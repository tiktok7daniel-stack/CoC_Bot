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

    def in_battle(self):
        """End Battle / Surrender button visible = the battle is still running."""
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

        if self.battle_end == "restart":
            if restart: start_coc(force_restart="battle end mode = restart")
            else: stop_coc(reason="battle end mode = restart")
            return

        start = time.monotonic()
        surrendered = False
        while time.monotonic() - start < max_wait:
            if not running(): break
            # results screen -> back to the village
            if self._click_return_home(timeout=0):
                time.sleep(2)
                for _ in range(10):
                    if game_ready(): return
                    time.sleep(1)
                break
            # optional early end: End Battle -> confirm
            if not surrendered and self.surrender_after > 0 and time.monotonic() - start > self.surrender_after:
                if self._click_end_battle(timeout=0) or Auto_Learn.learn_button("end_battle", tap=True):
                    time.sleep(0.7)
                    if not self._click_okay(timeout=3): Auto_Learn.learn_button("okay_button", tap=True, min_interval=0)
                    surrendered = True
            # results screen not recognised yet -> once the battle is over (no End Battle button),
            # find "Return Home" by its text and learn it
            if time.monotonic() - start > 15 and not self.in_battle() and Auto_Learn.learn_button("return_home", tap=True, min_interval=12):
                time.sleep(2)
                for _ in range(10):
                    if game_ready(): return
                    time.sleep(1)
            time.sleep(1)
        # (no Android back key here: in the village it opens the "exit game?" dialog)
        if game_ready(): return
        logger.warning("Battle end not detected, reopening the game")
        if restart: start_coc(force_restart="results screen not recognised")
        else: stop_coc(reason="results screen not recognised")

    # ============================================================
    # 📱 Screen Interaction
    # ============================================================
    
    def _click_okay(self, timeout=5):
        if tap_taught("okay_button", timeout=timeout): return True # taught from the user's screen wins
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["okay"], thresh=0.9),
            timeout=timeout,
        )
    
    def _click_surrender(self, timeout=5):
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["surrender"], thresh=0.9),
            timeout=timeout
        )
    
    def _click_end_battle(self, timeout=5):
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
        if not click_with_timeout(
            locate_find_a_match,
            timeout=5
        ):
            logger.error("Failed to click find a match button")
            return False

        # Saved army of the active loadout
        try: self.select_saved_army((self.plan or {}).get("army", ""))
        except Exception: logger.warning("Saved army selection failed, attacking with the current army")

        # Confirm attack
        if not click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["confirm_attack"], thresh=0.9),
            timeout=5
        ):
            logger.error("Failed to confirm attack")
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
            frame = Frame_Handler.get_frame(grayscale=False)
            for text, x1, y1, x2, y2, conf in ocr_boxes(frame):
                if conf > 0.3 and _word_hit(text, name.lower()):
                    Input_Handler.click((x1 + x2) / 2, (y1 + y2) / 2)
                    return True
            return False
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
            if find_taught("end_battle"): return True
            x, y = Frame_Handler.locate(self.assets["end_battle"], thresh=0.9)
            if x is not None and y is not None: return True
            time.sleep(0.3)
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
            time.sleep(0.8) # loot numbers count up for a moment
            frame = Frame_Handler.get_frame(grayscale=False)
            loot = {k: read_taught_number(f"enemy_{k}", frame) for k in need}
            checks = [(loot[k] or 0) >= v for k, v in need.items() if v > 0 and (k != "dark" or teach.taught("enemy_dark"))]
            ok = (all(checks) if f.get("mode", "all") == "all" else any(checks)) if checks else True
            logger.info(f"Base loot: gold={loot['gold']} elixir={loot['elixir']} dark={loot['dark']} -> {'attack' if ok else 'next'}")
            self.record_search(loot, accepted=ok)
            if ok: return True
            if skip == int(f.get("max_skips", 30)): break
            if not tap_taught("next_button", timeout=2) and not Auto_Learn.learn_button("next_button", tap=True, min_interval=0):
                logger.warning("Next button not found, attacking this base")
                return True
            time.sleep(1.5)
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
        
        # Remove partially visible card edges
        remove_left = 0
        remove_right = len(dists_discrete) - 1
        while dists_discrete[remove_left] != dist_categories[2]: remove_left += 1
        while dists_discrete[remove_right] != dist_categories[2]: remove_right -= 1
        peaks = peaks[remove_left:remove_right+2]
        peaks_norm = peaks_norm[remove_left:remove_right+2]
        dists_discrete = dists_discrete[remove_left:remove_right+1]
        
        assert len(peaks) % 2 == 0, "Uneven number of troop slot edges detected"
        
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
                for i in reversed(range(0, 12)):
                    loc = number_locs[i]
                    if loc[0] is not None and loc[1] is not None:
                        count = i
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
        section = Frame_Handler.get_frame_section(card_center-0.01, 0.89, card_center+0.01, 0.91, grayscale=False)
        return np.all(section[:, :, 0] == section[:, :, 1]) and np.all(section[:, :, 1] == section[:, :, 2])

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
        uses_sides = any(plan.get(k) in ("sides", "left", "right") for k in ("troops_where", "heroes_where", "clan_where"))
        order = {"troop": 0, "clan": 1, None: 1, "hero": 2, "spell": 3}
        idx = sorted([i for i in range(len(card_centers)) if available_slots[i]], key=lambda i: order.get(card_types[i], 1))
        hold_back = set(int(x) for x in str(plan.get("second_wave_spells", "")).replace(" ", "").split(",") if x.isdigit())
        hero_n = 0
        for i in idx:
            t = card_types[i]
            cx = card_centers[i]
            if t == "troop" and uses_sides and not getattr(self, "side_points", None):
                self.calibrate_sides(cx)
            if t == "troop":
                pts = self.points_for(plan.get("troops_where", "sides"))
                Input_Handler.click(cx, 0.9)
                share = TROOP_DEPLOY_TIME / len(pts)
                for k, pt in enumerate(pts):
                    Input_Handler.down(*pt, pointer=0)
                    end_time = time.monotonic() + share
                    while time.monotonic() < end_time and not self.card_gray(cx): time.sleep(0.05)
                    if k == len(pts) - 1: # last spot: finish the card
                        end2 = time.monotonic() + TROOP_DEPLOY_TIME
                        while time.monotonic() < end2 and not self.card_gray(cx): time.sleep(0.05)
                    Input_Handler.up(pointer=0)
                self.deployed_troops.append(cx)
                self.troops_done_at = time.monotonic()
            elif t in ("clan", None):
                pts = self.points_for(plan.get("clan_where", "sides"))
                Input_Handler.click(cx, 0.9)
                Input_Handler.click(*pts[0], n=max(1, card_counts[i]) if t is None else 1)
            elif t == "hero":
                pts = self.points_for(plan.get("heroes_where", "sides"))
                Input_Handler.click(cx, 0.9)
                Input_Handler.click(*pts[hero_n % len(pts)]) # heroes alternate between the sides
                hero_n += 1
                self.deployed_heroes.append(cx)
                self.heroes_done_at = time.monotonic()
            elif t == "spell":
                self.spell_no = getattr(self, "spell_no", 0) + 1
                if self.spell_no in hold_back:
                    self.held_spells.append((cx, card_counts[i]))
                    continue
                if plan.get("spells_where", "center") == "none": continue
                delay = float(plan.get("spells_delay", 3))
                waited = time.monotonic() - getattr(self, "troops_done_at", time.monotonic())
                if delay > waited: time.sleep(delay - waited)
                Input_Handler.click(cx, 0.9)
                self.cast_spell(card_counts[i])
        Input_Handler.click(0.01, 0.9)

    def cast_spell(self, n):
        import random
        x0, y0 = self.SPELL_CENTER
        for _ in range(max(1, n)):
            Input_Handler.click(x0 + random.uniform(-0.04, 0.04), y0 + random.uniform(-0.04, 0.04))

    def second_wave(self):
        """Held-back spells (e.g. heal / rage) once the army has taken damage."""
        import time
        plan = getattr(self, "plan", None) or {}
        if not self.held_spells: return
        after = float(plan.get("second_wave_after", 20))
        start = getattr(self, "troops_done_at", time.monotonic())
        if after > time.monotonic() - start: time.sleep(after - (time.monotonic() - start))
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
        pts = self.points_for((getattr(self, "plan", None) or {}).get("troops_where", "bottom"))
        px, py = pts[-1]
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

    def activate_hero_abilities(self):
        """Tap the deployed hero cards again after a delay to fire their abilities."""
        import time
        plan = getattr(self, "plan", None) or {}
        delay = float(plan.get("abilities_after", getattr(self, "hero_retap", 0))) if plan else getattr(self, "hero_retap", 0)
        if delay <= 0 or not self.deployed_heroes: return
        since = time.monotonic() - (getattr(self, "heroes_done_at", None) or time.monotonic())
        if delay > since: time.sleep(delay - since)
        for x in self.deployed_heroes:
            Input_Handler.click(x, 0.9)
            time.sleep(0.15)
        logger.info(f"Activated {len(self.deployed_heroes)} hero abilities")
    
    def complete_normal_attack(self, restart=True, exclude_clan_troops=False):
        import time, numpy as np

        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_up(y1=0.5)
        self.deployed_heroes = []
        self.deployed_troops = []
        self.side_points = None
        self.held_spells = []
        self.spell_no = 0
        self.troops_done_at = self.heroes_done_at = None
        if getattr(self, "plan", None): logger.info(f"Attack plan: {self.plan.get('name', '')}")
        
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
        try: self.activate_hero_abilities()
        except Exception: logger.warning("Hero ability activation failed")
        try: self.second_wave()
        except Exception: logger.warning("Second spell wave failed")
        self.finish_battle(restart)
    
    def complete_builder_attack(self, restart=True):
        import numpy as np
        
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_up(y1=0.5)
        
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

    @require_exit()
    def run_home_base(self, timeout=10, restart=True):
        import time
        
        try:
            # Make sure in home base
            start_time = time.time()
            found = False
            while time.time() - start_time < timeout:
                if in_home_base(): found = True; break
                time.sleep(0.3)
            if not found:
                logger.error("Not in home base. Aborting home attack.")
                Auto_Learn.handle_unknown_screen("home_attack")
                return
            
            # Complete an attack
            if self.start_normal_attack(timeout):
                self.complete_normal_attack(restart=restart, exclude_clan_troops=EXCLUDE_CLAN_TROOPS)
            else:
                start_coc() # reset in case stuck on find a match screen
        
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
