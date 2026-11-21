"""
The bot studies the player's cards by itself, the way the user showed it: Cards tab -> every card of the deck and
of the collection -> tap it -> Info -> a picture of the card's page -> what it says is read (name, level, rarity,
type, Evolution / Hero, evolution cycles, the hero ability and its cost) -> closed with the red X.

  - the card's own picture is cut from its page and kept as a reference for the eyes
    (~/.CoC_Bot/learn/royale_cards/<card>[_ev1|_hero]_user.jpg): the hand reader knows the game's current art
  - evolved / hero cards and their cycles go to the brain (which plays come out evolved, the hero's ability)
  - every page (picture + the words read) is sent to the learning repo, inbox/royale_cards/<account>_<time>/,
    in one commit: Claude reads them, fills what the bot could not, and adds cards it did not know

Only Info and the red X are tapped: never Upgrade, Star Level, the magic items or anything with a price.
Runs once a week by itself (setting royale.scan_cards) or when the app's "Study my cards now" button asks.
"""
import json, re, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn" / "royale_cards"
STATE = DIR / "scan.json"
RARITIES = ("common", "rare", "epic", "legendary", "champion", "hero")
TYPES = ("troop", "building", "spell", "tower troop")


def due(acc, every=7 * 86400):
    try:
        d = json.loads(STATE.read_text(encoding="utf-8")).get(str(acc)) or {}
        return time.time() - d.get("t", 0) > every
    except (OSError, ValueError):
        return True


def _mark(acc, n):
    try:
        DIR.mkdir(parents=True, exist_ok=True)
        d = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        d[str(acc)] = {"t": time.time(), "cards": n}
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass


def _k(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def red_x(frame):
    """The red close button (top right of a card's page) -> (x, y) fractions or None."""
    import numpy as np
    H, W = frame.shape[:2]
    y0, y1, x0 = int(0.02 * H), int(0.45 * H), int(0.78 * W)
    s = frame[y0:y1, x0:].astype(np.int16)
    m = (s[..., 0] > 190) & (s[..., 1] < 90) & (s[..., 2] < 90)
    if m.sum() < 150: return None
    ys, xs = np.where(m)
    # the topmost red blob (a red button lower down, e.g. a badge, is not the X)
    top = ys.min()
    sel = ys < top + int(0.06 * H)
    bw, bh = xs[sel].max() - xs[sel].min() + 1, ys[sel].max() - ys[sel].min() + 1
    # the close button is a red square about 7% of the width: a small red dot / badge is not it
    if sel.sum() < 0.0004 * W * H or not (0.5 < bw / max(1, bh) < 2.4) or bw < 0.045 * W: return None
    return (x0 + xs[sel].mean()) / W, (y0 + ys[sel].mean()) / H


def read_page(frame, words):
    """A card's Info page -> {name, level, rarity, type, form, cycles, ability, ability_cost, art_box}."""
    from royale.brain import cards_db
    H, W = frame.shape[:2]
    names = {_k(n): n for n in cards_db()}
    out = {"form": "plain"}
    name_box = None
    for t, b in words:
        k = _k(t)
        cy = (b[2] + b[4]) / 2 if len(b) > 4 else 0.5
        if k in names and "name" not in out and cy < 0.5:
            out["name"], name_box = names[k], b
        m = re.search(r"level\s*(\d{1,2})", t, re.I)
        if m and "level" not in out and "star" not in t.lower(): out["level"] = int(m.group(1))
        if k in RARITIES and k != "hero" and "rarity" not in out: out["rarity"] = t.strip().title()
        if k in {_k(x) for x in TYPES} and "type" not in out: out["type"] = t.strip().title()
        if k == "evolution": out["form"] = "evolution"
        if k == "hero" and cy < 0.5: out["form"] = "hero"
        if k == "evolved" and out["form"] == "plain": out["form"] = "evolution"
    # the cycles number: the number next to / under "Cycles"
    for i, (t, b) in enumerate(words):
        if _k(t).startswith("cycles"):
            m = re.search(r"(\d)", t)
            if m: out["cycles"] = int(m.group(1))
            else:
                for t2, b2 in words[i + 1:i + 4]:
                    if re.fullmatch(r"\d", t2.strip()): out["cycles"] = int(t2.strip()); break
    # a hero's ability: the name in the row with the round ability icon (the words just above the price buttons)
    if out["form"] == "hero":
        for t, b in words:
            cy = (b[2] + b[4]) / 2 if len(b) > 4 else 0
            if 0.6 < cy < 0.82 and len(t) > 4 and not re.search(r"\d", t) and _k(t) not in ("upgrade", "starlevel"):
                out["ability"] = t.strip(); break
    if name_box:
        ny = (name_box[2] + name_box[4]) / 2
        # the card's picture: left of the name, from a little above it to ~15% of the screen below
        out["art_box"] = [0.03, max(0.0, ny - 0.06), 0.33, min(1.0, ny + 0.16)]
    return out


def scan(acc, log, brain=None, max_pages=30, on_done=None):
    """FAST: every card of the deck and the collection -> tap, Info, a picture, the X — nothing is read meanwhile
    (the Info button's place is learned on the first card, then tapped straight away). Then, in the background
    while the bot goes on playing, every picture is read, kept and sent in one commit to the learning repo, and
    on_done(pages) is called. -> number of pictures taken."""
    from royale import game
    from royale.account import _tab, _bad, TABS, TAB_Y
    import utils
    DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    shots = []                                         # (frame, in_deck)
    info_off = [None]                                  # where Info shows, relative to the tapped card

    def close():
        for _ in range(3):
            x = red_x(game.frame())
            if not x: return True
            game.tap(*x); time.sleep(0.45)
        return False

    def find_info(tx, ty):
        """The Info button under the tapped card: read only a small strip there (fast)."""
        fr = game.frame()
        H, W = fr.shape[:2]
        x0, x1 = max(0.0, tx - 0.2), min(1.0, tx + 0.2)
        y0, y1 = max(0.0, ty - 0.05), min(1.0, ty + 0.3)
        crop = fr[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
        for b in utils.ocr_boxes(crop):
            t = b[0].strip().lower()
            if b[5] > 0.4 and t.startswith("info"):
                return x0 + (b[1] + b[3]) / 2 * (x1 - x0), y0 + (b[2] + b[4]) / 2 * (y1 - y0)
        if _bad([(b[0].strip().lower(), b) for b in utils.ocr_boxes(crop)]): return None
        return None

    def shoot(tx, ty, in_deck=False):
        game.tap(tx, ty); time.sleep(0.45)
        if info_off[0]:                                # Info where it was on the other cards: straight to it
            game.tap(tx + info_off[0][0], ty + info_off[0][1]); time.sleep(0.75)
            if not red_x(game.frame()):                # the page did not open: look for Info properly
                game.tap(tx, ty); time.sleep(0.45)
                info = find_info(tx, ty)
                if not info: game.tap(tx, ty); time.sleep(0.3); return
                game.tap(*info); time.sleep(0.75)
        else:
            info = find_info(tx, ty)
            if not info: game.tap(tx, ty); time.sleep(0.3); return
            info_off[0] = (info[0] - tx, info[1] - ty)
            game.tap(*info); time.sleep(0.9)
        fr = game.frame()
        if red_x(fr): shots.append((fr, in_deck))
        close()

    t0 = time.time()
    _tab("cards")
    ws = game.words(game.frame())
    d = game.find_word(ws, "decks", y_max=0.25)
    if d: game.tap(*d); time.sleep(0.8)
    seen = set()
    for t, b in game.words(game.frame()):                  # the deck: the 8 "Level N" labels at the top
        if re.search(r"level\s*\d{1,2}", t, re.I) and (b[2] + b[4]) / 2 < 0.6:
            cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
            if (round(cx, 1), round(cy, 1)) in seen: continue
            seen.add((round(cx, 1), round(cy, 1)))
            shoot(cx, cy - 0.06, in_deck=True)
    ws = game.words(game.frame())
    c = game.find_word(ws, "collection", y_max=0.25)
    if c:
        game.tap(*c); time.sleep(1.0)
        last = None
        for _page in range(max_pages):
            labels = [((b[1] + b[3]) / 2, (b[2] + b[4]) / 2) for t, b in game.words(game.frame())
                      if re.search(r"level\s*\d{1,2}", t, re.I)]
            sig = tuple(sorted((round(x, 2), round(y, 2)) for x, y in labels))
            if not labels or sig == last: break            # the end of the collection
            last = sig
            for cx, cy in labels:
                if 0.2 < cy < 0.88: shoot(cx, cy - 0.06)
            try: utils.Input_Handler.drag(0.5, 0.78, 0.5, 0.33, 0.5, 0.1, 12)
            except Exception: break
            time.sleep(0.8)
    game.tap(TABS["battle"], TAB_Y)
    _mark(acc, len(shots))
    log.info(f"Clash Royale: {len(shots)} card pages photographed in {time.time() - t0:.0f}s — reading them in the background")
    import threading
    threading.Thread(target=_process, args=(acc, log, brain, shots, stamp, on_done), daemon=True,
                     name="royale-cards").start()
    return len(shots)


def _process(acc, log, brain, shots, stamp, on_done):
    """In the background: every picture read, the card pictures kept, everything sent in one commit."""
    import io
    from PIL import Image
    from royale import collection
    import utils
    pages, files = {}, {}
    for k, (fr, in_deck) in enumerate(shots):
        try:
            ws = [(b[0].strip().lower(), b) for b in utils.ocr_boxes(fr) if b[5] > 0.4]
            p = read_page(fr, ws)
        except Exception:
            ws, p = [], {"form": "plain"}
        p["in_deck"] = in_deck
        name = p.get("name")
        key = f"{name or 'unknown'}{'_' + p['form'] if p['form'] != 'plain' else ''}"
        if name and key in pages:
            pages[key]["in_deck"] = pages[key].get("in_deck") or in_deck
            continue
        H, W = fr.shape[:2]
        if name and p.get("art_box"):
            x0, y0, x1, y1 = p["art_box"]
            art = Image.fromarray(fr[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)])
            suf = {"evolution": "_ev1", "hero": "_hero"}.get(p["form"], "")
            try: art.resize((252, 313), Image.Resampling.LANCZOS).save(DIR / f"{name}{suf}_user.jpg", quality=92)
            except OSError: pass
        pages[key if name else f"unknown_{k}"] = p
        buf = io.BytesIO()
        Image.fromarray(fr).save(buf, "JPEG", quality=85)
        stem = f"inbox/royale_cards/{_safe(acc)}_{stamp}/{k + 1:03d}_{key}"
        files[stem + ".jpg"] = buf.getvalue()
        files[stem + ".json"] = json.dumps({"page": p, "words": [[t, list(b)] for t, b in ws][:80],
                                            "account": str(acc)}, ensure_ascii=False, indent=1).encode("utf-8")
    if brain is not None:
        for p in pages.values():
            n = p.get("name")
            if not n: continue
            if p["form"] == "evolution": brain.evo_cards[n] = p.get("cycles") or brain.evo_cards.get(n) or 2
            if p["form"] == "hero": brain.heroes.add(n)
            if p.get("level"): brain.levels[n] = p["level"]
    try:
        (DIR / f"pages_{_safe(acc)}.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    try:                                       # the levels read = the collection the deck choice uses
        lv = dict(collection.load(acc, max_age=10 ** 9))
        for p in pages.values():
            if p.get("name") and p.get("level"): lv[p["name"]] = max(lv.get(p["name"], 0), p["level"])
        if lv:
            collection.DIR.mkdir(parents=True, exist_ok=True)
            collection._path(acc).write_text(json.dumps({"t": time.time(), "levels": lv}), encoding="utf-8")
    except Exception:
        pass
    if files:
        try:
            import learn_sync
            if learn_sync.configured():
                files[f"inbox/royale_cards/{_safe(acc)}_{stamp}/cards.json"] = json.dumps(
                    pages, ensure_ascii=False, indent=1).encode("utf-8")
                learn_sync.commit_files(files, f"royale cards: {len(shots)} card pages from {acc}")
                log.info(f"Clash Royale: {len(shots)} card pages sent to the learning repo")
            else:
                log.info("Clash Royale: the learning repo is not set up — the card pages stay on this PC")
        except Exception as e:
            log.info(f"Clash Royale: sending the card pages failed — {e}")
    log.info(f"Clash Royale: read {len(pages)} cards from the pictures")
    if on_done:
        try: on_done(pages)
        except Exception: log.debug("card pages: on_done failed", exc_info=True)


def _safe(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"
