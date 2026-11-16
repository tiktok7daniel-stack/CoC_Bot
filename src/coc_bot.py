from utils import *
try:
    from configs import *
except:
    from configs_build import *
import utils as _utils
import settings as bot_settings
import stats
from upgrader import Upgrader
from attacker import Attacker

class CoC_Bot:
    def __init__(self):
        self.upgrader = Upgrader()
        self.attacker = Attacker()
        self.cycle_count = 0
        self.session_start = None
        self.session_attacks = 0
        self.next_break = None
        self.upgrader.on_upgrade = self._on_upgrade

    def load_settings(self):
        """Re-read the account's GUI settings every cycle so changes apply without a restart."""
        try:
            import today_plan
            s = today_plan.overlay(bot_settings.load(_utils.INSTANCE_ID), _utils.INSTANCE_ID)   # today's plan on top
            bot_settings.apply(s)
        except Exception:
            logger.exception("CoC_Bot.load_settings: using previous settings")
            s = getattr(self, "settings", None) or bot_settings.default_settings()
        Task_Handler.cache_valid = False
        self.settings = s
        return s

    def storages_full(self, s):
        """User-set "storages full" levels reached -> skip attacking (nothing more to store)."""
        return False                       # never skip attacking: the bot keeps going (the user's choice)
        f = s["attack"].get("skip_when_full", {})
        res = getattr(self, "last_res", None)
        if not f.get("enabled") or not res: return False
        checks = [(res.get(k) or 0) >= int(f.get(k, 0)) for k in ("gold", "elixir") if int(f.get(k, 0)) > 0]
        return bool(checks) and all(checks)

    def read_and_record_resources(self, builder_base=False, max_age=0):
        import time
        cache = getattr(self, "_res_cache", None)
        if max_age and cache and cache[0] == builder_base and time.monotonic() - cache[1] < max_age:
            return cache[2]
        if not builder_base:      # the learned storage sizes: readings above them are misreads
            pass                  # (learned sizes are not used to reject readings: a wrong size made real numbers vanish)
        res = read_resources(builder_base=builder_base)
        self._res_cache = (builder_base, time.monotonic(), res)
        if res is not None and not builder_base: self.last_res = res
        if res is not None and not builder_base:
            stats.record(_utils.INSTANCE_ID, "resources", **res)
            logger.info(f"Resources: gold={res['gold']} elixir={res['elixir']} dark={res['dark']}")
        return res

    def attack_with_loot(self, base, attack_fn):
        """Run one attack and record the loot as the storage difference before/after."""
        builder = base == "builder"
        import time
        before = self.read_and_record_resources(builder_base=builder, max_age=20) # just read after the last attack
        t0 = time.monotonic()
        attack_fn()
        try:
            (to_builder_base if builder else to_home_base)()
        except Exception:
            pass
        after = self.read_and_record_resources(builder_base=builder)
        if not builder: self.learn_caps(before, after)
        loot = {}
        most = {"gold": 4_000_000, "elixir": 4_000_000, "dark": 60_000}   # more than one attack can bring = misread
        for k in ("gold", "elixir", "dark"):
            b, a = (before or {}).get(k), (after or {}).get(k)
            d = a - b if a is not None and b is not None else 0
            loot[k] = d if 0 <= d <= most[k] else 0
        extra = {"strategy": self.attacker.last_strategy} if base == "home" else {}
        stats.record(_utils.INSTANCE_ID, "attack", base=base, **loot, **extra)
        self.session_attacks += 1
        logger.info(f"Attack ({base}) loot: gold={loot['gold']} elixir={loot['elixir']} dark={loot['dark']}")
        logger.info(f"Attack took {time.monotonic() - t0:.0f}s")
        if (self.settings or {}).get("notify", {}).get("loot"):
            try: send_notification(f"غنيمة الهجوم: ذهب {loot['gold']:,} — إكسير {loot['elixir']:,} — دارك {loot['dark']:,}")
            except Exception: pass

    # ---------------------------------------------------------------- farm until full
    def _caps_path(self):
        from pathlib import Path
        return Path.home() / ".CoC_Bot" / f"caps_{_utils.INSTANCE_ID}.json"

    def caps(self):
        """Learned storage sizes {"gold": n, "elixir": n} (file version 2: older files could hold misreads)."""
        import json
        if getattr(self, "_caps", None) is None:
            try: d = json.loads(self._caps_path().read_text())
            except (OSError, ValueError): d = {}
            if d.get("v") != 2: d = {"v": 2}
            self._caps = d
        return self._caps

    def _save_caps(self):
        import json
        try: self._caps_path().write_text(json.dumps(self._caps))
        except OSError: pass

    def learn_caps(self, before, after):
        """
        A storage that didn't grow while the other one did may be full. Only learned when the same size is seen
        3 times and no bigger reading was ever seen (one misread can't set a wrong size any more).
        """
        if not before or not after: return
        caps = self.caps()
        seen = caps.setdefault("max_seen", {})
        cand = caps.setdefault("cand", {})
        gained = {k: (after.get(k) or 0) - (before.get(k) or 0) for k in ("gold", "elixir")}
        for k, other in (("gold", "elixir"), ("elixir", "gold")):
            v = after.get(k)
            if not v: continue
            if v > seen.get(k, 0): seen[k] = v
            if caps.get(k) and v > caps[k] * 1.02:                       # bigger than the size: upgraded / wrong
                caps.pop(k)
                logger.info(f"Storage size of {k} forgotten (read {v:,})")
            if v >= 1_000_000 and gained[k] <= 0 and gained[other] > 20000 and v >= seen.get(k, 0) * 0.98:
                c = cand.get(k) or {"v": v, "n": 0}
                c = {"v": v, "n": c["n"] + 1} if abs(c["v"] - v) <= v * 0.01 else {"v": v, "n": 1}
                cand[k] = c
                if c["n"] >= 3 and caps.get(k) != v:
                    caps[k] = v
                    logger.info(f"Learned the {k} storage size: {v}")
        self._save_caps()

    def full_resources(self, s):
        """Which storages are full now (user amount, else the learned storage size)."""
        f = s["attack"].get("farm", {})
        res = getattr(self, "last_res", None) or {}
        caps, full = self.caps(), []
        for k in ("gold", "elixir"):
            v, limit = res.get(k), int(f.get(f"{k}_full", 0) or 0)
            if not v: continue
            if limit > 0 and v >= limit: full.append(k)
            elif limit <= 0 and caps.get(k) and v >= caps[k] * 0.98: full.append(k)
        return full

    def spend_when_full(self, s):
        """Walls first (all of them that can be paid), then the normal upgrades. True if anything was spent."""
        # today's plan says no walls and no buildings -> don't spend, keep doing what was asked
        walls_ok = s.get("walls", {}).get("enabled") or s.get("attack", {}).get("farm", {}).get("max_walls")
        if not walls_ok and self.excluded("home_base"):
            if not getattr(self, "_full_plan_logged", False):
                logger.info("Storages full, but today's plan has no upgrades: going on with the plan")
                self._full_plan_logged = True
            return False
        before = dict(getattr(self, "last_res", None) or {})
        logger.info("Storages full: upgrading walls and buildings")
        set_phase("spend_full")
        self.upgrader.wall_budget = 10**6
        # storages full = spend on walls even when "wall upgrades" is off in the quick tasks
        prio = [list(l) for l in configs.HOME_BASE_UPGRADE_PRIORITY]
        if walls_ok and not any("Wall" in l for l in prio):
            configs.HOME_BASE_UPGRADE_PRIORITY = prio + [["Wall"]]
        to_home_base()
        try: self.upgrader.run_home_base(self.excluded("home_base"), self.excluded("home_lab"), self.excluded("pet_house"))
        except (KeyboardInterrupt, SystemExit): raise
        except Exception: logger.exception("Spending when full failed")
        configs.HOME_BASE_UPGRADE_PRIORITY = prio
        to_home_base()
        after = self.read_and_record_resources() or {}
        spent = any((before.get(k) or 0) - (after.get(k) or 0) > 1000 for k in ("gold", "elixir"))
        logger.info("Spent the loot, back to attacking" if spent else "Nothing could be bought")
        # wall-max mode: storages full and not one wall could be bought twice in a row -> every wall is maxed
        if s["attack"].get("farm", {}).get("max_walls"):
            if getattr(self.upgrader, "last_walls_done", 0) > 0: self.no_wall_streak = 0
            else: self.no_wall_streak = getattr(self, "no_wall_streak", 0) + 1
            if self.no_wall_streak >= 2 and not getattr(self, "walls_maxed_told", False):
                self.walls_maxed_told = True
                logger.info("All walls are maxed: wall-max mode is done")
                try: send_notification("كل الأسوار وصلت للماكس — وضع تمكيس الأسوار خلص")
                except Exception: pass
        return spent

    # ---------------------------------------------------------------- record a battle
    def record_battle(self, name):
        """Open the game, go into a battle by itself, then record the user's own taps until the battle ends."""
        import time, recorder
        iid = _utils.INSTANCE_ID
        set_phase("recording")
        recorder.set_status(iid, "opening")
        logger.info(f"Battle recording '{name}': opening the game and finding a base")
        try:
            start_coc()
            to_home_base()
            self.attacker.plan = None # the user's own army, no loadout
            if not self.attacker.start_normal_attack(60):
                recorder.set_status(iid, "failed")
                logger.warning("Battle recording cancelled: could not start a battle")
                return
            Input_Handler.zoom(dir="out")
            Input_Handler.swipe_up(y1=0.5)
            time.sleep(0.8)
            found = recorder.find_touch_device(lambda c: ADB_Manager.adbutils_device.shell(c))
            if not found:
                recorder.set_status(iid, "failed")
                logger.error("Battle recording failed: touch device not found")
                return
            rec = recorder.Recorder(ADB_Manager._adb_exe or "adb", _utils.ADB_ADDRESS, *found)
            rec.start()
            recorder.set_status(iid, "recording")
            logger.info("Battle recording: attack now, every tap is being recorded")
            start, gone = time.monotonic(), 0
            while time.monotonic() - start < 200:
                time.sleep(1)
                gone = 0 if self.attacker.in_battle() else gone + 1
                if gone >= 3: break
            rec.stop()
            time.sleep(0.3)
            data = rec.save(name)
            taps = sum(1 for e in data["events"] if e["type"] == "down")
            recorder.set_status(iid, "saved")
            logger.info(f"Battle recording '{name}' saved: {taps} taps, {data['duration']:.0f} seconds")
            self.attacker.battle_end = "wait"
            self.attacker.finish_battle(restart=True) # results screen -> back to the village
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            recorder.set_status(iid, "failed")
            logger.exception("Battle recording failed")

    def _on_upgrade(self, kind, name):
        stats.record(_utils.INSTANCE_ID, "upgrade", kind=kind, name=name)
        if kind != "wall": logger.info(f"Auto upgrade started: {name}")
        if (getattr(self, "settings", {}) or {}).get("notify", {}).get("auto_upgrade", True) and kind != "wall":
            try: send_notification(f"تم تطوير {name} بنجاح")
            except Exception: pass

    # ---------------------------------------------------------------- army learning
    def learn_army(self, name):
        """Watch the user prepare an army (from the village) and learn every tap with the word under it."""
        import time, army_learn, recorder
        iid = _utils.INSTANCE_ID
        set_phase("army_learning")
        army_learn.set_status(iid, "opening", name=name)
        logger.info(f"Army learning '{name}': opening the village")
        rec = None
        try:
            start_coc()
            to_home_base()
            found = recorder.find_touch_device(lambda c: ADB_Manager.adbutils_device.shell(c))
            if not found:
                army_learn.set_status(iid, "failed", name=name)
                logger.error("Army learning failed: touch device not found")
                return
            _dev, max_x, max_y = found
            rec = recorder.Recorder(ADB_Manager._adb_exe or "adb", _utils.ADB_ADDRESS, *found)
            rec.start()
            army_learn.set_status(iid, "watching", name=name, taps=0)
            logger.info("Army learning: prepare your army in the game now (open the army, pick / train it), then press Done")
            import cv2
            prev = Frame_Handler.get_frame(grayscale=False)
            downs, shots, seen, start, last_tap = [], [], 0, time.monotonic(), time.monotonic()
            while time.monotonic() - start < 300:
                if army_learn.stop_requested(iid): break
                if time.monotonic() - last_tap > 90 and downs: break       # forgot to press Done
                frame = Frame_Handler.get_frame(grayscale=False)
                now = time.monotonic()
                new = [e for e in rec.events[seen:] if e["type"] == "down"]
                seen = len(rec.events)
                for e in new: # the screen the user saw when tapping = the frame captured before this one
                    small = cv2.resize(prev, (1280, int(1280 * prev.shape[0] / prev.shape[1])))
                    shots.append((now - 0.2, small))
                    downs.append((now - 0.2, e["fx"], e["fy"]))
                    last_tap = now
                    army_learn.set_status(iid, "watching", name=name, taps=len(downs))
                prev = frame
                time.sleep(0.15)
            rec.stop()
            if not downs:
                army_learn.set_status(iid, "failed", name=name)
                logger.warning("Army learning cancelled: no taps were made")
                return
            army_learn.set_status(iid, "reading", name=name, taps=len(downs))
            logger.info(f"Army learning: reading the {len(downs)} steps")
            cache = {}
            def boxes_of(shot):
                k = id(shot[1])
                if k not in cache: cache[k] = ocr_boxes(shot[1])
                return cache[k]
            steps = army_learn.build_steps(downs, shots, boxes_of, max_x, max_y)
            data = {"name": name, "created": time.time(), "steps": steps, "touch": [max_x, max_y]}
            army_learn.save(data, shots[-1][1])     # the army screen right before the last tap
            words = [s["word"] for s in steps if s["word"]]
            army_learn.set_status(iid, "saved", name=name, taps=len(steps), words=len(words))
            logger.info(f"Army learned '{name}': {len(steps)} steps ({len(words)} by word: {', '.join(words[:6])})")
            try: # the picture also goes to the Claude learning inbox (composition is read there)
                import learn_sync
                learn_sync.queue_army(iid, name)
            except Exception: pass
            to_home_base()
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            army_learn.set_status(iid, "failed", name=name)
            logger.exception("Army learning failed")
        finally:
            if rec is not None: rec.stop()

    def capture_screens(self):
        """Capture mode: the user plays, the bot photographs every new screen (no taps by the bot)."""
        import time, cv2, capture_session as cs, recorder
        iid = _utils.INSTANCE_ID
        set_phase("capturing")
        session, folder = cs.new_session(iid)
        data = {"session": session, "account": iid, "started": time.time(), "state": "capturing", "shots": []}
        cs.save_session(iid, session, data)
        cs.set_status(iid, "starting", session=session, shots=0)
        logger.info("Capture mode: opening the game")
        rec = None
        try:
            start_coc()
            found = None
            try: found = recorder.find_touch_device(lambda c: ADB_Manager.adbutils_device.shell(c))
            except Exception: found = None
            if found:   # the user's taps: what was pressed to reach each screen
                rec = recorder.Recorder(ADB_Manager._adb_exe or "adb", _utils.ADB_ADDRESS, *found)
                rec.start()
            max_x, max_y = (found[1], found[2]) if found else (1, 1)
            cs.set_status(iid, "capturing", session=session, shots=0)
            logger.info("Capture mode: play now — every new screen is photographed. Press Done when finished")
            saved, prev_h, last_tap, start = [], None, None, time.monotonic()
            seen = 0
            data["battles"] = []
            battle, gone, next_check = None, 0, 0.0
            attacker = getattr(self, "attacker", None)
            while time.monotonic() - start < cs.MAX_MINUTES * 60 and len(saved) < cs.MAX_SHOTS:
                if cs.stop_requested(iid): break
                # ---- your attacks: the whole battle is recorded (taps + pictures), and kept as a replayable recording
                if attacker is not None and time.monotonic() >= next_check:
                    next_check = time.monotonic() + 1.0
                    try: fighting = attacker.in_battle()
                    except Exception: fighting = False
                    if fighting and battle is None:
                        battle = cs.start_battle(folder, len(data["battles"]) + 1, rec)
                        logger.info(f"Capture mode: battle #{battle['n']} started, watching your attack")
                        cs.set_status(iid, "capturing", session=session, shots=len(saved), battles=len(data["battles"]), in_battle=True)
                        gone = 0
                    elif battle is not None:
                        gone = 0 if fighting else gone + 1
                        if gone >= 3:
                            info = cs.end_battle(battle, rec, max_x, max_y, session)
                            data["battles"].append(info)
                            cs.save_session(iid, session, data)
                            logger.info(f"Capture mode: battle #{info['n']} recorded ({info['taps']} deploys, {info['frames']} pictures)")
                            cs.set_status(iid, "capturing", session=session, shots=len(saved), battles=len(data["battles"]))
                            battle = None
                frame = Frame_Handler.get_frame(grayscale=False)
                if battle is not None:
                    cs.battle_frame(battle, frame, rec)
                    time.sleep(0.25)
                    continue
                if rec is not None:
                    downs = [e for e in rec.events[seen:] if e["type"] == "down"]
                    seen = len(rec.events)
                    if downs:
                        import army_learn
                        x, y = army_learn.touch_to_screen(downs[-1]["fx"], downs[-1]["fy"], max_x, max_y)
                        last_tap = [round(x, 4), round(y, 4)]
                h = cs.dhash(frame)
                stable = prev_h is not None and cs.distance(h, prev_h) <= cs.STABLE
                prev_h = h
                if stable and cs.is_new(h, saved):
                    saved.append(h)
                    name = f"{len(saved):03d}.jpg"
                    small = cv2.resize(frame, (1280, int(1280 * frame.shape[0] / frame.shape[1])))
                    cv2.imwrite(str(folder / name), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
                    data["shots"].append({"file": name, "t": time.time(), "tap": last_tap, "hash": [str(h[0]), str(h[1])]})
                    cs.save_session(iid, session, data)
                    cs.set_status(iid, "capturing", session=session, shots=len(saved))
                    last_tap = None
                time.sleep(0.35)
            if battle is not None:      # stopped in the middle of a battle
                data["battles"].append(cs.end_battle(battle, rec, max_x, max_y, session))
            if rec is not None: rec.stop()
            # read the words of every picture (Claude gets them with the picture)
            cs.set_status(iid, "reading", session=session, shots=len(saved))
            logger.info(f"Capture mode: {len(saved)} screens photographed, reading them")
            for sh in data["shots"]:
                try:
                    img = cv2.cvtColor(cv2.imread(str(folder / sh["file"])), cv2.COLOR_BGR2RGB)
                    sh["words"] = [b[0] for b in ocr_boxes(img) if b[5] > 0.3][:60]
                except Exception:
                    sh["words"] = []
            data["state"] = "ready"
            data["ended"] = time.time()
            cs.save_session(iid, session, data)
            cs.set_status(iid, "ready", session=session, shots=len(saved))
            logger.info(f"Capture finished: {len(saved)} new screens ready to review and send")
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            data["state"] = "ready"
            cs.save_session(iid, session, data)
            cs.set_status(iid, "ready" if data["shots"] else "failed", session=session, shots=len(data["shots"]))
            logger.exception("Capture mode failed")
        finally:
            if rec is not None: rec.stop()

    def run_army(self, name):
        """Prepare a learned army: repeat the user's steps, finding each button by its word."""
        import time, army_learn
        data = army_learn.load(name)
        if not data or not data.get("steps"):
            logger.warning(f"Learned army '{name}' not found")
            return False
        set_phase("army_prepare")
        to_home_base()
        by_word = 0
        for i, st in enumerate(data["steps"]):
            if not running(): return False
            time.sleep(min(3.0, max(0.7, float(st.get("gap") or 0))))
            pos = None
            if st.get("word"):
                for _ in range(2):
                    pos = army_learn.find_word(ocr_boxes(Frame_Handler.get_frame(grayscale=False)), st["word"], (st["x"], st["y"]))
                    if pos: break
                    time.sleep(0.8)
            if pos: by_word += 1
            Input_Handler.click(*(pos or (st["x"], st["y"])))
        time.sleep(1.0)
        army_learn.count_use(name)
        logger.info(f"Army '{name}' prepared ({by_word}/{len(data['steps'])} steps found by word)")
        to_home_base()
        return True

    def prepare_army(self):
        """
        Before a home attack: the active loadout's learned army, if it has one. The game keeps (and refills) the
        last army by itself after every battle, so this runs once — again only when the army changed or after
        the game was reopened.
        """
        plan = self.attacker.plan or {}
        name = plan.get("army_macro")
        if not name: return
        if getattr(self, "_army_prepared", None) == (name, _utils.TEMP_CACHE.get("game_session")): return
        try:
            if self.run_army(name): self._army_prepared = (name, _utils.TEMP_CACHE.get("game_session"))
        except (KeyboardInterrupt, SystemExit): raise
        except Exception: logger.exception("Preparing the learned army failed")

    # ---------------------------------------------------------------- 1-tap commands from the window
    def run_commands(self):
        """Upgrade-now / batch walls / rescan requested from the window; True when something ran."""
        import village
        cmds = village.take_commands(_utils.INSTANCE_ID)
        if not cmds: return False
        set_phase("commands")
        try:
            start_coc()
            to_home_base()
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.warning("Commands postponed: the game / village is not reachable right now")
        if not in_home_base():
            # don't hammer the game with commands it can't do now: keep them for the next round (max 3 tries)
            for c in cmds:
                tries = int(c.get("tries", 0)) + 1
                if tries <= 3: village.push_command(_utils.INSTANCE_ID, c["cmd"], **{k: v for k, v in c.items() if k not in ("cmd", "t")}, tries=tries)
            logger.warning("Commands postponed: not in the village (will try again)")
            return False
        for c in cmds:
            if c.get("cmd") == "upgrade" and c.get("name"):
                logger.info(f"1-tap upgrade requested: {c['name']}")
                name = None
                try: name = self.upgrader.home_specified_upgrade([c["name"].lower()])
                except Exception: logger.exception("1-tap upgrade failed")
                if name:
                    logger.info(f"1-tap upgrade done: {name}")
                    self._on_upgrade("building", name)
                else:
                    logger.warning(f"1-tap upgrade not possible now: {c['name']} (busy builders, resources, or not in the menu)")
                to_home_base()
            elif c.get("cmd") == "army" and c.get("name"):
                logger.info(f"Prepare learned army requested: {c['name']}")
                try: self.run_army(c["name"])
                except Exception: logger.exception("Preparing the learned army failed")
                to_home_base()
            elif c.get("cmd") == "walls":
                n = max(1, int(c.get("count", 10)))
                logger.info(f"Batch wall upgrade requested: up to {n}")
                self.upgrader.wall_budget = n
                prio = [list(l) for l in configs.HOME_BASE_UPGRADE_PRIORITY]
                configs.HOME_BASE_UPGRADE_PRIORITY = [["Wall"]]
                try: self.upgrader.run_home_base(True, True, True)
                except Exception: logger.exception("Batch wall upgrade failed")
                finally: configs.HOME_BASE_UPGRADE_PRIORITY = prio
                to_home_base()
        if all(c.get("cmd") == "army" for c in cmds):
            return True
        try: village.scan(self.upgrader, _utils.INSTANCE_ID)  # fresh list + timers after every command
        except Exception: logger.exception("Village scan failed")
        to_home_base()
        return True

    def run_routines(self, s):
        """Tap the taught buttons of every enabled routine, in order (missing steps are skipped)."""
        import time, teach
        for r in s.get("routines", []):
            if not r.get("enabled") or not r.get("steps"): continue
            set_phase("routine_" + r.get("name", "custom"))
            done = 0
            for step in r["steps"]:
                key = step.get("key", "")
                if not teach.taught(key):
                    # buttons with a word on them can be learned on the spot
                    if Auto_Learn.learn_button(key, tap=True, min_interval=0): done += 1
                    time.sleep(max(0.0, float(step.get("wait", 0.5))))
                    continue
                n = tap_taught(key, multi=bool(step.get("multi")), timeout=2)
                done += n
                time.sleep(max(0.0, float(step.get("wait", 0.5))))
            logger.info(f"Routine {r.get('name')}: {done} taps")
            to_home_base()

    def announce_round(self, s):
        """One clear line per round: exactly which jobs it will do now (today's plan + settings)."""
        t = s.get("tasks", {})
        farm = s.get("attack", {}).get("farm", {})
        jobs = []
        if t.get("home_attacks") and (farm.get("enabled", True) or farm.get("max_walls")): jobs.append("attack & farm")
        if t.get("home_base"): jobs.append("buildings")
        if s.get("walls", {}).get("enabled") or farm.get("max_walls"): jobs.append("walls")
        if t.get("home_lab"): jobs.append("lab")
        if t.get("heroes") or t.get("pet_house"): jobs.append("heroes & pets")
        if t.get("builder_attacks") or t.get("builder_base") or t.get("builder_lab"): jobs.append("builder base")
        logger.info(f"Round {self.cycle_count + 1}: " + (", ".join(jobs) if jobs else "nothing to do"))

    def ask_today_plan(self):
        """Ask in the app what to do today; wait for the answer (the usual after ASK_TIMEOUT)."""
        import time, today_plan
        iid = _utils.INSTANCE_ID
        set_phase("idle")
        today_plan.ask(iid)
        logger.info("Waiting for today's plan (choose in the app)")
        try: send_notification("🎮 اللعبة جاهزة — افتح Clash Farmer واختار عاوز تعمل إيه النهارده")
        except Exception: pass
        start = time.monotonic()
        while time.monotonic() - start < today_plan.ASK_TIMEOUT:
            p = today_plan.load(iid)
            if p:
                logger.info(f"Today's plan: {today_plan.describe(p)}")
                return p
            if not running(): break
            time.sleep(1)
        today_plan.cancel_ask(iid)
        if today_plan.load(iid) is None:
            p = today_plan.save(iid, "usual", auto=True)
            logger.info("No answer: doing the usual today")
            return p

    def excluded(self, task):
        """Fresh read of the GUI toggle, so changes made mid-cycle apply to the next step."""
        return Task_Handler.excluded(task)

    def idle(self, minutes):
        """
        Wait between cycles, but wake up early when the user presses "run now"
        or changes settings in the GUI (applies them right away while the game is open).
        """
        import time, random
        start = time.monotonic()
        seen_mtime = bot_settings.mtime(_utils.INSTANCE_ID)
        changed_at = None
        game = getattr(self, "settings", None) or {}
        game = game.get("game", {})
        # the game disconnects players who don't touch the screen for a few minutes:
        # while the game is kept open, nudge the map now and then like a player would
        anti_idle = game.get("keep_open", True) and game.get("anti_idle", True)
        next_nudge = time.monotonic() + random.uniform(70, 110)
        while time.monotonic() - start < minutes * 60:
            time.sleep(2)
            try:
                import recorder
                if recorder.pending(_utils.INSTANCE_ID): return
                import village
                if village.pending(_utils.INSTANCE_ID): return
                import army_learn
                if army_learn.pending(_utils.INSTANCE_ID): return
                import capture_session
                if capture_session.pending(_utils.INSTANCE_ID): return
                import learn_sync
                learn_sync.tick(_utils.INSTANCE_ID)    # upload unknown screens / fetch what Claude taught
            except Exception: pass
            if anti_idle and time.monotonic() >= next_nudge and running():
                next_nudge = time.monotonic() + random.uniform(70, 110)
                try:
                    if game_ready():
                        dy = random.uniform(0.03, 0.06)
                        Input_Handler.swipe(0.5, 0.5, 0.5, 0.5 + dy, duration=200)
                        Input_Handler.swipe(0.5, 0.5 + dy, 0.5, 0.5, duration=200)
                except (KeyboardInterrupt, SystemExit): raise
                except Exception:
                    pass
            if bot_settings.consume_wake(_utils.INSTANCE_ID):
                logger.info("Run now requested")
                return
            m = bot_settings.mtime(_utils.INSTANCE_ID)
            if m != seen_mtime:
                seen_mtime, changed_at = m, time.monotonic()
            # wait until the user stops clicking for a few seconds
            if changed_at is not None and time.monotonic() - changed_at > 4:
                s = self.load_settings()
                if s["game"]["apply_instantly"]:
                    logger.info("Settings changed, applying now")
                    return
                changed_at = None

    def run(self):
        import time

        import random
        stats.record(_utils.INSTANCE_ID, "session_start")
        self.session_start = time.time()
        consecutive_errors = 0
        # the brain: always knows what the screen is (newest live picture, or the last picture the bot took)
        try:
            import screen_model, stream_capture
            def newest():
                c = stream_capture._S.get("client")
                img = c.latest() if c is not None and c.alive else None
                return img if img is not None else Frame_Handler.cached_frame
            screen_model.watch(_utils.INSTANCE_ID, newest, logger)
        except Exception:
            logger.debug("Screen watcher not started", exc_info=True)
        while True:
            try:
                s = self.load_settings()

                if not online():
                    if not getattr(self, "_offline_logged", False):
                        logger.warning("No internet connection, waiting")
                        self._offline_logged = True
                    update_status("error")
                    time.sleep(3)
                    continue
                self._offline_logged = False

                import village
                if village.pending(_utils.INSTANCE_ID):
                    update_status("now")
                    self.run_commands()
                    continue

                import capture_session
                if capture_session.take_request(_utils.INSTANCE_ID):
                    update_status("now")
                    self.capture_screens()
                    continue

                import army_learn
                areq = army_learn.take_request(_utils.INSTANCE_ID)
                if areq:
                    update_status("now")
                    self.learn_army(areq.get("name") or "army")
                    continue

                import recorder
                req = recorder.take_request(_utils.INSTANCE_ID)
                if req:
                    update_status("now")
                    self.record_battle(req.get("name") or "battle")
                    continue

                if not running():
                    update_status("paused")
                    time.sleep(5)
                    continue

                if not bot_settings.in_schedule(s):
                    update_status("scheduled")
                    self.idle(1)
                    continue

                # no attack limit, no hour limit, no breaks: the bot keeps going until you stop it

                set_phase("start_game")
                if TEMP_CACHE.pop("restart_game", False):
                    started, res = start_coc(detailed=True, force_restart="watchdog: a step was stuck")
                else:
                    started, res = start_coc(detailed=True)
                if started:
                    # ---- today's plan: asked once a day as soon as the game is open
                    import today_plan
                    iid = _utils.INSTANCE_ID
                    if today_plan.load(iid) is None and bot_settings.load_app().get("ask_plan", True) is not False:
                        self.ask_today_plan()
                        continue
                    if today_plan.mode(iid) == "nothing":
                        if not getattr(self, "_nothing_logged", False):
                            logger.info("Today's plan: nothing — the game stays open, the bot waits for you")
                            self._nothing_logged = True
                        update_status("idle")
                        self.idle(2)
                        continue
                    self._nothing_logged = False
                    update_status("now")
                    cycle_start = time.monotonic()
                    self.announce_round(s)
                    self.cycle_count += 1

                    # Battle / wall / budget settings for this cycle
                    self.attacker.battle_end = s["attack"]["battle_end"]
                    self.attacker.smart_end = s["attack"].get("smart_end", True)
                    self.attacker.leave_after = max(0, float(s["attack"].get("leave_after", 0)))
                    sea = int(s["attack"].get("smart_end_after", 8))
                    self.attacker.smart_end_after = 8 if sea == 15 else max(5, sea)   # 15 = the old slow default
                    self.attacker.strategy = s["attack"]["strategy"]
                    self.attacker.loot_filter = s["attack"]["loot_filter"]
                    self.attacker.plan = next((p for p in s.get("plans", []) if p.get("name") and p.get("name") == s.get("active_plan")), None)
                    Auto_Learn.enabled = bool(s["game"].get("auto_learn", True))
                    self.attacker.hero_delay = max(0.0, float(s["attack"]["hero_delay"]))
                    self.attacker.hero_retap = max(0.0, float(s["attack"]["hero_retap"]))
                    self.attacker.surrender_after = max(0, int(s["attack"]["surrender_after"]))
                    walls = s["walls"]
                    wall_turn = walls["enabled"] and self.cycle_count % max(1, int(walls["every_cycles"])) == 0
                    self.upgrader.wall_budget = max(0, int(walls["max_per_run"])) if wall_turn else 0
                    self.upgrader.budget = s["budget"] if s["budget"]["enabled"] else None

                    up_turn = self.cycle_count % max(1, int(s["upgrades"].get("every_cycles", 1))) == 0 or self.cycle_count == 1
                    def home_upgrades_wanted():
                        if not up_turn: return False
                        if walls["enabled"] and self.upgrader.wall_budget > 0: return True # walls work even with buildings off
                        return not (self.excluded("home_base") and self.excluded("home_lab") and self.excluded("pet_house"))
                    def builder_upgrades_wanted():
                        if not up_turn: return False
                        return not (self.excluded("builder_base") and self.excluded("builder_lab"))

                    # ---- Home village
                    if running() and (home_upgrades_wanted() or not self.excluded("home_attacks")):
                        set_phase("to_home")
                        to_home_base(ref_cache=True)
                        set_phase("read_resources")
                        self.read_and_record_resources()
                        # free things now and then (the daily "Free!" gift): every few hours, never anything paid
                        try:
                            import daily_rewards
                            if bot_settings.load_app().get("daily_rewards", True) is not False:
                                set_phase("daily_rewards")
                                daily_rewards.run()
                        except (KeyboardInterrupt, SystemExit): raise
                        except Exception: logger.debug("Daily rewards failed", exc_info=True)

                    if running():
                        self.run_routines(s)

                    if running() and home_upgrades_wanted():
                        set_phase("home_upgrades")
                        logger.info("Upgrading home base")
                        self.load_settings()
                        self.upgrader.run_home_base(self.excluded("home_base"), self.excluded("home_lab"), self.excluded("pet_house"))
                        # read the builder menu for the Upgrade Deck only now and then (every 3 hours), not every round:
                        # the button "Scan village now" in the app does it on request
                        import village, time as _t
                        if _t.time() - float((village.load(_utils.INSTANCE_ID) or {}).get("t", 0) or 0) > 3 * 3600:
                            try:
                                set_phase("village_scan")
                                to_home_base()
                                village.scan(self.upgrader, _utils.INSTANCE_ID)
                            except Exception: logger.exception("Village scan failed")

                    farm = self.settings["attack"].get("farm", {})
                    if running() and not self.excluded("home_attacks") and (farm.get("enabled", True) or farm.get("max_walls")):
                        # attack non-stop; when the storages are full spend them, then attack again
                        attacks = 0
                        import recorder
                        import village
                        import army_learn
                        while running() and not self.excluded("home_attacks") and not recorder.pending(_utils.INSTANCE_ID) \
                                and not village.pending(_utils.INSTANCE_ID) and not army_learn.pending(_utils.INSTANCE_ID) \
                                and not __import__("capture_session").pending(_utils.INSTANCE_ID):
                            self.load_settings()
                            f_now = self.settings["attack"].get("farm", {})
                            if not (f_now.get("enabled", True) or f_now.get("max_walls")): break
                            plan_blocks_spending = not (self.settings.get("walls", {}).get("enabled") or f_now.get("max_walls")) \
                                and self.excluded("home_base")
                            if self.full_resources(self.settings) and not plan_blocks_spending:
                                # spent something: go round again (more walls to buy, or attack once not full);
                                # rest only when nothing at all could be bought
                                if self.spend_when_full(self.settings): continue
                                # nothing to buy: keep attacking anyway (the bot never stops by itself)
                                if not getattr(self, "_full_logged", False):
                                    logger.info("Storages full and nothing to spend on: attacking on")
                                    self._full_logged = True
                            else:
                                self._full_logged = False
                            set_phase("home_attack")
                            attacks += 1
                            logger.info(f"Attacking home base (#{attacks})")
                            self.attacker.choose_strategy([e for e in stats.read(_utils.INSTANCE_ID) if e["type"] == "attack" and e.get("base") == "home"][-60:])
                            self.prepare_army()
                            self.attack_with_loot("home", lambda: self.attacker.run_home_base(restart=True))
                    elif running() and not self.excluded("home_attacks") and self.storages_full(self.settings):
                        logger.info("Storages are full, skipping home attacks")
                    elif running() and not self.excluded("home_attacks"):
                        n = max(1, int(self.settings["attack"]["home_attacks_per_cycle"]))
                        for i in range(n):
                            if not running() or self.excluded("home_attacks"): break
                            set_phase("home_attack")
                            logger.info(f"Attacking home base ({i + 1}/{n})")
                            self.attacker.choose_strategy([e for e in stats.read(_utils.INSTANCE_ID) if e["type"] == "attack" and e.get("base") == "home"][-60:])
                            self.prepare_army()
                            self.attack_with_loot("home", lambda: self.attacker.run_home_base(restart=True))
                            # optionally spend the new loot on walls between farming attacks
                            w = self.settings["walls"]
                            if i < n - 1 and w["enabled"] and w["during_farming"] and not self.excluded("home_base"):
                                set_phase("walls_farming")
                                to_home_base()
                                self.upgrader.wall_budget = max(0, int(w["max_per_run"]))
                                self.upgrader.run_home_base(False, True, True)

                    # ---- Builder base
                    if running() and (builder_upgrades_wanted() or not self.excluded("builder_attacks")):
                        set_phase("to_builder")
                        to_builder_base(ref_cache=True)

                        if builder_upgrades_wanted():
                            set_phase("builder_upgrades")
                            logger.info("Upgrading builder base")
                            self.load_settings()
                            self.upgrader.collect_builder_attack_elixir()
                            self.upgrader.run_builder_base(self.excluded("builder_base"), self.excluded("builder_lab"))

                        if not self.excluded("builder_attacks"):
                            n = max(1, int(self.settings["attack"]["builder_attacks_per_cycle"]))
                            for i in range(n):
                                if not running() or self.excluded("builder_attacks"): break
                                set_phase("builder_attack")
                                logger.info(f"Attacking builder base ({i + 1}/{n})")
                                self.attack_with_loot("builder", self.attacker.run_builder_base)

                    set_phase("finish")
                    to_home_base()
                    if not self.settings["game"]["keep_open"]:
                        stop_coc(sleep=configs.SUSPEND_EMULATOR_ON_IDLE, reason="keep game open is off")
                    update_status(time.time())
                    seconds = time.monotonic() - cycle_start
                    stats.record(_utils.INSTANCE_ID, "cycle", seconds=round(seconds))
                    logger.info(f"Cycle finished in {seconds:.0f}s")
                    consecutive_errors = 0
                elif res == "error":
                    update_status("error")

                set_phase("idle")
                # attacks on: straight into the next round; otherwise look again in a few minutes
                self.idle(0.05 if not self.excluded("home_attacks") or not self.excluded("builder_attacks") else configs.CHECK_INTERVAL)

            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                consecutive_errors += 1
                logger.exception(f"CoC_Bot.run (error #{consecutive_errors} in a row):")
                if consecutive_errors == 3:
                    send_notification(f"Bot failed 3 times in a row, last error: {type(e).__name__}: {e}")
                # one-off error: leave the game open and just try again; close it only if errors repeat
                if consecutive_errors >= 2:
                    try: stop_coc(reason=f"{consecutive_errors} errors in a row")
                    except (KeyboardInterrupt, SystemExit): raise
                    except Exception: logger.exception("CoC_Bot.run: stop_coc failed")
                update_status("error")
                # retry quickly after a one-off glitch, back off when something is persistently broken
                wait = 1 if consecutive_errors == 1 else configs.CHECK_INTERVAL * min(consecutive_errors - 1, 6)
                self.idle(wait)
