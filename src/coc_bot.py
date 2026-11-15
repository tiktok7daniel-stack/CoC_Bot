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
        self.upgrader.on_upgrade = lambda kind, name: stats.record(_utils.INSTANCE_ID, "upgrade", kind=kind, name=name)

    def load_settings(self):
        """Re-read the account's GUI settings every cycle so changes apply without a restart."""
        try:
            s = bot_settings.load(_utils.INSTANCE_ID)
            bot_settings.apply(s)
        except Exception:
            logger.exception("CoC_Bot.load_settings: using previous settings")
            s = getattr(self, "settings", None) or bot_settings.default_settings()
        Task_Handler.cache_valid = False
        self.settings = s
        return s

    def storages_full(self, s):
        """User-set "storages full" levels reached -> skip attacking (nothing more to store)."""
        f = s["attack"].get("skip_when_full", {})
        res = getattr(self, "last_res", None)
        if not f.get("enabled") or not res: return False
        checks = [(res.get(k) or 0) >= int(f.get(k, 0)) for k in ("gold", "elixir") if int(f.get(k, 0)) > 0]
        return bool(checks) and all(checks)

    def read_and_record_resources(self, builder_base=False):
        res = read_resources(builder_base=builder_base)
        if res is not None and not builder_base: self.last_res = res
        if res is not None and not builder_base:
            stats.record(_utils.INSTANCE_ID, "resources", **res)
            logger.info(f"Resources: gold={res['gold']} elixir={res['elixir']} dark={res['dark']}")
        return res

    def attack_with_loot(self, base, attack_fn):
        """Run one attack and record the loot as the storage difference before/after."""
        builder = base == "builder"
        before = self.read_and_record_resources(builder_base=builder)
        attack_fn()
        try:
            (to_builder_base if builder else to_home_base)()
        except Exception:
            pass
        after = self.read_and_record_resources(builder_base=builder)
        loot = {}
        for k in ("gold", "elixir", "dark"):
            b, a = (before or {}).get(k), (after or {}).get(k)
            loot[k] = max(0, a - b) if a is not None and b is not None else 0
        extra = {"strategy": self.attacker.last_strategy} if base == "home" else {}
        stats.record(_utils.INSTANCE_ID, "attack", base=base, **loot, **extra)
        self.session_attacks += 1
        logger.info(f"Attack ({base}) loot: gold={loot['gold']} elixir={loot['elixir']} dark={loot['dark']}")

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

                if not running():
                    update_status("paused")
                    time.sleep(5)
                    continue

                if not bot_settings.in_schedule(s):
                    update_status("scheduled")
                    self.idle(1)
                    continue

                # End conditions
                lim = s["limits"]
                if (lim["max_attacks"] and self.session_attacks >= lim["max_attacks"]) or \
                   (lim["max_hours"] and time.time() - self.session_start >= lim["max_hours"] * 3600):
                    if getattr(self, "_limit_logged", False) is False:
                        logger.info("Session limit reached, bot is resting")
                        self._limit_logged = True
                        try: stop_coc(reason="session limit")
                        except Exception: pass
                    update_status("limit")
                    self.idle(1)
                    continue
                self._limit_logged = False

                # Humanized breaks
                br = s["breaks"]
                if br["enabled"]:
                    if self.next_break is None:
                        self.next_break = time.time() + br["every_minutes"] * 60 * random.uniform(0.8, 1.2)
                    elif time.time() >= self.next_break:
                        length = max(1, br["length_minutes"] * random.uniform(0.7, 1.3))
                        logger.info(f"Taking a break for {length:.0f} min")
                        try: stop_coc(reason="break")
                        except Exception: pass
                        update_status("break")
                        self.idle(length)
                        self.next_break = None
                        continue
                else:
                    self.next_break = None

                set_phase("start_game")
                started, res = start_coc(detailed=True)
                if started:
                    update_status("now")
                    cycle_start = time.monotonic()
                    self.cycle_count += 1

                    # Battle / wall / budget settings for this cycle
                    self.attacker.battle_end = s["attack"]["battle_end"]
                    self.attacker.smart_end = s["attack"].get("smart_end", True)
                    self.attacker.leave_after = max(0, float(s["attack"].get("leave_after", 0)))
                    self.attacker.smart_end_after = max(5, int(s["attack"].get("smart_end_after", 15)))
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

                    def home_upgrades_wanted():
                        return not (self.excluded("home_base") and self.excluded("home_lab") and self.excluded("pet_house"))
                    def builder_upgrades_wanted():
                        return not (self.excluded("builder_base") and self.excluded("builder_lab"))

                    # ---- Home village
                    if running() and (home_upgrades_wanted() or not self.excluded("home_attacks")):
                        set_phase("to_home")
                        to_home_base(ref_cache=True)
                        set_phase("read_resources")
                        self.read_and_record_resources()

                    if running():
                        self.run_routines(s)

                    if running() and home_upgrades_wanted():
                        set_phase("home_upgrades")
                        logger.info("Upgrading home base")
                        self.load_settings()
                        self.upgrader.run_home_base(self.excluded("home_base"), self.excluded("home_lab"), self.excluded("pet_house"))

                    if running() and not self.excluded("home_attacks") and self.storages_full(self.settings):
                        logger.info("Storages are full, skipping home attacks")
                    elif running() and not self.excluded("home_attacks"):
                        n = max(1, int(self.settings["attack"]["home_attacks_per_cycle"]))
                        for i in range(n):
                            if not running() or self.excluded("home_attacks"): break
                            set_phase("home_attack")
                            logger.info(f"Attacking home base ({i + 1}/{n})")
                            self.attacker.choose_strategy([e for e in stats.read(_utils.INSTANCE_ID) if e["type"] == "attack" and e.get("base") == "home"][-60:])
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
                self.idle(configs.CHECK_INTERVAL)

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
