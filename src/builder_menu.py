"""
The builder menu of the current game ("Buildings & Heroes", a panel on the right of the village) — read and used.

Every row of the panel is read:
  name        "Gold Storage x 4"  (easyocr, matched to the known names)       -> name, count
  price       "3 000 000"         (the game's own font: game_digits)          -> cost
  price colour white = can pay, red = can't                                   -> affordable
  icon        yellow = gold, pink = elixir, black = dark elixir               -> resource
  "New"       a new building to place (needs placing by hand: skipped)        -> new
An upgrade: tap the row -> the building is selected, its bar shows "Upgrade" (grey, hammer) -> the upgrade window ->
"Confirm" (green). Never the BLUE "Upgrade" (it uses a magic Hammer item) and never anything with gems.
After it, the free builders are read again: one less = the upgrade really started.

Builders: the village counter "2/5" (free / all) next to the Build button.
Positions are fractions of the screen, from the user's own screenshots (1280x720 and 960x540).
"""
import re, time

from utils import (Frame_Handler, Input_Handler, logger, ocr_boxes, _word_hit, TEMP_CACHE)

PANEL_X = 0.735                    # the panel's left edge
ROWS = (0.735, 0.06, 1.0, 0.885)   # where the rows are
CLOSE = (0.982, 0.03)              # the red X
BUILD_BTN = (0.93, 0.94)           # "Build" in the village
TAB_BUILDERS = (0.766, 0.94)
COUNTER = (0.86, 0.70, 0.98, 0.84)  # "2/5  0/2" above the Build button (village)
SWIPE_X = 0.86

# names the game uses in the panel (for fixing small reading mistakes)
KNOWN = [
    "Town Hall", "Wall", "Cannon", "Archer Tower", "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper", "Hidden Tesla",
    "Bomb Tower", "X-Bow", "Inferno Tower", "Eagle Artillery", "Scattershot", "Builder's Hut", "Spell Tower", "Monolith",
    "Multi-Archer Tower", "Ricochet Cannon", "Multi-Gear Tower", "Firespitter", "Giga Inferno", "Giga Tesla",
    "Gold Mine", "Elixir Collector", "Dark Elixir Drill", "Gold Storage", "Elixir Storage", "Dark Elixir Storage",
    "Army Camp", "Barracks", "Dark Barracks", "Laboratory", "Spell Factory", "Dark Spell Factory", "Workshop",
    "Clan Castle", "Pet House", "Blacksmith", "Hero Hall", "Helper Hut", "Crafting Station",
    "Bomb", "Spring Trap", "Air Bomb", "Giant Bomb", "Seeking Air Mine", "Skeleton Trap", "Tornado Trap", "Giga Bomb",
    "Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince", "Dragon Duke",
]
HEROES = {"Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince", "Dragon Duke"}
NEVER = {"Crafting Station"}       # seasonal: not a real upgrade
DANGER = ("gem", "buy", "purchase", "magic", "hammer", "book")


# ---------------------------------------------------------------- reading
def _fix_name(text):
    """OCR name -> (known name, count). 'Gold Stonage *4' -> ('Gold Storage', 4)."""
    from rapidfuzz import fuzz, process
    t = text.strip()
    count = 1
    m = re.search(r"[xX×*]\s*([0-9Il]{1,3})\s*$", t)
    if m:
        try: count = int(m.group(1).replace("I", "1").replace("l", "1"))
        except ValueError: count = 1
        t = t[:m.start()].strip()
    t = re.sub(r"[^a-z' -]", "", t.lower().replace("$", "s"))
    hit = process.extractOne(t, [k.lower() for k in KNOWN], scorer=fuzz.ratio)
    if hit and hit[1] >= 70: return KNOWN[hit[2]], count
    return None, count


def _resource(icon):
    """The small icon right of a price -> "gold" / "elixir" / "dark" (or None)."""
    import numpy as np
    r, g, b = (icon[..., i].astype(int) for i in range(3))
    gold = int(((r > 220) & (g > 170) & (b < 100)).sum())
    elixir = int(((r > 170) & (b > 190) & (g < 130)).sum())
    if max(gold, elixir) >= 8: return "gold" if gold >= elixir else "elixir"
    return "dark"                       # the dark elixir drop is black: no yellow, no pink


def _affordable(price):
    """White price = enough resources; red = not enough."""
    import numpy as np
    r, g, b = (price[..., i].astype(int) for i in range(3))
    white = int(((r > 200) & (g > 200) & (b > 200)).sum())
    red = int(((r > 215) & (g > 70) & (g < 175) & (b > 60) & (b < 170) & (r - g > 60)).sum())
    return white >= red


def read_rows(frame=None):
    """
    The rows visible now: [{"name", "count", "cost", "resource", "affordable", "new", "x", "y", "text"}].
    y = the row's middle (to tap it).
    """
    import game_digits
    frame = frame if frame is not None else Frame_Handler.get_frame(grayscale=False)
    x1, y1, x2, y2 = ROWS
    panel = Frame_Handler.crop(frame, x1, y1, x2, y2)
    boxes = [b for b in ocr_boxes(panel) if b[5] > 0.15]
    to_g = lambda bx, by: (x1 + bx * (x2 - x1), y1 + by * (y2 - y1))
    news = [to_g(b[1], b[2])[1] for b in boxes if b[0].strip().lower() in ("new", "new!")]
    rows = []
    for text, bx1, by1, bx2, by2, conf in boxes:
        gx1, gy1 = to_g(bx1, by1)
        gx2, gy2 = to_g(bx2, by2)
        if gx1 > 0.84 or gx1 < PANEL_X + 0.01: continue          # prices / times / headers are further right
        if len(text.strip()) < 3 or text.strip().lower() in ("new", "new!"): continue
        name, count = _fix_name(text)
        if not name: continue
        h = gy2 - gy1
        if count == 1:                    # "x 2" read as its own word right after the name
            for t2, cx1, cy1, cx2, cy2, _c in boxes:
                m = re.fullmatch(r"\s*[xX×*]\s*([0-9Il]{1,3})\s*", t2)
                if m and cx1 >= bx2 - 0.01 and abs(to_g(cx1, cy1)[1] - gy1) < h * 0.6:
                    try: count = int(m.group(1).replace("I", "1").replace("l", "1"))
                    except ValueError: pass
        # the price line sits right under the name, on the right side
        price = Frame_Handler.crop(frame, 0.845, gy2 - 0.004, 0.979, gy2 + 1.45 * h)
        icon = Frame_Handler.crop(frame, 0.978, gy2 + 0.1 * h, 0.996, gy2 + 1.3 * h)
        # "FREE" (a new wall piece) is written in letters
        free = any(b[0].strip().lower() in ("free", "free!") and -0.5 * h < to_g(b[1], b[2])[1] - gy2 < 2 * h for b in boxes)
        cost, sure = (0, 1.0) if free else game_digits.read(price, want_conf=True)
        new = any(0 <= ny - gy2 <= 2.2 * h for ny in news)
        rows.append({"name": name, "count": count, "cost": cost, "sure": round(float(sure or 0), 2),
                     "resource": _resource(icon), "affordable": _affordable(price) if cost else free, "new": new,
                     "x": 0.86, "y": round((gy1 + gy2 + 1.45 * h) / 2, 4), "text": text})
    return rows


def free_builders(frame=None):
    """Free builders from the village counter "free/all" -> (free, all) or (None, None)."""
    frame = frame if frame is not None else Frame_Handler.get_frame(grayscale=False)
    crop = Frame_Handler.crop(frame, *COUNTER)
    fix = lambda t: t.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("S", "5").replace(" ", "")
    # the builders counter is the left one ("2/5"); the right one is the goblin builder ("0/2")
    for text in [fix(b[0]) for b in sorted(ocr_boxes(crop), key=lambda b: b[1]) if b[5] > 0.2]:
        m = re.fullmatch(r"(\d)[/|\\71](\d)", text)            # the slash is often read as 7, 1 or |
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 2 <= b <= 6 and a <= b: return a, b
    return None, None


# ---------------------------------------------------------------- the panel
def is_open(frame=None):
    frame = frame if frame is not None else Frame_Handler.get_frame(grayscale=False)
    try:
        import screen_model, utils
        label, _d = screen_model.classify(frame, utils.INSTANCE_ID)
        if label == "builder_menu": return True
    except Exception:
        pass
    head = Frame_Handler.crop(frame, 0.78, 0.0, 0.97, 0.06)
    words = " ".join(b[0].lower() for b in ocr_boxes(head))
    return "building" in words or "heroes" in words


def open_panel():
    if is_open(): return True
    Input_Handler.click(*BUILD_BTN)
    for _ in range(15):
        time.sleep(0.2)
        if is_open(): return True
    return False


def close_panel():
    Input_Handler.click(*CLOSE)
    time.sleep(0.3)


def _swipe(up=True):
    """Scroll the rows (up=True shows the rows further down)."""
    a, b = (0.80, 0.22) if up else (0.22, 0.80)
    Input_Handler.swipe(SWIPE_X, a, SWIPE_X, b, duration=250, hold_end_time=150)
    time.sleep(0.45)


def scan(max_pages=12):
    """Every row of the panel (scrolling down), the panel left at its bottom. -> [rows with "page"]."""
    out, seen_pages, last = [], 0, None
    for page in range(max_pages):
        rows = read_rows()
        sig = [(r["name"], r["count"], r["cost"]) for r in rows]
        if sig == last: break
        for r in rows:
            r["page"] = page
            if not any((o["name"], o["count"], o["cost"], o["new"]) == (r["name"], r["count"], r["cost"], r["new"]) for o in out):
                out.append(r)
        last = sig
        seen_pages = page
        _swipe(up=True)
    return out, seen_pages


def find_and_tap(target, max_pages=12):
    """Scroll back up until the row is on screen, then tap it. True if tapped."""
    key = (target["name"], target["count"], target["cost"])
    for _ in range(max_pages + 1):
        for r in read_rows():
            if (r["name"], r["count"], r["cost"]) == key:
                Input_Handler.click(r["x"], r["y"])
                return True
        _swipe(up=False)
    return False


def _like(text, word):
    """Word read with a letter or two wrong ("[pgpade", "Upgpade" -> upgrade)."""
    from rapidfuzz import fuzz
    t = re.sub(r"[^a-z]", "", text.lower())
    return bool(t) and (fuzz.ratio(t, word) >= 70 or (len(t) >= len(word) - 1 and fuzz.ratio(t[1:], word[1:]) >= 70))


# ---------------------------------------------------------------- one upgrade
def _upgrade_buttons(frame):
    """Every grey "Upgrade" in the building's bar with its price above it -> [(x, y, cost, resource)]."""
    import game_digits
    out = []
    bar = Frame_Handler.crop(frame, 0.10, 0.62, 0.90, 0.98)
    boxes = ocr_boxes(bar)
    for text, bx1, by1, bx2, by2, conf in boxes:
        if conf < 0.25 or not _like(text, "upgrade"): continue
        if "more" in text.lower() or "row" in text.lower(): continue
        gx, gy = 0.10 + (bx1 + bx2) / 2 * 0.80, 0.62 + (by1 + by2) / 2 * 0.36
        # "Upgrade More" (pick several walls) has "More" on the line under it: never that one
        under = [o for o in boxes if -0.01 < (o[2] - by2) * 0.36 < 0.05 and abs((o[1] + o[3]) / 2 - (bx1 + bx2) / 2) * 0.80 < 0.04]
        if any(re.sub(r"[^a-z]", "", o[0].lower()).startswith(("mo", "mn")) for o in under): continue
        around = Frame_Handler.crop(frame, gx - 0.035, gy - 0.10, gx + 0.035, gy - 0.02)
        r, g, b = (around[..., i].astype(int).mean() for i in range(3))
        if b > r + 35 and b > 140: continue                          # blue = the magic Hammer: never
        price = Frame_Handler.crop(frame, gx - 0.055, gy - 0.13, gx + 0.055, gy - 0.065)    # the price sits on the button, above the word
        cost = game_digits.read(price)
        out.append((gx, gy - 0.05, cost, _resource(price) if cost else None))
    return out


def _pick_button(btns, res=None):
    """The Upgrade button to press: one whose price can be paid with what is in the storages (the fuller one)."""
    if not btns: return None
    if any(b[2] for b in btns): btns = [b for b in btns if b[2]]     # real Upgrade buttons show their price
    if res:
        ok = [b for b in btns if b[2] and b[3] in ("gold", "elixir", "dark") and (res.get(b[3]) or 0) >= b[2]]
        if ok: return max(ok, key=lambda b: (res.get(b[3]) or 0) - b[2])[:2]
        if any(b[2] for b in btns): return None                      # prices read and none can be paid
    return btns[0][:2]


def _upgrade_button(frame):
    """The grey "Upgrade" (hammer) in the building's bar, never the blue one (magic Hammer). -> (x, y) or None."""
    import numpy as np
    bar = Frame_Handler.crop(frame, 0.10, 0.62, 0.90, 0.98)
    for text, bx1, by1, bx2, by2, conf in ocr_boxes(bar):
        if conf < 0.25 or not _like(text, "upgrade"): continue
        gx, gy = 0.10 + (bx1 + bx2) / 2 * 0.80, 0.62 + (by1 + by2) / 2 * 0.36
        # the button around the word: blue = the magic Hammer -> never
        around = Frame_Handler.crop(frame, gx - 0.035, gy - 0.10, gx + 0.035, gy - 0.02)
        r, g, b = (around[..., i].astype(int).mean() for i in range(3))
        if b > r + 35 and b > 140: continue
        return gx, gy - 0.05
    return None


def _confirm_button(frame):
    """The green Confirm / Upgrade of the upgrade window, only when nothing on it speaks of gems. -> (x, y) or None."""
    boxes = ocr_boxes(Frame_Handler.crop(frame, 0.15, 0.10, 0.85, 0.98))
    to_g = lambda bx, by: (0.15 + bx * 0.70, 0.10 + by * 0.88)
    for t, bx1, by1, bx2, by2, conf in boxes:
        if conf >= 0.25 and (_like(t, "confirm") or _like(t, "upgrade")):
            gx, gy = to_g((bx1 + bx2) / 2, (by1 + by2) / 2)
            px = Frame_Handler.crop(frame, gx - 0.03, gy - 0.02, gx + 0.03, gy + 0.02)
            r, g, b = (px[..., i].astype(int).mean() for i in range(3))
            if not (g > r and g > b + 20): continue                 # not a green button
            # anything about gems / the magic Hammer on or right around this button: never press it
            near = " ".join(o[0].lower() for o in boxes
                            if abs(to_g(0, (o[2] + o[4]) / 2)[1] - gy) < 0.09 and abs(to_g((o[1] + o[3]) / 2, 0)[0] - gx) < 0.16)
            if any(w in near for w in DANGER): continue
            return gx, gy
    return None


def upgrade(row, upgrader=None, tries=12, res=None):
    """Tap the row (already on screen), Upgrade, Confirm. -> True when the upgrade window was confirmed."""
    import utils
    if not find_and_tap(row): return False
    pressed_upgrade = False
    for _ in range(tries):
        time.sleep(0.35)
        frame = Frame_Handler.get_frame(grayscale=False)
        c = _confirm_button(frame)
        if c:
            Input_Handler.click(*c)
            time.sleep(0.6)
            return True
        if not pressed_upgrade:
            u = None
            if upgrader is not None:
                try:
                    x, y = Frame_Handler.locate(upgrader.assets["upgrade"], frame, thresh=0.88, grayscale=False)
                    if x is not None: u = (x, y)
                except Exception:
                    u = None
            if u is None or row.get("name") == "Wall":
                # walls can show a gold and an elixir Upgrade: take the one that can be paid
                u = _pick_button(_upgrade_buttons(frame), res) or u
            if u:
                Input_Handler.click(*u)
                pressed_upgrade = True
                continue
        # the old picture of Confirm (still the same green button in many windows)
        if upgrader is not None:
            try:
                x, y = Frame_Handler.locate(upgrader.assets["confirm"], frame, grayscale=False, thresh=0.85)
                if x is not None:
                    Input_Handler.click(x, y)
                    time.sleep(0.6)
                    return True
            except Exception:
                pass
    # not recognised: the picture goes to Claude (once per screen) so the next version knows it
    try:
        import learn_sync
        learn_sync.report_stuck(utils.INSTANCE_ID, Frame_Handler.get_frame(grayscale=False), [], "upgrade_window")
    except Exception:
        pass
    utils.Input_Handler.click_exit(n=2)
    return False


# ---------------------------------------------------------------- choosing
def choose(rows, walls=False, heroes=True, keep=None, res=None):
    """The best row to upgrade now: can pay, not new; walls or buildings; the most expensive one first."""
    keep = keep or {}
    cands = []
    for r in rows:
        payable = r["affordable"]
        if walls and not payable and res:                     # high walls take gold OR elixir: either is enough
            payable = any((res.get(k) or 0) >= (r["cost"] or 10**12) for k in ("gold", "elixir"))
        if r["new"] or not payable or not r["cost"] or r["name"] in NEVER: continue
        if (r["name"] == "Wall") != walls: continue
        if r["name"] in HEROES and not heroes: continue
        if r["name"] == "Town Hall" and any(o is not r and o["affordable"] and not o["new"] and o["name"] != "Wall" for o in rows): continue
        if keep.get(r["resource"]) and r["cost"] > keep[r["resource"]]: continue
        cands.append(r)
    if walls: cands.sort(key=lambda r: r["cost"])                    # walls: the cheapest first (more walls)
    else: cands.sort(key=lambda r: -r["cost"])                       # buildings: spend where it counts
    return cands[0] if cands else None


def run(upgrader=None, reserve=1, walls_budget=0, heroes=True, max_buildings=6, buildings=True, walls_first=False, res=None):
    """
    Upgrade buildings while more than `reserve` builders are free (one is kept for walls), then walls with
    the free builder (walls are instant). -> {"buildings": [...], "walls": n}
    """
    from utils import in_home_base
    done = {"buildings": [], "walls": 0}
    if not in_home_base(): return done
    free, total = free_builders()
    logger.info(f"Builders: {free if free is not None else '?'} free of {total if total is not None else '?'} "
                f"(keeping {reserve} free for walls)")
    order = ("walls", "buildings") if walls_first else ("buildings", "walls")
    for part in order:
        if part == "buildings": free = _buildings(upgrader, reserve, heroes, max_buildings, buildings, done, free)
        else: free = _walls(upgrader, walls_budget, done, free, res)
    return done


def _resources_now():
    try:
        import utils
        return utils.read_resources(samples=1)
    except Exception:
        return None


def _buildings(upgrader, reserve, heroes, max_buildings, buildings, done, free):
    # ---- buildings
    while buildings and free is not None and free > reserve and len(done["buildings"]) < max_buildings:
        if not open_panel():
            logger.warning("The builder menu did not open")
            break
        rows, _pages = scan()
        pick = choose(rows, walls=False, heroes=heroes)
        if not pick:
            logger.info(f"Builder menu read ({len(rows)} upgrades): nothing that can be paid now")
            close_panel()
            break
        logger.info(f"Upgrading {pick['name']}{' x' + str(pick['count']) if pick['count'] > 1 else ''} "
                    f"for {pick['cost']:,} {pick['resource'] or ''}")
        ok = upgrade(pick, upgrader)
        time.sleep(0.5)
        Input_Handler.click_exit(n=1)
        time.sleep(0.4)
        new_free, _t = free_builders()
        if ok and new_free is not None and new_free < free:
            done["buildings"].append(pick["name"])
            logger.info(f"Upgrade started: {pick['name']} — {new_free} builder(s) free now")
            if upgrader is not None:
                try: upgrader.on_upgrade("building", pick["name"])
                except Exception: pass
            free = new_free
        else:
            logger.warning(f"The upgrade of {pick['name']} did not start (window not recognised)")
            break
    return free


def _walls(upgrader, walls_budget, done, free, res):
    # ---- walls with the builder kept free
    if walls_budget > 0 and free is not None and free >= 1 and walls_budget >= 10**5:
        logger.info("Upgrading walls until the gold / elixir runs out")
    while walls_budget > done["walls"] and free is not None and free >= 1:
        res = _resources_now() or res                  # read in the village (the panel moves the storage bars)
        if not open_panel(): break
        rows, _pages = scan()
        pick = choose(rows, walls=True, res=res)
        if not pick:
            if done["walls"] == 0: logger.info("No wall can be paid now")
            else: logger.info(f"Walls done: {done['walls']} upgraded, not enough gold / elixir for the next one")
            close_panel()
            break
        ok = upgrade(pick, upgrader, res=res)
        time.sleep(0.4)
        Input_Handler.click_exit(n=1)
        if not ok:
            logger.warning("The wall upgrade did not go through (window not recognised)")
            break
        done["walls"] += 1
        logger.info(f"Wall upgraded ({done['walls']}) for {pick['cost']:,} {pick['resource'] or ''}")
        if upgrader is not None:
            try: upgrader.on_upgrade("wall", "Wall")
            except Exception: pass
    return free
