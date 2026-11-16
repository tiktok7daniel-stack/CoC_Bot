from utils import *
try:
    import configs
    from configs import *
except:
    import configs_build as configs
    from configs_build import *

class Upgrader:
    def __init__(self):
        self.assets = Asset_Manager.upgrader_assets
        self.misc_assets = Asset_Manager.misc_assets
        self.wall_budget = 10**9   # max wall upgrades this cycle (set by CoC_Bot from settings)
        self.skip_walls = False
        self.budget = None         # {"keep_gold": .., "keep_elixir": ..} when smart budget is on
        self.on_upgrade = lambda kind, name: None

    def budget_blocked(self):
        """True when both storages are under the reserve the user wants to keep."""
        if not self.budget: return False
        res = read_resources(samples=1) # checked before every upgrade: one quick reading is enough
        if res is None: return False # can't read -> don't block
        gold_low = res["gold"] is not None and res["gold"] < self.budget.get("keep_gold", 0)
        elixir_low = res["elixir"] is not None and res["elixir"] < self.budget.get("keep_elixir", 0)
        return gold_low and elixir_low

    # ============================================================
    # 📱 Screen Interaction
    # ============================================================
    
    def _click_build_button(self):
        Input_Handler.click(0.95, -0.05)
    
    def _click_home_builders(self):
        Input_Handler.click(0.77, -0.05)
    
    def _click_home_lab(self):
        Input_Handler.click(0.84, -0.05)
    
    def _click_pet_house(self):
        Input_Handler.click(0.97, -0.05)

    def _click_builder_builders(self):
        Input_Handler.click(0.8, -0.05)
    
    def _click_builder_lab(self):
        Input_Handler.click(0.94, -0.05)

    def _click_upgrade(self, timeout=5):
        import cv2, numpy as np
        scale_templates = []
        for scale in np.arange(0.9, 1.1, 0.1):
            scale_templates.append(cv2.resize(self.assets["upgrade"], (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST))
        
        def locate():
            xys = Frame_Handler.batch_locate(scale_templates, thresh=0.90, grayscale=False)
            for x, y in xys:
                if x is None or y is None: continue
                return x, y
            return None, None

        return click_with_timeout(locate, timeout=timeout)

    def _click_home_confirm(self, timeout=5):
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["confirm"], grayscale=False, thresh=0.85, use_cached=True),
            timeout=timeout
        )

    def _click_builder_confirm(self, timeout=5):
        return click_with_timeout(
            lambda: self._find_builder_confirm(),
            timeout=timeout
        )

    def _scroll_to_menu_bottom(self, menu_left, menu_right, menu_top, menu_bottom, max_scrolls=10):
        import numpy as np
        menu_center = (menu_left + menu_right) / 2
        for _ in range(max_scrolls):
            menu_prev = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True)
            Input_Handler.swipe_up(x=menu_center, y1=menu_bottom-0.05, y2=menu_top, duration=0, hold_end_time=0)
            menu_curr = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True)
            diff = np.abs(menu_curr - menu_prev).mean() / 255
            if diff < 0.01: break

    # ============================================================
    # 💰 Resource & Builder Tracking
    # ============================================================
    
    def _builders_by_text(self):
        """Free builders read with OCR: the "free/total" counter at the top of the village (or the old spot)."""
        import re
        frame = Frame_Handler.get_frame(grayscale=False)
        h, w = frame.shape[:2]
        for x1, y1, x2, y2 in ((0.30, 0.0, 0.70, 0.13), (0.86, 0.70, 0.98, 0.84)):
            crop = frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
            try: boxes = ocr_boxes(crop)
            except Exception: continue
            text = " ".join(b[0] for b in boxes if b[5] > 0.25).replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")
            for a, b in re.findall(r"(\d)\s*/\s*(\d)", text):
                if 1 <= int(b) <= 6 and int(a) <= int(b):
                    if not getattr(self, "_builders_text_logged", False):
                        logger.info(f"Builders read as text: {a}/{b}")
                        self._builders_text_logged = True
                    return int(a)
        return None

    def get_home_builders(self, timeout=60, use_cached_frame=False):
            import time, numpy as np
            
            # the current village: the "free/all" counter next to Build, read directly
            try:
                import builder_menu
                free, _all = builder_menu.free_builders()
                if free is not None: return free
            except (KeyboardInterrupt, SystemExit): raise
            except Exception:
                pass
            start = time.time()
            tries = 0
            while time.time() < start + timeout:
                tries += 1
                if tries > 1:   # the font template didn't match: read the "N/M" builders counter as text
                    n = self._builders_by_text()
                    if n is not None: return n
                try:
                    section = Frame_Handler.get_frame_section(0.89, 0.75, -0.07, -0.21, high_contrast=True, use_cached=use_cached_frame)
                    if configs.DEBUG: Frame_Handler.save_frame(section, "home_builders.png")
                    
                    # Find the backslash
                    font_size = 24
                    slash = render_text("/", "SupercellMagic", font_size)
                    x, y, c = Frame_Handler.locate(
                        slash,
                        section,
                        grayscale=True,
                        ref="lc",
                        return_confidence=True
                    )
                    if c < 0.9: time.sleep(0.3); continue # don't hammer adb with screenshots

                    section = Frame_Handler.crop(section, 0, 0, x, 1)

                    # Determine number by best match to template
                    numbers = [
                        render_text(str(i), "SupercellMagic", font_size + j)
                        for j in (-1, 0, 1)
                        for i in range(10)
                    ]
                    xycs = Frame_Handler.batch_locate(
                        numbers,
                        section,
                        grayscale=True,
                        return_confidence=True
                    )
                    xs, ys, cs = zip(*xycs)
                    if max(cs) < 0.8: time.sleep(0.3); continue # don't hammer adb with screenshots
                    available = np.argmax(cs) % 10
                    return available
                except (KeyboardInterrupt, SystemExit): raise
                except Exception as e:
                    logger.error(f"Upgrader.get_home_builders: {e}")
                time.sleep(0.5)
            logger.error("Upgrader.get_home_builders: Failed to get home builders")
            raise Exception("Failed to get home builders")
    
    def get_builder_builders(self, timeout=60, use_cached_frame=False):
        import time, numpy as np
        
        start = time.time()
        while time.time() < start + timeout:
            try:
                section = Frame_Handler.get_frame_section(0.89, 0.75, -0.07, -0.21, high_contrast=True, use_cached=use_cached_frame)
                if configs.DEBUG: Frame_Handler.save_frame(section, "builder_builders.png")
                
                # Find the backslash
                font_size = 26
                slash = render_text("/", "SupercellMagic", font_size)
                x, y, c = Frame_Handler.locate(
                    slash,
                    section,
                    ref="lc",
                    grayscale=True,
                    return_confidence=True
                )
                if c < 0.9: time.sleep(0.3); continue # don't hammer adb with screenshots

                section = Frame_Handler.crop(section, 0, 0, x, 1)

                # Determine number by best match to template
                numbers = [
                    render_text(str(i), "SupercellMagic", font_size + j)
                    for j in (-1, 0, 1)
                    for i in range(10)
                ]
                xycs = Frame_Handler.batch_locate(
                    numbers,
                    section,
                    grayscale=True,
                    return_confidence=True
                )
                xs, ys, cs = zip(*xycs)
                if max(cs) < 0.8: time.sleep(0.3); continue # don't hammer adb with screenshots
                available = np.argmax(cs) % 10
                return available
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                logger.error(f"Upgrader.get_builder_builders: {e}")
            time.sleep(0.5)
        logger.error("Upgrader.get_builder_builders: Failed to get builder builders")
        raise Exception("Failed to get builder builders")

    def home_lab_available(self, timeout=60, use_cached_frame=False):
        import time, numpy as np
        
        start = time.time()
        while time.time() < start + timeout:
            try:
                section = Frame_Handler.get_frame_section(0.94, 0.75, -0.02, -0.21, high_contrast=True, use_cached=use_cached_frame)
                if configs.DEBUG: Frame_Handler.save_frame(section, "home_lab.png")
                
                # Find the backslash
                font_size = 24
                slash = render_text("/", "SupercellMagic", font_size)
                x, y, c = Frame_Handler.locate(
                    slash,
                    section,
                    ref="lc",
                    grayscale=True,
                    return_confidence=True
                )
                if c < 0.9: time.sleep(0.3); continue # don't hammer adb with screenshots

                section = Frame_Handler.crop(section, 0, 0, x, 1)

                # Determine number by best match to template
                numbers = [
                    render_text(str(i), "SupercellMagic", font_size + j)
                    for j in (-1, 0, 1)
                    for i in range(10)
                ]
                xycs = Frame_Handler.batch_locate(
                    numbers,
                    section,
                    grayscale=True,
                    return_confidence=True
                )
                xs, ys, cs = zip(*xycs)
                if max(cs) < 0.8: time.sleep(0.3); continue # don't hammer adb with screenshots
                available = np.argmax(cs) % 10
                return available > 0
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                logger.error(f"Upgrader.home_lab_available: {e}")
            time.sleep(0.5)
        # fallback: read the "x/y" counter as text
        try:
            frac = read_fraction(Frame_Handler.get_frame_section(0.94, 0.75, -0.02, -0.21, high_contrast=True))
            if frac is not None:
                logger.info(f"Upgrader.home_lab_available: read counter {frac[0]}/{frac[1]} with OCR")
                return frac[0] > 0
        except (KeyboardInterrupt, SystemExit): raise
        except Exception: pass
        logger.error("Upgrader.home_lab_available: Failed to get home lab availability")
        raise Exception("Failed to get home lab availability")

    def builder_lab_available(self, timeout=60, use_cached_frame=False):
        import time, numpy as np
        
        start = time.time()
        while time.time() < start + timeout:
            try:
                section = Frame_Handler.get_frame_section(0.94, 0.75, -0.02, -0.21, high_contrast=True, use_cached=use_cached_frame)
                if configs.DEBUG: Frame_Handler.save_frame(section, "builder_lab.png")
                
                # Find the backslash
                font_size = 26
                slash = render_text("/", "SupercellMagic", font_size)
                x, y, c = Frame_Handler.locate(
                    slash,
                    section,
                    ref="lc",
                    grayscale=True,
                    return_confidence=True
                )
                if c < 0.9: time.sleep(0.3); continue # don't hammer adb with screenshots

                section = Frame_Handler.crop(section, 0, 0, x, 1)

                # Determine number by best match to template
                numbers = [
                    render_text(str(i), "SupercellMagic", font_size + j)
                    for j in (-1, 0, 1)
                    for i in range(10)
                ]
                xycs = Frame_Handler.batch_locate(
                    numbers,
                    section,
                    grayscale=True,
                    return_confidence=True
                )
                xs, ys, cs = zip(*xycs)
                if max(cs) < 0.8: time.sleep(0.3); continue # don't hammer adb with screenshots
                available = np.argmax(cs) % 10
                return available > 0
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                logger.error(f"Upgrader.builder_lab_available: {e}")
            time.sleep(0.5)
        # fallback: read the "x/y" counter as text
        try:
            frac = read_fraction(Frame_Handler.get_frame_section(0.94, 0.75, -0.02, -0.21, high_contrast=True))
            if frac is not None:
                logger.info(f"Upgrader.builder_lab_available: read counter {frac[0]}/{frac[1]} with OCR")
                return frac[0] > 0
        except (KeyboardInterrupt, SystemExit): raise
        except Exception: pass
        logger.error("Upgrader.builder_lab_available: Failed to get builder lab availability")
        raise Exception("Failed to get builder lab availability")
    
    @require_exit(x=0.99, y=0.01)
    def pet_house_available(self, timeout=60, use_cached_frame=False):
            import time, numpy as np
            
            self._click_build_button()
            time.sleep(0.5)
            start = time.time()
            while time.time() < start + timeout:
                try:
                    section = Frame_Handler.get_frame_section(0.95, 0.94, -0.02, -0.02, high_contrast=True, use_cached=use_cached_frame)
                    if configs.DEBUG: Frame_Handler.save_frame(section, "pet_house.png")
                    
                    # Find the backslash
                    font_size = 16
                    slash = render_text("/", "SupercellMagic", font_size)
                    x, y, c = Frame_Handler.locate(
                        slash,
                        section,
                        ref="lc",
                        grayscale=True,
                        return_confidence=True
                    )
                    if c < 0.9: time.sleep(0.3); continue # don't hammer adb with screenshots

                    section = Frame_Handler.crop(section, 0, 0, x, 1)

                    # Determine number by best match to template
                    numbers = [
                        render_text(str(i), "SupercellMagic", font_size + j)
                        for j in (-1, 0, 1)
                        for i in range(10)
                    ]
                    xycs = Frame_Handler.batch_locate(
                        numbers,
                        section,
                        grayscale=True,
                        return_confidence=True
                    )
                    xs, ys, cs = zip(*xycs)
                    if max(cs) < 0.8: time.sleep(0.3); continue # don't hammer adb with screenshots
                    available = np.argmax(cs) % 10
                    return available > 0
                except (KeyboardInterrupt, SystemExit): raise
                except Exception as e:
                    logger.error(f"Upgrader.pet_house_available: {e}")
                time.sleep(0.5)
            logger.error("Upgrader.pet_house_available: Failed to get pet house availability")
            raise Exception("Failed to get pet house availability")

    def collect_builder_attack_elixir(self):
        import time
        
        # Align view to top right corner
        Input_Handler.zoom(dir="out")
        for _ in range(3):
            Input_Handler.swipe_down(duration=0)
        for _ in range(3):
            Input_Handler.swipe_left(duration=0)
        Input_Handler.swipe_left(duration=0, hold_end_time=500)
        time.sleep(0.5)
        
        # Open elixir cart menu
        Input_Handler.click(0.61, 0.47)
        time.sleep(0.5)
        
        # Collect elixir
        x, y = Frame_Handler.locate(self.assets["collect"], grayscale=False, thresh=0.9)
        if x is not None and y is not None:
            Input_Handler.click(x, y)
            time.sleep(0.1)
        Input_Handler.click_exit(n=5, delay=0.1)

    # ============================================================
    # 🧱 Upgrade Management
    # ============================================================

    def _get_suggested_upgrade_template(self):
        template = render_text("Suggested upgrades", "SupercellMagic", 15, color=(195, 172, 166))
        return template
    
    def _get_pet_assigned_templates(self):
        assigned_template = render_text("Assigned", "SupercellMagic", 15, color=(195, 172, 166))
        unassigned_template = render_text("Unassigned", "SupercellMagic", 15, color=(195, 172, 166))
        return assigned_template, unassigned_template
    
    def _get_assistant_available_template(self):
        return render_text("Available", "CCBackBeat", 25)
    
    def _get_upgrade_templates(self, upgrade_text, include_new=True, font_size=17):
        templates = [render_text(text, "SupercellMagic", font_size) for text in upgrade_text]
        if include_new:
            templates += [render_text(text, "SupercellMagic", font_size, color=(180, 247, 86)) for text in upgrade_text]
        return templates
    
    def _get_sufficient_resources(self, section):
        return not check_color((255, 123, 114), section, tol=10)

    def _get_upgrade_name(self, categories=["all"]):
        import numpy as np
        x, y = Frame_Handler.locate(self.assets["upgrade_name"], ref="lc", thresh=0.9)
        assert x is not None and y is not None, "Failed to locate upgrade name"
        section = Frame_Handler.get_frame_section(x+0.122, y-0.04, 1-x, y+0.035, high_contrast=True, thresh=255, use_cached=True)
        if configs.DEBUG: Frame_Handler.save_frame(section, "upgrade_name.png")
        upgrade_names = get_vocab_in_categories(categories)
        templates = self._get_upgrade_templates(upgrade_names, include_new=False, font_size=35)
        # upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()[:-3]), categories, phrase_level=True)
        res = Frame_Handler.batch_locate(templates, section, thresh=0.0, grayscale=True, return_confidence=True)
        return upgrade_names[np.argmax([c for x, y, c in res])].lower()

    def _get_upgrade_menu(self, frame, return_bounds=False, pet_house=False):
        menu_left = 0.775 if not pet_house else 0.8
        menu_top = 0.06
        menu_right = 1.0
        menu_bottom = 0.9
        menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
        if return_bounds: return menu, menu_left, menu_top, menu_right, menu_bottom
        return menu

    def _get_potential_upgrade_locs(self, menu, exclude_new=False):
        import numpy as np
        from scipy.ndimage import gaussian_filter1d
        
        def profile_bounds(profile):
            bounds = []
            prev_val = 0
            for i, val in enumerate(profile):
                if prev_val == 0 and val == 1:
                    bounds.append(i)
                if prev_val == 1 and val == 0:
                    bounds.append(i)
                prev_val = val
            if prev_val == 1:
                bounds.append(len(profile))
            bounds = np.array(bounds).reshape((-1, 2))
            centers = (bounds[:, 0] + bounds[:, 1]) / 2
            return bounds, centers
        
        menu_white = filter_color([255, 255, 255], menu, tol=0, return_mask=True)[1]
        menu_green = filter_color([180, 247, 86], menu, tol=0, return_mask=True)[1]
        # menu_red = filter_color((255, 123, 114), menu, tol=0, return_mask=True)[1]
        white_profile = np.where(gaussian_filter1d(menu_white.mean(axis=1), sigma=1) > 0.01, 1, 0)
        green_profile = np.where(gaussian_filter1d(menu_green.mean(axis=1), sigma=1) > 0.01, 1, 0)
        # red_profile = np.where(gaussian_filter1d(menu_red.mean(axis=1), sigma=1) > 0.01, 1, 0)
        white_bounds, white_centers = profile_bounds(white_profile)
        green_bounds, green_centers = profile_bounds(green_profile)
        # red_bounds, red_centers = profile_bounds(red_profile)
        potential_y_locs = [] # in pixels
        
        for i in range(len(white_centers)-1):
            wc = white_centers[i]
            wc_next = white_centers[i+1]
            if (abs(wc_next - wc) < 50) and (not exclude_new or all(abs(green_centers - wc) > 50)):
                potential_y_locs.append(wc)
        return np.array(potential_y_locs)

    def _find_builder_confirm(self):
        import cv2, numpy as np
        from scipy.ndimage import gaussian_filter1d
        thresh = 0.2
        section = Frame_Handler.get_frame_section(0.0, 0.9, 1.0, 0.92, grayscale=False)
        section = cv2.cvtColor(section, cv2.COLOR_RGB2LAB).astype(np.float32)
        btn_color = cv2.cvtColor(np.array([[[189, 230, 76]]], dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        diff = np.linalg.norm((section - btn_color)/255, axis=2).mean(0)
        diff = gaussian_filter1d(diff, sigma=10)
        min_loc = np.argmin(diff)
        x = min_loc / section.shape[1]
        if diff[min_loc] > thresh: return None, None
        x1 = x
        i = min_loc
        while i > 0 and diff[i] < thresh:
            x1 = i / section.shape[1]
            i -= 1
        x2 = x
        i = min_loc
        while i < section.shape[1]-1 and diff[i] < thresh:
            x2 = i / section.shape[1]
            i += 1
        x = (x1 + x2) / 2
        y = 0.85
        return x, y
    
    def _scroll_locate_upgrade(self, locate_func, menu_left, menu_right, menu_top, menu_bottom, dir="down"):
        # First two return values of locate_func should be x and y of located upgrade
        import time, numpy as np
        menu_center = (menu_left + menu_right) / 2
        res = locate_func()
        if res[0] is None or res[1] is None:
            prev_section = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True, thresh=255)
            for _ in range(20):
                if dir == "down":
                    y1, y2 = menu_bottom-0.075, menu_top
                elif dir == "up":
                    y1, y2 = menu_top+0.075, menu_bottom
                Input_Handler.swipe(x1=menu_center, y1=y1, x2=menu_center, y2=y2, duration=0, hold_end_time=100)
                time.sleep(0.1)
                
                # Check if at end of upgrade menu
                section = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True, thresh=255)
                diff = np.abs(section - prev_section).mean() / 255
                if diff < 0.01: break
                prev_section = section
                
                res = locate_func()
                if res[0] is not None and res[1] is not None: break
        return res
    
    @require_exit(x=0.99, y=0.01)
    def home_random_upgrade(self):
        import time, numpy as np

        try:
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_builders()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            town_hall_template = [render_text("Town Hall", "SupercellMagic", 17)]
            hero_templates = [render_text(text, "SupercellMagic", 17) for text in vocab()["heroes"]]
            seasonal_defense_template = [render_text("Crafting Station", "SupercellMagic", 17)]
            if getattr(self, "skip_walls", False): # wall budget used up -> random pick must not choose walls
                seasonal_defense_template.append(render_text("Wall", "SupercellMagic", 17))
            heros_excluded = Task_Handler.excluded("heroes")
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                # x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu, exclude_new=True)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                # if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Locate invalid upgrades
                invalid_templates = town_hall_template + hero_templates + seasonal_defense_template
                locs = Frame_Handler.batch_locate(invalid_templates, menu, thresh=0.75, ref="lc", null_val=-1, grayscale=True, normalize=False, return_all=True)
                town_hall_loc, hero_locs, seasonal_defense_locs = chunk_list(locs, [1, len(hero_templates), len(seasonal_defense_template)])
                invalid_locs = town_hall_loc[0] + [loc for locs_ in seasonal_defense_locs for loc in locs_]
                town_hall_loc = town_hall_loc[0][0]
                if heros_excluded:
                    for locs in hero_locs: invalid_locs += locs
                invalid_y_locs = np.array(invalid_locs)[:, 1] / WINDOW_DIMS[1] + menu_top

                # Choose an upgrade
                valid_y_locs = [y for y in potential_y_locs if min(abs(invalid_y_locs - y)) > 0.02]

                # Prioritize discounted upgrades
                discounted_upgrades = []
                # if len(valid_y_locs) > 0:
                #     discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, normalize=False, return_all=True)
                #     for x, y in discounted_locs:
                #         if len(valid_y_locs) == 0: break
                #         if x is None or y is None: continue
                #         y_global = y / WINDOW_DIMS[1] + menu_top
                #         min_idx = np.argmin(abs(valid_y_locs - y_global))
                #         if abs(valid_y_locs[min_idx] - y_global) < 0.02:
                #             discounted_upgrades.append(valid_y_locs[min_idx])
                #             valid_y_locs = np.delete(valid_y_locs, min_idx)

                if len(discounted_upgrades) > 0:
                    x_upgrade, y_upgrade = menu_center, np.random.choice(discounted_upgrades)
                elif len(valid_y_locs) > 0:
                    x_upgrade, y_upgrade = menu_center, np.random.choice(valid_y_locs)
                else:
                    x_upgrade, y_upgrade = None, None

                if x_upgrade is None or y_upgrade is None:
                    # If no valid upgrades found but town hall is found, then upgrade it
                    if town_hall_loc != (-1, -1) and min(abs(town_hall_loc[1] - potential_y_locs)) < 0.02:
                        x_upgrade, y_upgrade = menu_center, town_hall_loc[1]
                    else: return None, None
                return x_upgrade, y_upgrade
            
            # Choose an upgrade
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            Input_Handler.click(x_upgrade, y_upgrade)
            time.sleep(0.5)
            
            # Try to click upgrade button (only for walls)
            self._click_upgrade(0.5)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "buildings/home-village",
                "traps/home-village",
                "heroes",
                "guardians",
            ])
            
            # Hero upgrades go directly to confirm screen now
            in_hero_hall = upgrade_name in vocab()["heroes"]
            if in_hero_hall and Task_Handler.excluded("heroes"): return None
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_random_upgrade:")
            return None

    @require_exit(x=0.99, y=0.01)
    def home_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if Task_Handler.excluded("heroes"):
                upgrade_text = list(set(upgrade_text) - set(vocab()["heroes"]))
            if len(upgrade_text) == 0: return None
            templates = self._get_upgrade_templates(upgrade_text, include_new=False)
            np.random.shuffle(templates)
            
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_builders()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            
            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)
                res = Frame_Handler.batch_locate(templates, frame, thresh=0.70, ref="lc", return_all=True, grayscale=False, prefilter=True)
                non_discounted_upgrades = []
                for items in res:
                    for x, y in items:
                        if (
                            x is not None and y is not None
                            and (y_sug is None or (y_sug is not None and y > y_sug))
                            and y + 0.025 < menu_bottom
                        ):
                            section = Frame_Handler.crop(frame, menu_left, y, menu_right, y+0.025)
                            sufficient_resources = self._get_sufficient_resources(section)
                            if sufficient_resources:
                                non_discounted_upgrades.append((x, y))
                                continue

                                # Or if it is aligned to green discount tag
                                tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                                if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                    return x, y # Prioritize discounted upgrades
                
                if len(non_discounted_upgrades) > 0:
                    return non_discounted_upgrades[0]
                return None, None
            
            x, y = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x_sug, y)
            time.sleep(0.5)
            
            # Try to click upgrade button (only for walls)
            self._click_upgrade(0.5)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "buildings/home-village",
                "traps/home-village",
                "heroes",
                "guardians",
            ])
            
            # Hero upgrades go directly to confirm screen now
            in_hero_hall = upgrade_name in vocab()["heroes"]
            if in_hero_hall:
                if Task_Handler.excluded("heroes"): return None
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_specified_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def home_upgrade(self):
        if not Task_Handler.excluded("home_base_priority"):
            for priority_level in configs.HOME_BASE_UPGRADE_PRIORITY:
                upgrade_name = self.home_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.home_random_upgrade()
    
    @require_exit(x=0.99, y=0.01)
    def assign_builder_apprentice(self):
        import time
        
        try:
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_builders()
            time.sleep(0.5)
            
            # Find assistant available label
            xys = Frame_Handler.locate(self._get_assistant_available_template(), thresh=0.8, return_all=True)
            xys = sorted(xys, key=lambda pair: pair[1])
            if len(xys) == 0: return
            x, y = xys[0]
            if x is None or y is None: return

            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find assign assistant label
            xys = Frame_Handler.locate(self.assets["assign_assistant"], thresh=0.9, grayscale=False, return_all=True)
            if len(xys) == 0: return
            
            x, y = sorted(xys, key=lambda pair: pair[1])[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find confirm button
            x, y = Frame_Handler.locate(self.assets["confirm_assistant"], grayscale=False, thresh=0.9)
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.assign_builder_apprentice:")
    
    @require_exit(x=0.99, y=0.01)
    def home_lab_random_upgrade(self):
        import time, numpy as np
        
        try:
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_lab()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                # x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                # if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]

                # Determine discounted upgrades
                discounted_upgrades = []
                # discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                # for x, y in discounted_locs:
                #     if len(potential_y_locs) == 0: break
                #     if x is None or y is None: continue
                #     y_global = y / WINDOW_DIMS[1] + menu_top
                #     min_idx = np.argmin(abs(potential_y_locs - y_global))
                #     if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                #         discounted_upgrades.append(potential_y_locs[min_idx])
                #         potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                if len(discounted_upgrades) > 0:
                    return menu_center, np.random.choice(discounted_upgrades)
                return menu_center, np.random.choice(potential_y_locs)
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            Input_Handler.click(x_upgrade, y_upgrade)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "troops",
                "spells",
            ])

            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_lab_random_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def home_lab_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = self._get_upgrade_templates(upgrade_text, include_new=True)
            np.random.shuffle(templates)
            
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_lab()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            
            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.70, ref="lc", grayscale=True, prefilter=True)
                non_discounted_upgrades = []
                for x, y in xys:
                    if (
                        x is not None and y is not None
                        and (y_sug is None or (y_sug is not None and y > y_sug))
                        and y + 0.025 < menu_bottom
                    ):
                        section = Frame_Handler.crop(frame, menu_left, y, menu_right, y+0.025)
                        sufficient_resources = self._get_sufficient_resources(section)
                        if sufficient_resources:
                            non_discounted_upgrades.append((x, y))
                            continue

                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                return x, y # Prioritize discounted upgrades
                
                if len(non_discounted_upgrades) > 0:
                    return non_discounted_upgrades[0]
                return None, None
            
            x, y = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "troops",
                "spells",
            ])
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_lab_specified_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def home_lab_upgrade(self):
        if not Task_Handler.excluded("home_lab_priority"):
            for priority_level in configs.HOME_LAB_UPGRADE_PRIORITY:
                upgrade_name = self.home_lab_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.home_lab_random_upgrade()

    @require_exit(x=0.99, y=0.01)
    def assign_lab_assistant(self):
        import time
        
        try:
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_home_lab()
            time.sleep(0.5)
            
            # Find assistant available label
            xys = Frame_Handler.locate(self._get_assistant_available_template(), thresh=0.8, return_all=True)
            xys = sorted(xys, key=lambda pair: pair[1])
            if len(xys) == 0: return
            x, y = xys[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find assign assistant label
            xys = Frame_Handler.locate(self.assets["assign_assistant"], thresh=0.9, grayscale=False, return_all=True)
            if len(xys) == 0: return
            
            x, y = sorted(xys, key=lambda pair: pair[1])[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find confirm button
            x, y = Frame_Handler.locate(self.assets["confirm_assistant"], grayscale=False, thresh=0.9)
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.assign_lab_assistant:")
    
    @require_exit(x=0.99, y=0.01)
    def pet_house_random_upgrade(self):
        import time, numpy as np
        
        try:
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_pet_house()
            time.sleep(0.5)
            
            # Locate menu boundaries
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True, pet_house=True)
            menu_center = (menu_left + menu_right) / 2
            a_template, ua_template = self._get_pet_assigned_templates()
            xy_a, xy_ua = Frame_Handler.batch_locate([a_template, ua_template], thresh=0.70, grayscale=True, prefilter=True)
            if (xy_a[0] is None or xy_a[1] is None) and (xy_ua[0] is None or xy_ua[1] is None): return None
            y_a = xy_a[1] if xy_a[1] is not None else 1.0
            y_ua = xy_ua[1] if xy_ua[1] is not None else 1.0
            y_start = min(y_a, y_ua)
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_start, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top

                # Determine discounted upgrades
                discounted_upgrades = []
                # discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                # for x, y in discounted_locs:
                #     if len(potential_y_locs) == 0: break
                #     if x is None or y is None: continue
                #     y_global = y / WINDOW_DIMS[1] + menu_top
                #     min_idx = np.argmin(abs(potential_y_locs - y_global))
                #     if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                #         discounted_upgrades.append(potential_y_locs[min_idx])
                #         potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                if len(discounted_upgrades) > 0:
                    return menu_center, np.random.choice(discounted_upgrades)
                return menu_center, np.random.choice(potential_y_locs)
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            Input_Handler.click(x_upgrade, y_upgrade)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name(["pets"])

            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.pet_house_random_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def pet_house_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = self._get_upgrade_templates(upgrade_text, include_new=True)
            np.random.shuffle(templates)
            
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_pet_house()
            time.sleep(0.5)
            
            # Locate menu boundaries
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True, pet_house=True)
            menu_center = (menu_left + menu_right) / 2
            a_template, ua_template = self._get_pet_assigned_templates()
            xy_a, xy_ua = Frame_Handler.batch_locate([a_template, ua_template], thresh=0.70, grayscale=True, prefilter=True)
            if (xy_a[0] is None or xy_a[1] is None) and (xy_ua[0] is None or xy_ua[1] is None): return None
            y_a = xy_a[1] if xy_a[1] is not None else 1.0
            y_ua = xy_ua[1] if xy_ua[1] is not None else 1.0
            y_start = min(y_a, y_ua)
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_start, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                
                # Valid locations
                potential_y_locs = self._get_potential_upgrade_locs(menu, exclude_new=True)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.70, ref="lc", grayscale=False, prefilter=True)
                non_discounted_upgrades = []
                for x, y in xys:
                    if (
                        x is not None and y is not None
                        and (abs(y - potential_y_locs).min() < 0.01)
                        and y + 0.025 < menu_bottom
                    ):
                        section = Frame_Handler.crop(frame, menu_left, y, menu_right, y+0.025)
                        sufficient_resources = self._get_sufficient_resources(section)
                        if sufficient_resources:
                            non_discounted_upgrades.append((x, y))
                            continue

                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                return x, y # Prioritize discounted upgrades
                
                if len(non_discounted_upgrades) > 0:
                    return non_discounted_upgrades[0]
                return None, None
            
            x, y = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name(["pets"])
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.pet_house_specified_upgrade:")
            return None

    @require_exit(x=0.99, y=0.01)
    def pet_house_upgrade(self):
        if not Task_Handler.excluded("pet_house_priority"):
            for priority_level in configs.PET_HOUSE_UPGRADE_PRIORITY:
                upgrade_name = self.pet_house_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.pet_house_random_upgrade()
    
    @require_exit(x=0.99, y=0.01)
    def builder_random_upgrade(self):
        import time, re, numpy as np
        
        try:
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_builder_builders()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                # x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu, exclude_new=True)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                # if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Determine discounted upgrades
                discounted_upgrades = []
                # discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                # for x, y in discounted_locs:
                #     if len(potential_y_locs) == 0: break
                #     if x is None or y is None: continue
                #     y_global = y / WINDOW_DIMS[1] + menu_top
                #     min_idx = np.argmin(abs(potential_y_locs - y_global))
                #     if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                #         discounted_upgrades.append(potential_y_locs[min_idx])
                #         potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                if len(discounted_upgrades) > 0:
                    return menu_center, np.random.choice(discounted_upgrades)
                return menu_center, np.random.choice(potential_y_locs)
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            
            # Get upgrade name
            section = Frame_Handler.get_frame_section(menu_left, y_upgrade - 0.025, menu_center, y_upgrade + 0.025, high_contrast=True)
            upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()), ["buildings/builder-base", "traps/builder-base"], phrase_level=True)
            
            # Try to click upgrade button (only for walls)
            self._click_upgrade(0.5)
            time.sleep(0.5)
            
            # Select upgrade
            Input_Handler.click(x_upgrade, y_upgrade)
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_random_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def builder_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = self._get_upgrade_templates(upgrade_text, include_new=False)
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_builder_builders()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2

            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", grayscale=True)
                non_discounted_upgrades = []
                for (x, y), name in zip(xys, upgrade_text):
                    if (
                        x is not None and y is not None
                        and (y_sug is None or (y_sug is not None and y > y_sug))
                        and y + 0.025 < menu_bottom
                    ):
                        section = Frame_Handler.crop(frame, menu_left, y, menu_right, y+0.025)
                        sufficient_resources = self._get_sufficient_resources(section)
                        if sufficient_resources:
                            non_discounted_upgrades.append((x, y, name))
                            continue
                            
                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                return x, y, name # Prioritize discounted upgrades

                if len(non_discounted_upgrades) > 0:
                    return non_discounted_upgrades[0]
                return None, None, None
            
            x, y, upgrade_name = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up"
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Try to click upgrade button (only for walls)
            self._click_upgrade(0.5)
            time.sleep(0.5)
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_specified_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def builder_upgrade(self):
        if not Task_Handler.excluded("builder_base_priority"):
            for priority_level in configs.BUILDER_BASE_UPGRADE_PRIORITY:
                upgrade_name = self.builder_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.builder_random_upgrade()
    
    @require_exit(x=0.99, y=0.01)
    def builder_lab_random_upgrade(self):
        import time, re, numpy as np
        
        try:
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_builder_lab()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                # x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)
                
                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                # if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Determine discounted upgrades
                discounted_upgrades = []
                # discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                # for x, y in discounted_locs:
                #     if len(potential_y_locs) == 0: break
                #     if x is None or y is None: continue
                #     y_global = y / WINDOW_DIMS[1] + menu_top
                #     min_idx = np.argmin(abs(potential_y_locs - y_global))
                #     if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                #         discounted_upgrades.append(potential_y_locs[min_idx])
                #         potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                if len(discounted_upgrades) > 0:
                    return menu_center, np.random.choice(discounted_upgrades)
                return menu_center, np.random.choice(potential_y_locs)
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            
            # Get upgrade name
            section = Frame_Handler.get_frame_section(menu_left, y_upgrade - 0.025, menu_center, y_upgrade + 0.025, high_contrast=True)
            upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()), "troops", phrase_level=True)
            
            # Select upgrade
            Input_Handler.click(x_upgrade, y_upgrade)
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_lab_random_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def builder_lab_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = self._get_upgrade_templates(upgrade_text, include_new=True)
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open lab upgrade list menu
            self._click_build_button()
            time.sleep(0.5)
            self._click_builder_lab()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=True, prefilter=True)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2

            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=menu_top, duration=0, hold_end_time=100)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=True, prefilter=True)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", grayscale=True)
                non_discounted_upgrades = []
                for (x, y), name in zip(xys, upgrade_text):
                    if (
                        x is not None and y is not None
                        and (y_sug is None or (y_sug is not None and y > y_sug))
                        and y + 0.025 < menu_bottom
                    ):
                        section = Frame_Handler.crop(frame, menu_left, y, menu_right, y+0.025)
                        sufficient_resources = self._get_sufficient_resources(section)
                        if sufficient_resources:
                            non_discounted_upgrades.append((x, y, name))
                            continue
                            
                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                return x, y, name # Prioritize discounted upgrades

                if len(non_discounted_upgrades) > 0:
                    return non_discounted_upgrades[0]
                return None, None, None
            
            x, y, upgrade_name = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            
            # Find confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_lab_specified_upgrade:")
            return None
    
    @require_exit(x=0.99, y=0.01)
    def builder_lab_upgrade(self):
        if not Task_Handler.excluded("builder_lab_priority"):
            for priority_level in configs.BUILDER_LAB_UPGRADE_PRIORITY:
                upgrade_name = self.builder_lab_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.builder_lab_random_upgrade()
    
    # ============================================================
    # 📡 Upgrade Monitoring
    # ============================================================
    
    def run_home_base(self, exclude_base=False, exclude_lab=False, exclude_pet=False):
        import time
        
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_down()
        
        # Building upgrades (and walls: they need no builder and work even with buildings turned off)
        upgrades_started = []
        base_priority = [list(lvl) for lvl in configs.HOME_BASE_UPGRADE_PRIORITY]
        walls_wanted = any("Wall" in lvl for lvl in base_priority) and self.wall_budget > 0
        self.last_walls_done = 0
        # the current game: the "Buildings & Heroes" panel, read row by row (builder_menu). One builder always stays
        # free for the walls. The old way below only runs when the new panel isn't there.
        new_menu_done = False
        if not exclude_base or walls_wanted:
            try:
                import builder_menu, settings as _st
                if builder_menu.free_builders()[0] is not None:
                    keep = 1 if _st.load_app().get("keep_wall_builder", True) is not False else 0
                    res = builder_menu.run(self, reserve=max(keep, int(OPEN_HOME_BUILDERS)), heroes=not Task_Handler.excluded("heroes"),
                                           walls_budget=self.wall_budget if walls_wanted else 0, buildings=not exclude_base,
                                           walls_first=getattr(self, "walls_first", False))
                    upgrades_started += res["buildings"]
                    self.last_walls_done = res["walls"]
                    if res["walls"]:
                        logger.info(f"Walls finished: {res['walls']} upgraded")
                        try: send_notification(f"🧱 البوت خلّص الأسوار: طوّر {res['walls']} سور")
                        except Exception: pass
                    new_menu_done = True
            except (KeyboardInterrupt, SystemExit): raise
            except Exception:
                logger.warning("The new builder menu could not be used, trying the old way", exc_info=True)
            try: Input_Handler.click_exit(n=1)
            except Exception: pass
        if (not exclude_base or walls_wanted) and not new_menu_done:
            walls_done = 0
            wall_misses = 0
            counter = 0
            if walls_wanted: logger.info("Upgrading walls")
            errors_in_row = 0
            while counter < max(MAX_UPGRADES_PER_CHECK, min(self.wall_budget, 200) if walls_wanted else 0):
                counter += 1
                try:
                    # Wall budget: once used up, walls are removed from both priority and random picks
                    self.skip_walls = self.wall_budget - walls_done <= 0
                    configs.HOME_BASE_UPGRADE_PRIORITY = [
                        lvl for lvl in ([[x for x in l if x != "Wall"] for l in base_priority] if self.skip_walls else base_priority) if lvl
                    ]
                    # Smart budget: stop spending once storages fall under the reserve
                    if self.budget_blocked():
                        logger.info("Budget reserve reached, skipping further home upgrades")
                        break
                    initial_builders = self.get_home_builders(1)
                    # walls don't need a free builder, so keep going while wall budget remains
                    if initial_builders <= max(0, OPEN_HOME_BUILDERS) and self.skip_walls: break
                    walls_only = exclude_base or initial_builders <= max(0, OPEN_HOME_BUILDERS)
                    if walls_only:
                        if self.skip_walls: break
                        upgraded = self.home_specified_upgrade(["Wall"]) # no builder / buildings off: walls only
                    else:
                        upgraded = self.home_upgrade()
                    time.sleep(0.5)
                    final_builders = self.get_home_builders(1)
                    if upgraded is not None:
                        upgraded = upgraded.lower()
                        if upgraded == "wall":
                            walls_done += 1
                            wall_misses = 0
                            self.on_upgrade("wall", "Wall")
                            logger.info(f"Wall upgraded ({walls_done})")
                            continue
                        if final_builders < initial_builders:
                            upgrades_started.append(upgraded)
                            self.on_upgrade("building", upgraded)
                        elif final_builders == initial_builders:
                            if walls_wanted and not self.skip_walls and not walls_only:
                                exclude_base = True # buildings can't go on: spend the rest on walls
                                continue
                            break
                    elif walls_wanted and not self.skip_walls and not walls_only:
                        exclude_base = True # no building to upgrade: try walls before giving up
                        continue
                    else:
                        if walls_wanted and walls_only:
                            logger.info("No more walls could be upgraded (not enough resources, or no wall in the builder menu)" if walls_done == 0
                                        else f"Walls done: {walls_done} upgraded")
                        break
                except (KeyboardInterrupt, SystemExit): raise
                except:
                    errors_in_row += 1
                    if errors_in_row >= 3:
                        logger.warning("Home base upgrades stopped: the builder menu could not be read 3 times in a row")
                        break
                    logger.warning("Encountered an error while attempting to upgrade home base. Retrying...")
                    continue
                errors_in_row = 0
            configs.HOME_BASE_UPGRADE_PRIORITY = base_priority
            self.skip_walls = False
            self.last_walls_done = walls_done
            if walls_wanted and walls_done > 0:
                logger.info(f"Walls finished: {walls_done} upgraded")
                try: send_notification(f"🧱 البوت خلّص الأسوار: طوّر {walls_done} سور")
                except Exception: pass
        if not Task_Handler.excluded("builder_apprentice"):
            self.assign_builder_apprentice()
        
        # Lab upgrades
        lab_upgrades_started = []
        try:
            if not exclude_lab and self.home_lab_available(1):
                upgraded = self.home_lab_upgrade()
                time.sleep(0.5)
                final_lab_avail = self.home_lab_available(1)
                if upgraded is not None and not final_lab_avail:
                    lab_upgrades_started.append(upgraded.lower())
                    self.on_upgrade("lab", upgraded)
        except (KeyboardInterrupt, SystemExit): raise
        except:
            logger.warning("Encountered an error while attempting to upgrade home lab. Retrying...")
        if not Task_Handler.excluded("lab_assistant"):
            self.assign_lab_assistant()
        
        # Pet house upgrades
        pet_upgrades_started = []
        try:
            if not exclude_pet and self.pet_house_available(1):
                upgraded = self.pet_house_upgrade()
                time.sleep(0.5)
                final_pet_avail = self.pet_house_available(1)
                if upgraded is not None and not final_pet_avail:
                    pet_upgrades_started.append(upgraded.lower())
                    self.on_upgrade("pet", upgraded)
        except (KeyboardInterrupt, SystemExit): raise
        except: pass

        for upgrade in upgrades_started + lab_upgrades_started + pet_upgrades_started:
            send_notification(f"Started upgrading {upgrade}")
    
    def run_builder_base(self, exclude_base=False, exclude_lab=False):
        import time
        
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_down()

        # Building upgrades
        upgrades_started = []
        if not exclude_base:
            counter = 0
            while counter < MAX_UPGRADES_PER_CHECK:
                counter += 1
                try:
                    initial_builders = self.get_builder_builders(1)
                    if initial_builders <= max(0, OPEN_BUILDER_BUILDERS): break
                    upgraded = self.builder_upgrade()
                    time.sleep(0.5)
                    final_builders = self.get_builder_builders(1)
                    if upgraded is not None:
                        upgraded = upgraded.lower()
                        if final_builders < initial_builders:
                            upgrades_started.append(upgraded)
                            self.on_upgrade("builder_base", upgraded)
                        elif final_builders == initial_builders and upgraded != "wall": break
                    else: break
                except (KeyboardInterrupt, SystemExit): raise
                except:
                    logger.warning("Encountered an error while attempting to upgrade builder base. Retrying...")
        
        # Lab upgrades
        lab_upgrades_started = []
        try:
            if not exclude_lab and self.builder_lab_available(1):
                upgraded = self.builder_lab_upgrade()
                time.sleep(0.5)
                final_lab_avail = self.builder_lab_available(1)
                if upgraded is not None and not final_lab_avail:
                    lab_upgrades_started.append(upgraded.lower())
                    self.on_upgrade("builder_lab", upgraded)
        except (KeyboardInterrupt, SystemExit): raise
        except:
            logger.warning("Encountered an error while attempting to upgrade builder lab. Retrying...")
        
        for upgrade in upgrades_started + lab_upgrades_started:
            send_notification(f"Started upgrading {upgrade}")
