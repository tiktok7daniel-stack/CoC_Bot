from utils import *
try:
    import configs
    from configs import *
except:
    import configs_build as configs
    from configs_build import *

class Attacker:
    def __init__(self):
        self.assets = Asset_Manager.attacker_assets
        self.misc_assets = Asset_Manager.misc_assets
        self.deployed_heroes = []
        self.deployed_troops = []
        self.held_spells = []
        self.plan = None             # active loadout (attack plan) dict, None = classic single point
        self.loot_filter = None      # {"enabled", "min_gold", "min_elixir", "min_dark", "mode", "max_skips"}
        self.strategy = "funnel"   # "funnel" | "line" | "two_sides" | "auto" (learns the best)
        self.last_strategy = "funnel"
        self.hero_delay = 1.0      # seconds between the army and the heroes
        self.hero_retap = 0        # seconds after deploying to fire hero abilities (0 = off)
        self.battle_end = "wait"    # "wait": stay in game until the battle ends | "restart": reopen the game (faster)
        self.surrender_after = 0    # seconds after deployment to end the battle early (0 = never)
        self.smart_end = True       # end the battle once the enemy loot stops going down
        self.leave_after = 0        # battle_end "leave": seconds after deploying before ending
        self.smart_end_after = 15   # seconds without loot change before ending

    def in_battle(self):
        """End Battle / Surrender button visible = the battle is still running."""
        if red_battle_button() is not None: return True                  # by its colour: works on every version
        if find_taught("end_battle"): return True
        x, y = Frame_Handler.locate(self.assets["end_battle"], thresh=0.9)
        if x is not None: return True
        x, y = Frame_Handler.locate(self.assets["surrender"], thresh=0.9, use_cached=True)
        return x is not None

    def finish_battle(self, restart=True, max_wait=200):
        """
        End the battle after all troops are deployed.
        "wait" keeps the game open: wait for the results screen (or surrender after
        surrender_after seconds) and press Return Home. Falls back to reopening the game.
        """
        import time

        if self.battle_end == "restart" and not never_close():
            if restart: start_coc(force_restart="battle end mode = restart")
            else: stop_coc(reason="battle end mode = restart")
            return

        import teach
        start = time.monotonic()
        surrendered = False
        self._next_words = 0
        self._left_battle = None
        self._speed_done, self._speed_taps, next_speed = False, 0, 0.0
        leave = self.battle_end == "leave"
        surrender_after = (self.leave_after if leave else self.surrender_after)
        if leave:
            if self.leave_after > 0: time.sleep(self.leave_after)
            logger.info("Army deployed, leaving the battle right away")
            if self._click_end_battle(timeout=2) or Auto_Learn.learn_button("end_battle", tap=True):
                time.sleep(0.5)
                if not self._click_okay(timeout=3): Auto_Learn.learn_button("okay_button", tap=True, min_interval=0)
                surrendered = True
        smart = self.smart_end and not leave and teach.taught("enemy_gold") and teach.taught("enemy_elixir")
        # without the taught numbers: watch the "Available Loot" numbers top-left by their pixels (no reading)
        # always: the Available Loot (top left) and the Overall Damage % (bottom right) watched by their pixels
        smart_px = self.smart_end and not leave
        loot_img = None
        last_loot, last_change, next_read, dropped = None, time.monotonic(), 0, False
        while time.monotonic() - start < max_wait:
            if not running(): break
            if not surrendered and getattr(self, "_later", None) and self.in_battle():
                self.run_due()                           # hero abilities / second spell wave when their time comes
            # the last minute: battle speed 4x (the game shows the button then)
            if not surrendered and not self._speed_done and time.monotonic() >= next_speed and self.battle_speed:
                next_speed = time.monotonic() + 1.5
                try: self.speed_up()
                except Exception: logger.debug("speed_up failed", exc_info=True)
            if smart_px and not surrendered and time.monotonic() >= next_read:
                next_read = time.monotonic() + 1.0
                try:
                    import numpy as np
                    fr = Frame_Handler.get_frame(grayscale=True)
                    cur = np.concatenate([Frame_Handler.crop(fr, 0.04, 0.12, 0.17, 0.27).astype(int).ravel(),
                                          Frame_Handler.crop(fr, 0.85, 0.70, 0.99, 0.78).astype(int).ravel()])
                    if loot_img is not None and cur.shape == loot_img.shape and float(np.abs(cur - loot_img).mean()) > 3:
                        dropped, last_change = True, time.monotonic()
                    if loot_img is None: last_change = time.monotonic()
                    loot_img = cur
                    # nothing more is being taken or destroyed: leave. Before anything was destroyed (troops still
                    # walking in) the bot waits longer
                    wait = self.smart_end_after if dropped else max(20, self.smart_end_after)
                    stalled = time.monotonic() - last_change > wait and time.monotonic() - start > 10
                    if stalled and self.in_battle():
                        logger.info(f"Nothing taken or destroyed for {wait:.0f}s, ending the battle")
                        if self._click_end_battle(timeout=0) or Auto_Learn.learn_button("end_battle", tap=True):
                            time.sleep(0.4)
                            if not self._click_okay(timeout=3): Auto_Learn.learn_button("okay_button", tap=True, min_interval=0)
                            surrendered = True
                except Exception:
                    smart_px = False
            # smart end: the remaining enemy loot (top-left) stopped going down -> nothing more to take
            if smart and not surrendered and time.monotonic() >= next_read:
                next_read = time.monotonic() + 1.5
                try:
                    frame = Frame_Handler.get_frame(grayscale=False)
                    vals = [read_taught_number(k, frame) for k in ("enemy_gold", "enemy_elixir")]
                except Exception:
                    vals = [None, None]
                if all(v is not None for v in vals):
                    if last_loot is None or any(v < o for v, o in zip(vals, last_loot)):
                        if last_loot is not None: dropped = True # troops are taking loot
                        last_change = time.monotonic()
                    last_loot = [v if o is None else min(v, o) for v, o in zip(vals, last_loot or [None, None])]
                # only after the loot went down at least once (troops still walking in is not "stopped"),
                # or when nothing at all was taken for 45 seconds
                stalled = time.monotonic() - last_change > (self.smart_end_after if dropped else max(30, self.smart_end_after))
                if last_loot is not None and stalled and self.in_battle():
                    logger.info(f"Loot stopped for {self.smart_end_after}s, ending the battle early")
                    if self._click_end_battle(timeout=0) or Auto_Learn.learn_button("end_battle", tap=True):
                        time.sleep(0.4)
                        if not self._click_okay(timeout=3): Auto_Learn.learn_button("okay_button", tap=True, min_interval=0)
                        surrendered = True
            # instant checks by colour (no reading): the results screen's green button, or already back home
            # (the battle ended by hand / by the game) -> go on at once
            frame = Frame_Handler.get_frame(grayscale=False)
            if bottom_green_button(frame):
                self.ended_at = time.monotonic()
                logger.info("Battle over, collecting the reward")
                if collect_rewards(): return
                continue
            if in_home_base(fast=True):
                try: __import__("screen_model").teach_self(__import__("utils").INSTANCE_ID, frame, "village_home")
                except Exception: pass
                self.ended_at = time.monotonic()
                logger.info("Battle over, already back in the village")
                TEMP_CACHE["location"] = "home_base"
                return
            if time.monotonic() - start > 1.5 and in_builder_base():
                TEMP_CACHE["location"] = "builder_base"
                return
            # results screen not recognised by colour: read it now and then (reading takes ~1 s)
            # (only when the colours haven't told what the screen is for a few seconds after the battle ended)
            if time.monotonic() - start > 1.5 and not self.in_battle():
                if self._left_battle is None: self._left_battle = time.monotonic()
            else:
                self._left_battle = None
            if self._left_battle is not None and time.monotonic() - self._left_battle > 4 \
                    and time.monotonic() >= getattr(self, "_next_words", 0):
                self._next_words = time.monotonic() + 3
                words = " ".join(b[0].lower() for b in ocr_boxes(frame) if b[5] > 0.3)
                if ("claim" in words and "reward" in words) or "continue" in words or "delivered" in words or "storage" in words \
                        or any(w in words for w in CHEST_WORDS) \
                        or (("victory" in words or "defeat" in words) and ("bonus" in words or "damage" in words)):
                    logger.info("Battle over, collecting the reward")
                    if collect_rewards(): return
            if self._click_return_home(timeout=0):
                self.ended_at = time.monotonic()
                logger.info("Battle over, returning home")
                time.sleep(0.3)
                for _ in range(80): # the village usually shows within 2-4 s
                    if game_ready(fast=True): return
                    if bottom_green_button():
                        if collect_rewards(): return
                    time.sleep(0.15)
                break
            # optional early end: End Battle -> confirm
            if not surrendered and (surrender_after > 0 or leave) and time.monotonic() - start > surrender_after:
                if self._click_end_battle(timeout=0) or Auto_Learn.learn_button("end_battle", tap=True):
                    time.sleep(0.7)
                    if not self._click_okay(timeout=3): Auto_Learn.learn_button("okay_button", tap=True, min_interval=0)
                    surrendered = True
            # results screen not recognised yet -> once the battle is over (no End Battle button),
            # find "Return Home" by its text and learn it
            if time.monotonic() - start > 15 and not self.in_battle() and Auto_Learn.learn_button("return_home", tap=True, min_interval=12):
                time.sleep(0.3)
                for _ in range(60):
                    if game_ready(fast=True): return
                    time.sleep(0.2)
            time.sleep(0.25)                             # notice the results screen right away
        # (no Android back key here: in the village it opens the "exit game?" dialog)
        if game_ready() or collect_rewards(timeout=15): return
        logger.warning("Battle end not detected, reopening the game")
        if restart: start_coc(force_restart="results screen not recognised")
        else: stop_coc(reason="results screen not recognised")

    # ============================================================
    # 📱 Screen Interaction
    # ============================================================
    
    def _click_okay(self, timeout=5):
        import time
        end = time.monotonic() + max(0.5, timeout)
        while time.monotonic() < end:
            if tap_taught("okay_button", timeout=0): return True # taught from the user's screen wins
            x, y = Frame_Handler.locate(self.assets["okay"], thresh=0.9)
            if x is not None:
                Input_Handler.click(x, y)
                return True
            g = green_center_button()                             # the confirm window's green Okay, by colour
            if g is not None:
                Input_Handler.click(*g)
                return True
            time.sleep(0.15)
        return False
    
    def _click_surrender(self, timeout=5):
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["surrender"], thresh=0.9),
            timeout=timeout
        )
    
    def _click_end_battle(self, timeout=5):
        r = red_battle_button()                                   # the red button at the left, by colour
        if r is not None:
            Input_Handler.click(*r)
            return True
        if tap_taught("end_battle", timeout=timeout): return True # taught from the user's screen wins
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["end_battle"], thresh=0.9),
            timeout=timeout
        )
    
    def _click_return_home(self, timeout=5):
        if tap_taught("return_home", timeout=timeout): return True # taught from the user's screen wins
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["return_home"], thresh=0.9),
            timeout=timeout
        )

    def start_normal_attack(self, timeout=60):
        import time, numpy as np

        # Click attack
        Input_Handler.click(0.07, 0.9)

        # Find a match
        find_a_match_temp = render_text("Find a Match", "SupercellMagic", 29)
        battle_temp = render_text("Battle", "SupercellMagic", 37)
        def locate_find_a_match():
            frame = Frame_Handler.get_frame(grayscale=True, high_contrast=True)
            bx, by = Frame_Handler.locate(battle_temp, frame, thresh=0.9)
            if bx is None or by is None: return None, None
            xys = Frame_Handler.locate(find_a_match_temp, frame, thresh=0.9, return_all=True)
            xys = [xy for xy in xys if xy[0] is not None and xy[1] is not None]
            if len(xys) == 0: return None, None
            xys = np.array(xys, dtype=float)
            dists = abs(xys[:, 0] - bx)
            if min(dists) > 0.01: return None, None
            x, y = xys[np.argmin(dists)]
            if x is None or y is None: return None, None
            return x, y
        # React to what the game shows (older: "Find a Match" window; current: the army screen with a green
        # "Attack!" button at the bottom right, then sometimes a confirm) until the search for a base starts.
        army_done, started, next_read = False, False, time.monotonic() + 1.0
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and running():
            if find_taught("end_battle") or Frame_Handler.locate(self.assets["end_battle"], thresh=0.9) != (None, None):
                started = True
                break
            # the army screen: the green "Attack!" at the bottom right (colour, instant) — checked first
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            is_army = army_screen_open(frame)
            if not is_army:
                x, y = locate_find_a_match()
                if x is not None:
                    Input_Handler.click(x, y)
                    time.sleep(0.4)
                    continue
                x, y = Frame_Handler.locate(self.assets["confirm_attack"], thresh=0.9, use_cached=True)
                if x is not None:
                    Input_Handler.click(x, y)
                    started = True
                    break
                frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            # its tabs are read only as a fallback
            if not is_army and time.monotonic() >= next_read:
                next_read = time.monotonic() + 2
                top = Frame_Handler.crop(frame, 0.0, 0.0, 1.0, 0.15)
                words = " ".join(b[0].lower() for b in ocr_boxes(top) if b[5] > 0.3)
                is_army = "army" in words and ("recipes" in words or "cookbook" in words or "saved" in words)
            if is_army:
                try: __import__("screen_model").teach_self(__import__("utils").INSTANCE_ID, frame, "army_screen")
                except Exception: pass
                if not army_done:      # the saved army of the active loadout, on this very screen
                    army_done = True
                    want = ((self.plan or {}).get("army", "") or "").strip()
                    # the game keeps the last army after a battle: choose it only the first time (or when it changed)
                    if want and getattr(self, "_army_selected", None) != want:
                        try:
                            if self.select_saved_army(want): self._army_selected = want
                        except Exception: logger.warning("Saved army selection failed, attacking with the current army")
                        Input_Handler.click(0.20, 0.10)      # back to the "My Army" tab (the Attack! button is there)
                        time.sleep(0.4)
                Input_Handler.click(0.883, 0.889)             # green "Attack!" at the bottom right
                logger.info("Attack! pressed, looking for a base")
                time.sleep(0.5)
                continue
            time.sleep(0.15)
        if not started and not army_done:
            try:                                         # what was on the screen: to Claude (picture + words)
                import learn_sync, utils as _u
                fr = Frame_Handler.get_frame(grayscale=False)
                learn_sync.report_stuck(_u.INSTANCE_ID, fr, [b[0] for b in ocr_boxes(fr) if b[5] > 0.3], "open_attack")
            except Exception:
                pass
            logger.error("Failed to open the attack (no Find a Match / Attack! button)")
            return False

        # Wait until "end battle" button is found
        if not self.wait_for_base(timeout):
            logger.error("Failed to search for attack")
            return False
        return self.apply_loot_filter()

    def select_saved_army(self, name):
        """
        On the army screen before attacking: pick the saved army called `name`.
        Reads the screen for the name; if it isn't visible, opens the saved-armies list
        (taught "army_dropdown" button) and looks again. Never blocks the attack.
        """
        import time, teach
        name = (name or "").strip()
        if not name: return True
        time.sleep(0.8)
        def find_and_tap():
            boxes = [b for b in ocr_boxes(Frame_Handler.get_frame(grayscale=False)) if b[5] > 0.3]
            # current game: Army -> "Saved Recipes" tab, every recipe row has a green "Use" button on its right
            tab = next((b for b in boxes if _word_hit(b[0], "saved recipes") or _word_hit(b[0], "recipes")), None)
            if tab and not any(_word_hit(b[0], "use") for b in boxes):
                Input_Handler.click((tab[1] + tab[3]) / 2, (tab[2] + tab[4]) / 2)
                time.sleep(0.8)
                boxes = [b for b in ocr_boxes(Frame_Handler.get_frame(grayscale=False)) if b[5] > 0.3]
            hit = next((b for b in boxes if _word_hit(b[0], name.lower())), None)
            if not hit: return False
            cy = (hit[2] + hit[4]) / 2
            uses = [b for b in boxes if b[0].strip().lower() == "use" and b[1] > hit[3] and -0.02 < (b[2] + b[4]) / 2 - cy < 0.14]
            if uses:
                u = min(uses, key=lambda b: (b[2] + b[4]) / 2 - cy)
                Input_Handler.click((u[1] + u[3]) / 2, (u[2] + u[4]) / 2)
            else:
                Input_Handler.click((hit[1] + hit[3]) / 2, (hit[2] + hit[4]) / 2)
            return True
        if find_and_tap():
            logger.info(f"Saved army '{name}' selected")
            time.sleep(0.8)
            return True
        if tap_taught("army_dropdown", timeout=2):
            time.sleep(1.0)
            if find_and_tap():
                logger.info(f"Saved army '{name}' selected")
                time.sleep(0.8)
                return True
        logger.warning(f"Saved army '{name}' not found, attacking with the current army")
        return False

    def wait_for_base(self, timeout=60):
        """Wait for an opponent's village (End Battle button visible)."""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:                                     # the red End Battle button by its colour: instant
                if red_battle_button():
                    self.base_at = time.monotonic()
                    return True
            except Exception:
                pass
            if find_taught("end_battle"):
                self.base_at = time.monotonic()
                return True
            x, y = Frame_Handler.locate(self.assets["end_battle"], thresh=0.9)
            if x is not None and y is not None:
                self.base_at = time.monotonic()
                return True
            time.sleep(0.1)
        return False

    def record_search(self, loot=None, accepted=True):
        """Statistics: every base looked at during the search (loot read when the numbers are taught)."""
        try:
            import stats, teach, utils as _u
            if loot is None and teach.taught("enemy_gold"):
                frame = Frame_Handler.get_frame(grayscale=False)
                loot = {k: read_taught_number(f"enemy_{k}", frame) for k in ("gold", "elixir", "dark")}
            loot = loot or {}
            stats.record(_u.INSTANCE_ID, "search", accepted=bool(accepted),
                         gold=loot.get("gold"), elixir=loot.get("elixir"), dark=loot.get("dark"))
        except Exception:
            pass

    def apply_loot_filter(self):
        """
        Skip bases with too little loot (needs the Next button and the loot numbers taught).
        Returns True when a good base is on screen.
        """
        import time, teach
        # attack every base it finds: no skipping, no reading of the loot (no time lost)
        if not getattr(self, "skip_bases", False): return True
        # learn the search screen by itself (once), even when the filter is off
        if not (teach.taught("enemy_gold") and teach.taught("next_button")):
            frame = Frame_Handler.get_frame(grayscale=False)
            Auto_Learn.learn_enemy_loot(frame)
            if not teach.taught("next_button"): Auto_Learn.learn_button("next_button", frame)
        f = getattr(self, "loot_filter", None)
        if not f or not f.get("enabled"):
            self.record_search(None, accepted=True)
            return True
        if not teach.taught("next_button") or not (teach.taught("enemy_gold") or teach.taught("enemy_elixir")):
            logger.warning("Loot filter is on but the Next button / loot numbers aren't taught yet")
            return True
        need = {"gold": int(f.get("min_gold", 0)), "elixir": int(f.get("min_elixir", 0)), "dark": int(f.get("min_dark", 0))}
        for skip in range(max(0, int(f.get("max_skips", 30))) + 1):
            if not running(): return False
            # loot numbers count up for a moment: read until two reads agree (max ~1.6 s)
            loot, prev = None, None
            for _ in range(6):
                frame = Frame_Handler.get_frame(grayscale=False)
                loot = {k: read_taught_number(f"enemy_{k}", frame) for k in need}
                if prev == loot and any(v for v in loot.values()): break
                prev = loot
                time.sleep(0.25)
            checks = [(loot[k] or 0) >= v for k, v in need.items() if v > 0 and (k != "dark" or teach.taught("enemy_dark"))]
            ok = (all(checks) if f.get("mode", "all") == "all" else any(checks)) if checks else True
            logger.info(f"Base loot: gold={loot['gold']} elixir={loot['elixir']} dark={loot['dark']} -> {'attack' if ok else 'next'}")
            self.record_search(loot, accepted=ok)
            if ok: return True
            if skip == int(f.get("max_skips", 30)): break
            if not tap_taught("next_button", timeout=2) and not Auto_Learn.learn_button("next_button", tap=True, min_interval=0):
                logger.warning("Next button not found, attacking this base")
                return True
            time.sleep(0.6) # clouds; wait_for_base below waits for the next village
            if not self.wait_for_base(20): return False
        logger.info("No base passed the loot filter, attacking the last one")
        return True
    
    def start_builder_attack(self, timeout=60):
        import time
        
        # Click attack
        Input_Handler.click(0.07, 0.9)
        
        # Find a match
        if not click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["find_now"], thresh=0.9),
            timeout=5
        ): return False
        
        # Wait until "battle starts in" text is found
        start_time = time.time()
        while time.time() - start_time < timeout:
            section = Frame_Handler.get_frame_section(0, 0, 1, 0.1, grayscale=True, high_contrast=True, thresh=150)
            x, y = Frame_Handler.locate(self.assets["battle_starts_in"], section, thresh=0.9)
            if x is not None and y is not None: return True
            time.sleep(0.1)
        return False
    
    def detect_troop_positions(self, frame, clip_left=0.0, clip_right=1.0, type_gaps_seen=0, return_boundaries=False, return_types=False, return_counts=False):
        import cv2, scipy, numpy as np
        
        # Look for vertical card edges
        assert len(frame.shape) == 3 and frame.shape[2] == 3
        frame_color = frame.copy()
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        orig_h, orig_w = frame_gray.shape
        frame_color = frame_color[:, max(0, int(orig_w*clip_left)-10):min(orig_w, int(orig_w*clip_right)+10)]
        frame_gray = frame_gray[:, max(0, int(orig_w*clip_left)-10):min(orig_w, int(orig_w*clip_right)+10)]
        frame_gray = cv2.equalizeHist(frame_gray)
        edges = cv2.convertScaleAbs(np.abs(cv2.Sobel(frame_gray, cv2.CV_64F, 1, 0, ksize=3)))
        profile = np.sum(edges, axis=0)
        profile = (profile - profile.min()) / (profile.max() - profile.min())
        peaks = scipy.signal.find_peaks(profile, height=0.8, distance=10)[0]
        peaks_norm =  peaks / orig_w + clip_left
        
        # Compute distances between edges and discretize
        dists = np.diff(peaks_norm)
        dist_categories = np.array([0.007, 0.015, 0.068]) # normal gap, type change gap, card width
        tol = 0.01
        diffs = np.abs(dists[:, None] - dist_categories)
        closest_idx = np.argmin(diffs, axis=1)
        closest_dist = diffs[np.arange(len(dists)), closest_idx]
        dists_discrete = dist_categories[closest_idx]
        dists_discrete[closest_dist > tol] = np.nan
        
        # Remove partially visible card edges (no whole card at all, e.g. the bar after the army is out: no cards)
        whole = np.where(dists_discrete == dist_categories[2])[0]
        if len(whole) == 0: raise ValueError("No troop cards found")
        remove_left, remove_right = int(whole[0]), int(whole[-1])
        peaks = peaks[remove_left:remove_right+2]
        peaks_norm = peaks_norm[remove_left:remove_right+2]
        dists_discrete = dists_discrete[remove_left:remove_right+1]
        
        if len(peaks) % 2 == 1:
            # an extra edge (a half-visible card at the side, a glow): drop the one edge whose
            # removal leaves edge pairs that all look like whole cards
            card_w = dist_categories[2]
            def pair_err(pn):
                return sum(abs((pn[k + 1] - pn[k]) - card_w) for k in range(0, len(pn) - 1, 2))
            best = min(range(len(peaks)), key=lambda k: pair_err(np.delete(peaks_norm, k)))
            peaks, peaks_norm = np.delete(peaks, best), np.delete(peaks_norm, best)
            dists_discrete = np.delete(dists_discrete, min(best, len(dists_discrete) - 1)) if len(dists_discrete) else dists_discrete
            dd = np.diff(peaks_norm)
            dd_idx = np.argmin(np.abs(dd[:, None] - dist_categories), axis=1) if len(dd) else np.array([], dtype=int)
            dists_discrete = dist_categories[dd_idx] if len(dd) else dd
        if len(peaks) < 2: raise ValueError("No troop cards found")
        
        # Convert edge distances to card locations
        card_types = []
        card_centers = []
        card_boundaries = []
        card_counts = []
        for i in range(0, len(peaks_norm), 2):
            x = (peaks_norm[i] + peaks_norm[i+1]) / 2
            card_centers.append(x)
            card_boundaries.extend([peaks_norm[i], peaks_norm[i+1]])
            prev_gap = dists_discrete[i-1] if i-1 > 0 else dist_categories[0]
            next_gap = dists_discrete[i+1] if i+1 < len(dists_discrete) else dist_categories[0]
            if prev_gap == dist_categories[1]: type_gaps_seen += 1
            
            # Figure out whether card is a normal troop, clan troop, or hero
            card_section = frame_color[:, peaks[i]:peaks[i+1]]
            card_section_gray = frame_gray[:, peaks[i]:peaks[i+1]]
            h, w = card_section_gray.shape[:2]
            card_texture = cv2.Canny(card_section_gray, 50, 150) / 255
            x_asset = render_text("x", "SupercellMagic", 25)
            x_h, x_w = x_asset.shape[:2]
            x_sign_loc = Frame_Handler.locate(x_asset, card_section_gray, grayscale=True, thresh=0.75, ref="lc")
            if x_sign_loc[0] is not None and x_sign_loc[1] is not None: # Only troops, clan troops, or spells have multiplicity
                count_section = card_section_gray[:int(h*x_sign_loc[1]+0.5*x_h)+1, int(w*x_sign_loc[0]+x_w)-1:]
                number_locs = Frame_Handler.batch_locate([render_text(str(n), "SupercellMagic", 25) for n in range(0, 12)], frame=count_section, grayscale=True, thresh=0.8, ref="cc")
                
                count = 1
                for n in reversed(range(0, 12)):
                    loc = number_locs[n]
                    if loc[0] is not None and loc[1] is not None:
                        count = n
                        break
                
                # Clan troops either have a clan badge rather than a smooth background
                # or will have wider card edge gaps compared to typical troops
                if max(card_texture[int(h*x_sign_loc[1])-10:int(h*x_sign_loc[1])+10, :int(w*x_sign_loc[0]-1)].mean(1)) > 0.1:
                    card_type = "clan"
                    card_counts.append(1)
                elif prev_gap == dist_categories[1] and next_gap == dist_categories[1]:
                    card_type = "clan"
                    card_counts.append(1)
                elif type_gaps_seen > 0:
                    card_type = "spell"
                    card_counts.append(count)
                else:
                    card_type = "troop"
                    card_counts.append(-1)
            else:
                card_section_border = card_section.copy()
                card_section_border[int(h*0.1):int(h*0.9), int(w*0.1):int(w*0.9)] = 0
                mask = filter_color((68, 202, 222), card_section_border, tol=100, return_mask=True)[1]
                blue_pct = mask.mean()
                # Seige machine doesn't have multiplicity anymore
                if blue_pct > 0.1:
                    card_type = "clan"
                    card_counts.append(1)
                else:
                    card_type = "hero"
                    card_counts.append(1)
            card_types.append(card_type)

        card_centers = np.array(card_centers)
        
        if not return_boundaries and not return_types: return card_centers
        
        output = [card_centers]
        if return_boundaries: output.append(card_boundaries)
        if return_types: output.append(card_types)
        if return_counts: output.append(card_counts)
        output.append(type_gaps_seen)
        return output
    
    DEPLOY_POINT = (0.5, 0.8) # proven deploy spot (bottom tip of the map after zooming out + scrolling up)

    def choose_strategy(self, history=None):
        """Only the proven single-point deployment is used (estimated multi-point paths landed inside the base)."""
        self.last_strategy = "funnel"
        return self.last_strategy

    def card_gray(self, card_center):
        """A used-up card turns gray."""
        import numpy as np
        section = Frame_Handler.get_frame_section(card_center-0.01, 0.89, card_center+0.01, 0.91, grayscale=False).astype(int)
        # (nearly) no colour: the live picture is compressed, so the grey isn't exactly R = G = B any more
        spread = section.max(axis=2) - section.min(axis=2)
        return float((spread <= 14).mean()) >= 0.9

    # Candidate deploy spots per side (screen fractions after zooming out). The other bot's log on
    # this game confirmed spots at the far left / far right of the screen at mid height; each one is
    # still verified in battle before use (one troop is dropped and the card must change).
    SIDE_CANDIDATES = {
        "left":  [(0.04, 0.55), (0.06, 0.48), (0.08, 0.62), (0.12, 0.40)],
        "right": [(0.96, 0.55), (0.94, 0.48), (0.92, 0.62), (0.88, 0.40)],
    }
    SPELL_CENTER = (0.5, 0.45)

    def card_crop(self, cx):
        """The card's count area (changes when a troop is dropped)."""
        import numpy as np
        return Frame_Handler.get_frame_section(cx - 0.03, 0.83, cx + 0.03, 0.88, grayscale=True).astype(np.int16)

    def card_changed(self, cx, before, noise):
        import numpy as np
        after = self.card_crop(cx)
        if after.shape != before.shape: return True
        return float(np.abs(after - before).mean()) > max(6.0, noise * 3)

    def calibrate_sides(self, cx):
        """
        Find a valid deploy spot on each side using the troop card at cx: drop one troop,
        keep the spot if the card's number changed. Falls back to the proven bottom spot.
        """
        import time, numpy as np
        a = self.card_crop(cx); time.sleep(0.15); b = self.card_crop(cx)
        noise = float(np.abs(a - b).mean()) if a.shape == b.shape else 2.0
        self.side_points = {}
        Input_Handler.click(cx, 0.9)
        for side, cands in self.SIDE_CANDIDATES.items():
            for pt in cands:
                if self.card_gray(cx): break
                before = self.card_crop(cx)
                Input_Handler.click(*pt)
                time.sleep(0.45)
                if self.card_changed(cx, before, noise):
                    self.side_points[side] = pt
                    logger.info(f"Deploy spot verified on the {side}: {pt}")
                    break
            if side not in self.side_points:
                self.side_points[side] = self.DEPLOY_POINT
                logger.warning(f"No valid deploy spot found on the {side}, using the bottom spot")

    def points_for(self, where):
        if where == "smart":                     # the weakest side the vision model chose (spots on its grass)
            sp = getattr(self, "smart_points", None)
            if sp: return list(sp)
            where = "sides"
        pts = getattr(self, "side_points", None) or {}
        if where == "sides": return [pts.get("left", self.DEPLOY_POINT), pts.get("right", self.DEPLOY_POINT)]
        if where in ("left", "right"): return [pts.get(where, self.DEPLOY_POINT)]
        return [self.DEPLOY_POINT]

    def deploy_troops(self, card_centers, available_slots=None, card_types=None, card_counts=None):
        """
        Deploy the visible cards. Without a plan: the original proven single point.
        With a plan (loadout): troops / heroes / clan castle on the chosen sides,
        spells in the middle after a delay, some spells held back for a second wave.
        """
        import time, random, numpy as np
        
        if available_slots is None: available_slots = [1] * len(card_centers)
        if card_types is None: card_types = [None] * len(card_centers)
        if card_counts is None: card_counts = [0] * len(card_centers)
        plan = getattr(self, "plan", None) or {}
        px, py = self.DEPLOY_POINT
        # card positions are only valid for the page of cards currently on screen
        self.deployed_troops = []
        self.deployed_heroes = []

        if not plan:
            # ---- original, proven deployment: everything on one point, in card order
            Input_Handler.down(px, py, pointer=1)
            for i in range(len(card_centers)):
                if not available_slots[i]: continue
                Input_Handler.click(card_centers[i], 0.9)
                if card_types[i] in ["hero", "clan"]:
                    Input_Handler.click(px, py)
                    if card_types[i] == "hero": self.deployed_heroes.append(card_centers[i])
                elif card_types[i] == "troop":
                    Input_Handler.down(px, py, pointer=0)
                    end_time = time.monotonic() + TROOP_DEPLOY_TIME
                    while time.monotonic() < end_time and not self.card_gray(card_centers[i]): time.sleep(0.05)
                    Input_Handler.up(pointer=0)
                    self.deployed_troops.append(card_centers[i])
                elif card_types[i] == "spell":
                    for coord in zip(np.random.uniform(0.35, 0.65, card_counts[i]), np.random.uniform(0.45, 0.55, card_counts[i])):
                        Input_Handler.click(*coord)
                else:
                    Input_Handler.click(px, py, n=max(0, card_counts[i]))
            Input_Handler.up(pointer=1)
            Input_Handler.click(0.01, 0.9)
            return

        # ---- plan (loadout) deployment
        if plan.get("mode") == "smart":          # smart attack: everything on the side the model chose
            plan = dict(plan, troops_where="smart", heroes_where="smart", clan_where="smart")
            if not getattr(self, "smart_points", None):
                plan.update(troops_where="sides", heroes_where="sides", clan_where="sides")
        uses_sides = any(plan.get(k) in ("sides", "left", "right") for k in ("troops_where", "heroes_where", "clan_where"))
        order = {"troop": 0, "clan": 1, None: 1, "hero": 2, "spell": 3}
        idx = sorted([i for i in range(len(card_centers)) if available_slots[i]], key=lambda i: order.get(card_types[i], 1))
        wave = [x.strip().lower() for x in str(plan.get("second_wave_spells", "")).replace("،", ",").split(",") if x.strip()]
        hold_back = set(int(x) for x in wave if x.isdigit())
        hold_names = set(x for x in wave if not x.isdigit())
        hero_n = 0
        for i in idx:
            t = card_types[i]
            cx = card_centers[i]
            if t == "troop" and uses_sides and not getattr(self, "side_points", None):
                self.calibrate_sides(cx)
            if t == "troop":
                smart = plan.get("troops_where") == "smart"
                pts = self.points_for(plan.get("troops_where", "sides"))
                if smart and len(pts) >= 3:      # the two ends first (they make the funnel), then the middle
                    pts = [pts[0], pts[-1]] + pts[1:-1]
                Input_Handler.click(cx, 0.9)
                share = TROOP_DEPLOY_TIME / len(pts)
                for k, pt in enumerate(pts):
                    before = self.card_crop(cx) if smart else None
                    Input_Handler.down(*pt, pointer=0)
                    end_time = time.monotonic() + share
                    while time.monotonic() < end_time and not self.card_gray(cx): time.sleep(0.05)
                    if k == len(pts) - 1: # last spot: finish the card
                        end2 = time.monotonic() + TROOP_DEPLOY_TIME
                        while time.monotonic() < end2 and not self.card_gray(cx): time.sleep(0.05)
                    Input_Handler.up(pointer=0)
                    if smart and before is not None and not self.card_gray(cx) and not self.card_changed(cx, before, 2.0):
                        self.smart_bad(pt)       # that spot doesn't take troops (inside the red line): not again
                    if self.card_gray(cx): break
                self.deployed_troops.append(cx)
                self.troops_done_at = time.monotonic()
            elif t in ("clan", None):
                pts = self.points_for(plan.get("clan_where", "sides"))
                if plan.get("clan_where") == "smart": pts = [pts[len(pts) // 2]]
                Input_Handler.click(cx, 0.9)
                Input_Handler.click(*pts[0], n=max(1, card_counts[i]) if t is None else 1)
            elif t == "hero":
                pts = self.points_for(plan.get("heroes_where", "sides"))
                Input_Handler.click(cx, 0.9)
                if plan.get("heroes_where") == "smart":   # heroes behind the troops: the middle spots
                    mid = len(pts) // 2
                    pts = [pts[mid]] + [p for p in pts[max(0, mid - 1):mid + 2] if p != pts[mid]]
                Input_Handler.click(*pts[hero_n % len(pts)]) # heroes alternate between the sides
                hero_n += 1
                self.deployed_heroes.append(cx)
                self.heroes_done_at = time.monotonic()
            elif t == "spell":
                self.spell_no = getattr(self, "spell_no", 0) + 1
                if self.spell_no in hold_back or (hold_names and (self.card_name(cx) or "") in hold_names):
                    self.held_spells.append((cx, card_counts[i]))
                    continue
                if plan.get("spells_where", "center") == "none": continue
                delay = float(plan.get("spells_delay", 3))
                waited = time.monotonic() - getattr(self, "troops_done_at", time.monotonic())
                sm = getattr(self, "smart_plan", None)
                if plan.get("mode") == "smart" and sm and sm.get("spell"):
                    self.wait_for_fight(sm["spell"], max_wait=max(4.0, delay + 12 - waited))
                elif delay > waited: time.sleep(delay - waited)
                Input_Handler.click(cx, 0.9)
                self.cast_spell(card_counts[i])
        Input_Handler.click(0.01, 0.9)

    def name_cards(self, bar_frame, boundaries, types):
        """bar_frame: bottom strip (y 0.82..1.0). Remembers card center -> unit name and logs the bar once."""
        import unit_icons
        if not hasattr(self, "card_names"): self.card_names = {}
        w = bar_frame.shape[1]
        names = []
        for k, t in enumerate(types):
            x1, x2 = boundaries[2 * k], boundaries[2 * k + 1]
            cx = round((x1 + x2) / 2, 3)
            if cx in self.card_names: names.append(self.card_names[cx] or "?"); continue
            if t == "hero": self.card_names[cx] = None; names.append("hero"); continue
            crop = bar_frame[:, max(0, int(x1 * w)):int(x2 * w)]
            groups = ("spells",) if t == "spell" else ("troops", "sieges")
            name, _ = unit_icons.identify(crop, groups=groups, min_score=0.7)
            self.card_names[cx] = name
            names.append(name or "?")
        if names: logger.info("Troop bar: " + ", ".join(names))

    def card_name(self, cx):
        names = getattr(self, "card_names", {}) or {}
        if not names: return None
        k = min(names, key=lambda c: abs(c - cx))
        return names[k] if abs(k - cx) < 0.02 else None

    def wait_for_fight(self, target, max_wait=15.0, box=0.07):
        """
        Live battle watching: wait until the army reaches the spell's target (the picture around it starts to move a
        lot: troops arriving, defenses shooting), then return -> seconds waited. Only the first spell waits; once
        the fight is seen the next ones go straight away. max_wait: cast anyway.
        """
        import time, numpy as np
        if getattr(self, "fight_seen", False): return 0.0
        x, y = target
        t0 = time.monotonic()
        prev, base, hot = None, [], 0
        while time.monotonic() - t0 < max_wait:
            cur = Frame_Handler.get_frame_section(max(0, x - box), max(0.07, y - box), min(1, x + box), min(0.8, y + box),
                                                  grayscale=True).astype(np.int16)
            if prev is not None and cur.shape == prev.shape:
                d = float(np.abs(cur - prev).mean())
                if len(base) < 4: base.append(d)
                else:
                    calm = float(np.median(base))
                    hot = hot + 1 if d > max(6.0, calm * 2.2) else 0
                    if hot >= 2:
                        self.fight_seen = True
                        logger.info(f"Spells: the army reached the target after {time.monotonic() - t0:.1f}s — casting now")
                        return time.monotonic() - t0
            prev = cur
            time.sleep(0.2)
        self.fight_seen = True
        return time.monotonic() - t0

    def smart_bad(self, pt):
        """A smart spot the game refused (the red line is further out there): push it outward, drop it if it can't."""
        sp = getattr(self, "smart_points", None) or []
        if pt not in sp: return
        i = sp.index(pt)
        side = (getattr(self, "smart_plan", None) or {}).get("side", "")
        dx = -0.035 if "left" in side else 0.035
        dy = 0.035 if "bottom" in side else -0.035
        nx, ny = pt[0] + dx, pt[1] + dy
        base = getattr(self, "base_seen", None)
        if 0.02 < nx < 0.98 and 0.10 < ny < 0.79 and (base is None or base.on_grass(nx, ny)): sp[i] = (nx, ny)
        else: sp.pop(i)
        logger.debug(f"Smart spot {pt} refused -> {sp[i] if i < len(sp) and sp[i] != pt else 'dropped'}")

    def cast_spell(self, n):
        import random
        x0, y0 = self.SPELL_CENTER
        sm = getattr(self, "smart_plan", None)
        if sm and (getattr(self, "plan", None) or {}).get("mode") == "smart" and sm.get("spell"):
            x0, y0 = sm["spell"]                 # the defenses packed together behind the side we attack
        for _ in range(max(1, n)):
            Input_Handler.click(x0 + random.uniform(-0.04, 0.04), y0 + random.uniform(-0.04, 0.04))

    def second_wave(self):
        """Held-back spells (e.g. heal / rage) once the army has taken damage."""
        import time
        plan = getattr(self, "plan", None) or {}
        if not self.held_spells: return
        after = float(plan.get("second_wave_after", 20))
        start = getattr(self, "troops_done_at", None) or time.monotonic()
        if after > time.monotonic() - start:
            self.later(start + after, self.second_wave)
            return
        for cx, n in self.held_spells:
            Input_Handler.click(cx, 0.9)
            self.cast_spell(n)
        Input_Handler.click(0.01, 0.9)
        logger.info(f"Second spell wave: {len(self.held_spells)} spell card(s)")

    def redeploy_leftovers(self):
        """
        Troop cards that are still coloured weren't (fully) deployed: try them again on the same point.
        Returns how many troop cards were used up in the end.
        """
        import time
        plan = getattr(self, "plan", None) or {}
        pts = self.points_for("smart" if plan.get("mode") == "smart" else plan.get("troops_where", "bottom"))
        px, py = pts[len(pts) // 2] if plan.get("mode") == "smart" else pts[-1]
        used = 0
        for x in self.deployed_troops:
            if self.card_gray(x):
                used += 1
                continue
            Input_Handler.click(x, 0.9)
            Input_Handler.down(px, py, pointer=0)
            end_time = time.monotonic() + TROOP_DEPLOY_TIME
            while time.monotonic() < end_time and not self.card_gray(x): time.sleep(0.05)
            Input_Handler.up(pointer=0)
            if self.card_gray(x): used += 1
        if self.deployed_troops: Input_Handler.click(0.01, 0.9)
        return used

    def deploy_leftovers(self, data):
        """
        After a recording: every card still in colour on the army bar (heroes, troops that weren't in the army when
        the recording was made) is dropped — and checked: the card must change (a hero's card gets its ability / health
        bar, a troop's number goes down). If a spot doesn't take it (inside the red line on this base), the next spot
        is tried: the recording's own spots first, then the sides. Spells left over are not thrown blindly.
        """
        import time, numpy as np, army_learn
        mx, my = (data.get("max") or [1, 1])[:2]
        spots = []
        for e in data.get("events", []):
            if e.get("type") != "down": continue
            x, y = army_learn.touch_to_screen(e["fx"], e["fy"], mx, my)
            if y < 0.80 and all(abs(x - a) + abs(y - b) > 0.05 for a, b in spots): spots.append((x, y))
        spots = spots[:6] + [p for side in self.SIDE_CANDIDATES.values() for p in side[:2]]
        base = getattr(self, "base_seen", None)
        if base is not None and base.hull is not None:
            spots = base.outside_spots(spots)              # spots outside the base first (the model saw its outline)
        time.sleep(0.2)
        frame = Frame_Handler.get_frame_section(0.0, 0.82, 1.0, 1.0, grayscale=False)
        try:
            centers, _b, types, _c, _g = self.detect_troop_positions(frame, return_boundaries=True, return_types=True, return_counts=True)
        except ValueError:                           # no card left on the bar: the whole army is out
            self.army_out = True
            return 0
        done, missed = [], []
        for x, t in zip(centers, types):
            if t == "spell" or self.card_gray(x): continue
            a, b = self.card_crop(x), self.card_crop(x)
            noise = float(np.abs(a - b).mean())
            Input_Handler.click(x, 0.9)
            time.sleep(0.15)
            out = False
            for sp in spots:
                for _ in range(1 if t in ("hero", "clan") else 4):
                    Input_Handler.click(*sp)
                    time.sleep(0.06)
                time.sleep(0.3)
                if self.card_gray(x) or self.card_changed(x, a, noise):
                    out = True
                    if t not in ("hero", "clan"):            # the rest of this troop on the spot that works
                        for _ in range(14):
                            if self.card_gray(x): break
                            Input_Handler.click(*sp)
                            time.sleep(0.06)
                    break
            if out:
                done.append(t)
                if t == "hero": self.deployed_heroes.append(x)
            else:
                missed.append(t)
        heroes = done.count("hero")
        if done: logger.info(f"Recording: also deployed {len(done)} card(s) that were still left ({heroes} hero(es))")
        if missed: logger.info(f"Could not drop {len(missed)} card(s) on any spot ({', '.join(missed)})")
        if self.deployed_heroes:
            self.heroes_done_at = time.monotonic()
            self.activate_hero_abilities()
        self.army_out = not missed
        return len(done)

    def _watch_touches(self):
        """Start reading the screen's touch events (to tell your taps from the bot's own)."""
        try:
            import recorder, utils as _u
            found = _u.TEMP_CACHE.get("touch_dev")
            if not found:
                found = recorder.find_touch_device(lambda c: ADB_Manager.adbutils_device.shell(c))
                _u.TEMP_CACHE["touch_dev"] = found
            if not found: return None
            rec = recorder.Recorder(ADB_Manager._adb_exe or "adb", _u.ADB_ADDRESS, *found)
            rec.start()
            return rec
        except Exception:
            return None

    def _merge_touches(self, watch, data, start, replay_end=None):
        """Your taps made while the recording was playing (not the bot's) -> saved into the same recording."""
        import time
        if watch is None: return
        try:
            import recorder, army_learn
            time.sleep(0.3)
            watch.stop()
            until = getattr(self, "ended_at", None) or time.monotonic()
            # only taps after the replay finished (during it the bot taps all the time) and away from the bot's own
            if replay_end is None: return
            strokes = recorder.user_strokes(watch.events, since=replay_end + 0.5, until=until, tol=0.6)
            mx, my = (data.get("max") or [1, 1])[:2]
            keep = []
            for st in strokes:            # a tap on Surrender / End Battle ends the battle: not part of the attack
                x, y = army_learn.touch_to_screen(st[0]["fx"], st[0]["fy"], mx, my)
                if x < 0.16 and 0.69 < y < 0.81: break
                keep.append(st)
            n = recorder.merge_user_part(data.get("name") or self.plan.get("recording"), keep, start)
            if n: logger.info(f"Recording '{data.get('name')}': you added {n} new tap(s) — saved into the recording")
        except Exception:
            logger.warning("Could not add your taps to the recording", exc_info=True)

    battle_speed = True
    SPEED_AREA = (0.90, 0.42, 1.0, 0.72)          # the green battle-speed button (1x / 2x / 4x), right side

    def speed_up(self, frame=None):
        """
        The battle speed button (shown in the last minute): tap it until it says 4x, so the end of the battle
        plays 4 times faster. At most 3 taps per battle; read every time (never taps blindly).
        """
        import re, numpy as np, cv2
        if getattr(self, "_speed_done", False) or getattr(self, "_speed_taps", 0) >= 3: return
        frame = frame if frame is not None else Frame_Handler.get_frame(grayscale=False)
        x1, y1, x2, y2 = self.SPEED_AREA
        area = Frame_Handler.crop(frame, x1, y1, x2, y2)
        r, g, b = (area[..., i].astype(int) for i in range(3))
        m = ((g > 165) & (g - r > 25) & (g - b > 70) & (r > 70)).astype(np.uint8)
        n, _lab, st, _c = cv2.connectedComponentsWithStats(m, 8)
        boxes = [st[i] for i in range(1, n) if st[i][4] > area.shape[0] * area.shape[1] * 0.02]
        if not boxes: return
        bx, by, bw, bh, _a = max(boxes, key=lambda s: s[4])
        if not (0.6 < bw / max(1, bh) < 1.7): return                      # a square button, not a bar
        h, w = area.shape[:2]
        cx, cy = x1 + (bx + bw / 2) / w * (x2 - x1), y1 + (by + bh / 2) / h * (y2 - y1)
        btn = Frame_Handler.crop(frame, cx - 0.04, cy - 0.06, cx + 0.04, cy + 0.06)
        speed = None
        try:                                    # the game's own font first: "4x" -> 4 (the x is read as an extra digit)
            import game_digits
            v, c = game_digits.read(btn, want_conf=True)
            if v is not None and c >= 0.3 and str(v)[0] in "124": speed = int(str(v)[0])
        except Exception:
            pass
        if speed is None:
            text = " ".join(t[0] for t in ocr_boxes(btn)).lower().replace(" ", "").replace("q", "4").replace("a", "4")
            mm = re.search(r"([1248])[x×%]", text) or re.search(r"([1248])", text)
            if not mm: return
            speed = int(mm.group(1))
        if speed >= 4:
            if getattr(self, "_speed_taps", 0): logger.info("Battle speed 4x")
            self._speed_done = True
            return
        Input_Handler.click(cx, cy)
        self._speed_taps = getattr(self, "_speed_taps", 0) + 1

    def later(self, at, fn):
        """Run fn at time `at` (monotonic) from the battle-end loop, so nothing waits for it."""
        self._later = getattr(self, "_later", None) or []
        self._later.append((at, fn))

    def run_due(self):
        import time
        todo, keep = [], []
        for at, fn in getattr(self, "_later", None) or []:
            (todo if time.monotonic() >= at else keep).append((at, fn))
        self._later = keep
        for _at, fn in todo:
            try: fn()
            except Exception: logger.warning("A timed battle step failed", exc_info=True)

    def activate_hero_abilities(self, wait=False):
        """Tap the deployed hero cards again after a delay to fire their abilities (scheduled, not waited for)."""
        import time
        plan = getattr(self, "plan", None) or {}
        delay = float(plan.get("abilities_after", getattr(self, "hero_retap", 0))) if plan else getattr(self, "hero_retap", 0)
        if delay <= 0 or not self.deployed_heroes: return
        since = time.monotonic() - (getattr(self, "heroes_done_at", None) or time.monotonic())
        if delay > since and not wait:
            self.later(time.monotonic() + delay - since, lambda: self.activate_hero_abilities(wait=True))
            return
        if delay > since: time.sleep(delay - since)
        for x in self.deployed_heroes:
            Input_Handler.click(x, 0.9)
            time.sleep(0.15)
        logger.debug(f"Activated {len(self.deployed_heroes)} hero abilities")
    
    def prepare_field(self):
        """
        Before dropping anything: wait until the base has fully appeared (the clouds are gone: two pictures in a row
        look the same), then zoom out (twice: the second one is harmless when it is already out) and move the view.
        Zooming while the clouds are still there is ignored by the game.
        """
        import time, numpy as np
        T = self.timing = {"start": time.monotonic()}
        prev, end = None, time.monotonic() + 1.5
        while time.monotonic() < end:
            cur = Frame_Handler.get_frame_section(0.0, 0.1, 1.0, 0.8, grayscale=True)[::8, ::8].astype(int)
            if prev is not None and cur.shape == prev.shape and float(np.abs(cur - prev).mean()) < 4: break
            prev = cur
            time.sleep(0.05)
        T["clouds"] = time.monotonic()
        for _ in range(2):
            Input_Handler.zoom(dir="out")
            time.sleep(0.08)
        Input_Handler.swipe_up(y1=0.5, duration=80, inter_points=3, fast=True)
        time.sleep(0.12)
        T["zoom"] = time.monotonic()
        # one look with the YOLO model: what the base has, where its outline is (deploy spots outside it)
        self.base_seen = None
        field = None
        try:
            import vision
            field = Frame_Handler.get_frame(grayscale=False)
            self.base_seen = vision.look(field, logger=logger)
        except Exception:
            logger.debug("vision look failed", exc_info=True)
        self._field_frame = field
        T["eyes"] = time.monotonic()
        self.smart_plan, self.smart_points = None, None
        plan = getattr(self, "plan", None) or {}
        smart = plan.get("mode") == "smart"
        # the exact red line, shown by the game itself (smart attacks and recordings: they decide where to drop)
        import deploy_zone
        self.zone = deploy_zone.Zone()
        uses_rec = bool(plan.get("recording")) and plan.get("mode", "recording") == "recording"
        # recordings: off unless switched on (your own drop spots are valid; it costs a few pictures = time)
        if plan and (smart or uses_rec) and plan.get("red_line", smart):
            probe = None
            b = self.base_seen
            if b is not None and b.hull is not None:
                probe = b.th.center if b.th is not None else tuple(float(v) for v in b.hull.reshape(-1, 2).mean(axis=0))
            self.zone = deploy_zone.reveal(self, probe=probe, logger=logger)
        T["red_line"] = time.monotonic()
        try:                                     # a model that didn't load is a bug (logged), not an unknown base
            import vision as _v
            loaded = _v._NET.get("net") is not None
        except Exception:
            loaded = False
        if not smart and loaded and self.base_seen is not None and len(self.base_seen.objs) < 6:
            self._learn_unknown_base()           # the model hardly saw anything here: Claude labels it for training
        if smart:
            try:
                sp = self.base_seen.attack_plan() if self.base_seen is not None else None
            except Exception:
                sp = None
                logger.debug("smart plan failed", exc_info=True)
            if sp and self.zone:                 # right at the red line (+ a small gap), on the map's grass
                pts = []
                for x, y in sp["points"]:
                    q = self.zone.snap(x, y)
                    pts.append(q if self.base_seen.on_grass(*q) else (x, y))
                sp = dict(sp, points=pts)
            if sp:
                self.smart_plan, self.smart_points = sp, list(sp["points"])
                logger.info(f"Smart attack: {sp['side']} side (danger {sp['danger']}), {len(sp['points'])} deploy spots")
            else:
                logger.info("Smart attack: the base wasn't recognised, attacking from the sides")
                if loaded: self._learn_unknown_base()

    def _learn_unknown_base(self):
        """The model saw too little of this base: the picture goes to Claude (for the next training)."""
        try:
            import learn_sync, utils
            import threading                       # in the background: the battle doesn't wait for it
            fr = getattr(self, "_field_frame", None)
            if fr is None: fr = Frame_Handler.get_frame(grayscale=False)
            threading.Thread(target=learn_sync.report_unknown, args=(utils.INSTANCE_ID, fr, "battle_base"),
                             kwargs={"why": "vision"}, daemon=True).start()
        except Exception:
            logger.debug("could not send the base", exc_info=True)

    def complete_normal_attack(self, restart=True, exclude_clan_troops=False):
        import time, numpy as np

        self.prepare_field()
        self.deployed_heroes = []
        self.deployed_troops = []
        self.side_points = None
        self.held_spells = []
        self.spell_no = 0
        self.card_names = {}
        self.troops_done_at = self.heroes_done_at = None
        self.fight_seen = False
        self._later = []
        if getattr(self, "plan", None): logger.debug(f"Attack plan: {self.plan.get('name', '')}")
        if getattr(self, "plan", None) and self.plan.get("recording") and self.plan.get("mode", "recording") == "recording":
            import recorder
            data = recorder.load(self.plan["recording"])
            if data and data.get("events"):
                logger.info(f"Replaying recording '{data.get('name')}'")
                play, shift = data, 0.0
                try:                                     # the quiet time before your first tap is not replayed
                    evs = data.get("events", [])
                    t0 = next((e["t"] for e in evs if e.get("type") == "down"), 0.0)
                    if t0 > 0.15:
                        shift = t0 - 0.05
                        play = dict(data, events=[dict(e, t=max(0.0, e["t"] - shift)) for e in evs])
                except Exception:
                    play = data
                trimmed = play
                if self.plan.get("adapt", True):        # your attack re-shaped for this base (the model saw it)
                    try:
                        play, moved = recorder.adapt(play, getattr(self, "base_seen", None))
                        if getattr(self, "zone", None):    # whatever still falls inside the red line: just outside it
                            play, fixed = recorder.apply_zone(play, self.zone)
                            if fixed: logger.info(f"Red line: {fixed} drop(s) of the recording moved out of it")
                        if moved: logger.info(f"Recording adapted to this base: {moved} drop(s) moved"
                                              + ("" if data.get("base") else " (old recording: only out of the base)"))
                    except Exception:
                        play = trimmed
                        logger.debug("adapting the recording failed", exc_info=True)
                watch = self._watch_touches()            # your own taps during the battle are added to the recording
                time.sleep(0.1)
                replay_start = time.monotonic()
                if getattr(self, "base_at", None):
                    logger.info(f"Battle: first tap of the recording {replay_start + 0.05 - self.base_at:.1f}s after the base appeared")
                    T = getattr(self, "timing", {}) or {}
                    try:
                        p = Frame_Handler._power
                        cap = f"{max(p['src'], key=p['src'].get)} {p['ms'] / max(1, p['n']):.0f} ms" if p.get("n") else "?"
                    except Exception:
                        cap = "?"
                    st = [("clouds", "clouds"), ("zoom", "zoom"), ("eyes", "eyes"), ("red_line", "red line")]
                    parts, last = [], T.get("start", self.base_at)
                    for k, name in st:
                        if k in T:
                            parts.append(f"{name} {T[k] - last:.1f}s")
                            last = T[k]
                    parts.append(f"recording ready {replay_start - last:.1f}s")
                    logger.info(f"Battle timing: waiting for the base {T.get('start', self.base_at) - self.base_at:.1f}s, "
                                + ", ".join(parts) + f" (pictures: {cap})")
                self.ended_at = None
                replay_end = None
                try:
                    taps = recorder.replay(play, ADB_Manager.minitouch_device.connection, lambda: not running())
                    replay_end = time.monotonic()
                    logger.debug(f"Recording replayed: {taps} taps")
                except Exception:
                    logger.exception("Recording replay failed")
                try: self.deploy_leftovers(play)     # new heroes / troops the recording didn't know about
                except Exception: logger.exception("Deploying the remaining cards failed")
                self.finish_battle(restart)
                self._merge_touches(watch, data, replay_start - shift, replay_end)   # your taps: on the recording's own clock
                return
            logger.warning(f"Recording '{self.plan['recording']}' not found, using the loadout")
        
        type_gaps_seen = 0
        total_slots_seen = 0
        last_card_left = 0.0
        
        while total_slots_seen < ATTACK_SLOT_RANGE[1] - ATTACK_SLOT_RANGE[0] + 1:
            frame = Frame_Handler.get_frame_section(0.0, 0.82, 1.0, 1.0, grayscale=False)
            # Find troops to deploy
            card_centers, card_boundaries, card_types, card_counts, type_gaps_seen = self.detect_troop_positions(frame, clip_left=last_card_left, type_gaps_seen=type_gaps_seen, return_boundaries=True, return_types=True, return_counts=True)

            if len(card_centers) == 0: break

            # Exclude clan troops if specified
            available_slots = np.ones_like(card_centers)
            if exclude_clan_troops:
                for i, card_type in enumerate(card_types):
                    if card_type == "clan": available_slots[i] = 0
            
            # Exclude troops outside of specified slot range
            available_slots[:max(0, ATTACK_SLOT_RANGE[0] - total_slots_seen)] = 0
            available_slots[max(0, ATTACK_SLOT_RANGE[1] + 1 - total_slots_seen):] = 0
            
            # Put a name on each card from the uploaded unit pictures (troops / spells / sieges)
            try: self.name_cards(frame, card_boundaries, card_types)
            except Exception: logger.debug("Card naming failed", exc_info=True)

            # Deploy troops up until the last one visible
            total_slots_seen += len(card_centers) - 1
            self.deploy_troops(card_centers[:-1], available_slots[:-1], card_types[:-1], card_counts[:-1])
            # Scroll over and look for the new position of the last card
            last_card_frame = frame[:, int(card_boundaries[-2] * frame.shape[1]):int(card_boundaries[-1] * frame.shape[1])]
            Input_Handler.swipe_left(x1=card_centers[-1], x2=0.038, y=0.9, hold_end_time=500)
            time.sleep(0.5)
            frame = Frame_Handler.get_frame_section(0.0, 0.82, 1.0, 1.0, grayscale=False)
            last_card_left = Frame_Handler.locate(last_card_frame, frame, thresh=0.9, grayscale=False, ref="lc")[0]
            # If the card didn't move then there are no more troops so it can be deployed
            if last_card_left is not None and abs(last_card_left - card_boundaries[-2]) < 0.01:
                self.deploy_troops(card_centers[-1:], available_slots[-1:], card_types[-1:], card_counts[-1:])
                break
            elif last_card_left is None:
                break
        
        # make sure the army really went in
        try:
            used = self.redeploy_leftovers()
            if self.deployed_troops and used == 0 and not self.deployed_heroes:
                # nothing could be deployed: don't sit through a 3-minute empty battle
                logger.warning("No troops could be deployed, ending the battle")
                if self._click_end_battle(timeout=2):
                    time.sleep(0.7)
                    self._click_okay(timeout=3)
        except Exception:
            logger.warning("Could not verify the deployment")
        if self.battle_end != "leave": # fast in / fast out skips the timed extras
            try: self.activate_hero_abilities()      # scheduled: fired from the battle-end loop
            except Exception: logger.warning("Hero ability activation failed")
            try: self.second_wave()
            except Exception: logger.warning("Second spell wave failed")
        self.finish_battle(restart)
    
    def complete_builder_attack(self, restart=True):
        import numpy as np
        
        self.prepare_field()
        
        card_centers = np.linspace(0.1, 0.9, 11)
        self.deployed_heroes = []
        self.deployed_troops = []
        plan, self.plan = self.plan, None # builder base keeps the proven single point
        try: self.deploy_troops(card_centers, card_counts=[4]*len(card_centers))
        finally: self.plan = plan
        
        self.finish_battle(restart, max_wait=260) # builder battles can have two stages
    
    # ============================================================
    # ⚔️ Attack Management
    # ============================================================

    def clear_leftover_screens(self):
        """Results / reward screens (green button, chest, item) left from the last battle -> go through them."""
        try:
            import screen_model, utils as _u
            frame = Frame_Handler.get_frame(grayscale=False)
            label, _d = screen_model.classify(frame, _u.INSTANCE_ID)
            if bottom_green_button(frame) or (label or "").startswith(("reward_", "battle_result")):
                logger.info("Finishing the last battle's reward screens first")
                collect_rewards()
                return True
        except Exception:
            logger.debug("clear_leftover_screens failed", exc_info=True)
        return False

    @require_exit()
    def run_home_base(self, timeout=10, restart=True):
        import time
        
        try:
            # the last battle's results / reward screens still open: finish them first
            self.clear_leftover_screens()
            # Make sure in home base
            start_time = time.time()
            found = False
            while time.time() - start_time < timeout:
                if in_home_base(): found = True; break
                time.sleep(0.2)
            if not found:
                # a popup / another screen is in the way: clear it and try to get home once more
                Auto_Learn.handle_unknown_screen("home_attack")
                try: to_home_base()
                except Exception: pass
                found = in_home_base()
            if not found:
                logger.error("Not in home base. Aborting home attack.")
                return
            
            # Complete an attack
            if self.start_normal_attack(timeout):
                self.open_fails = 0
                self.complete_normal_attack(restart=restart, exclude_clan_troops=EXCLUDE_CLAN_TROOPS)
            else:
                # couldn't open the attack: clear what is on the screen; twice in a row -> reopen the game
                self.open_fails = getattr(self, "open_fails", 0) + 1
                self.clear_leftover_screens()
                if self.open_fails >= 2:
                    self.open_fails = 0
                    start_coc(force_restart="the attack could not be opened twice")
                else:
                    Auto_Learn.handle_unknown_screen("home_attack")
        
        except Exception:
            logger.exception("Error in run_home_base():")

    @require_exit()
    def run_builder_base(self, timeout=10, restart=True):
        import time
        
        try:
            # Make sure in builder base
            start_time = time.time()
            found = False
            while time.time() - start_time < timeout:
                if in_builder_base(): found = True; break
                time.sleep(0.3)
            if not found:
                logger.error("Not in builder base. Aborting builder attack.")
                Auto_Learn.handle_unknown_screen("builder_attack")
                return
            
            # Complete an attack
            if self.start_builder_attack(timeout):
                self.complete_builder_attack(restart=restart)
            else:
                start_coc() # reset in case stuck on find a match screen
        
        except Exception:
            logger.exception("Error in run_builder_base():")
