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


def scan(acc, log, brain=None, max_pages=30):
    """Opens every card's Info page once. -> {card: page info}."""
    import numpy as np
    from PIL import Image
    from royale import game, collection
    from royale.account import _tab, _bad, TABS, TAB_Y
    import utils
    DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    pages, files, seen_spots = {}, {}, set()

    def close():
        for _ in range(3):
            fr = game.frame()
            x = red_x(fr)
            if not x: return True
            game.tap(*x); time.sleep(0.9)
        return False

    def study(tx, ty):
        game.tap(tx, ty); time.sleep(0.9)
        ws = game.words(game.frame())
        if _bad(ws): close(); return
        info = game.find_word(ws, "info", y_min=max(0.0, ty - 0.05), y_max=min(1.0, ty + 0.25))
        if not info:                                   # the tap opened nothing (or something else): out again
            game.tap(tx, ty); time.sleep(0.5)
            return
        game.tap(*info); time.sleep(1.4)
        fr = game.frame()
        ws = game.words(fr)
        if _bad(ws): close(); return
        p = read_page(fr, ws)
        name = p.get("name")
        key = f"{name or 'unknown'}{'_' + p['form'] if p['form'] != 'plain' else ''}"
        if name and key in pages:
            close(); return
        H, W = fr.shape[:2]
        if name and p.get("art_box"):
            x0, y0, x1, y1 = p["art_box"]
            art = Image.fromarray(fr[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)])
            suf = {"evolution": "_ev1", "hero": "_hero"}.get(p["form"], "")
            art.resize((252, 313), Image.Resampling.LANCZOS).save(DIR / f"{name}{suf}_user.jpg", quality=92)
        pages[key if name else f"unknown_{len(pages)}"] = p
        import io
        buf = io.BytesIO()
        Image.fromarray(fr).save(buf, "JPEG", quality=85)
        stem = f"inbox/royale_cards/{_safe(acc)}_{stamp}/{len(pages):03d}_{key}"
        files[stem + ".jpg"] = buf.getvalue()
        files[stem + ".json"] = json.dumps({"page": p, "words": [[t, list(b)] for t, b in ws][:80],
                                            "account": str(acc)}, ensure_ascii=False, indent=1).encode("utf-8")
        log.info(f"Clash Royale: card page — {name or '?'} {p.get('level', '')} {p['form']}"
                 + (f" cycles {p['cycles']}" if p.get("cycles") else "") + (f" ability {p['ability']}" if p.get("ability") else ""))
        close()

    _tab("cards")
    ws = game.words(game.frame())
    d = game.find_word(ws, "decks", y_max=0.25)
    if d: game.tap(*d); time.sleep(1.0)
    # the deck: 2 rows of 4 cards at the top of the Decks page
    fr = game.frame()
    for t, b in game.words(fr):
        m = re.search(r"level\s*(\d{1,2})", t, re.I)
        if m and (b[2] + b[4]) / 2 < 0.6:
            cx, cy = (b[1] + b[3]) / 2, (b[2] + b[4]) / 2
            if (round(cx, 1), round(cy, 1)) in seen_spots: continue
            seen_spots.add((round(cx, 1), round(cy, 1)))
            study(cx, cy - 0.06)
    # the collection, page by page
    ws = game.words(game.frame())
    c = game.find_word(ws, "collection", y_max=0.25)
    if c:
        game.tap(*c); time.sleep(1.2)
        still = 0
        for _page in range(max_pages):
            before = len(pages)
            fr = game.frame()
            labels = []
            for t, b in game.words(fr):
                if re.search(r"level\s*\d{1,2}", t, re.I):
                    labels.append(((b[1] + b[3]) / 2, (b[2] + b[4]) / 2))
            for cx, cy in labels:
                if 0.2 < cy < 0.88: study(cx, cy - 0.06)
            still = still + 1 if len(pages) == before else 0
            if still >= 2 or not utils: break
            try: utils.Input_Handler.drag(0.5, 0.78, 0.5, 0.33, 0.5, 0.1, 12)
            except Exception: break
            time.sleep(1.0)
    game.tap(TABS["battle"], TAB_Y)
    _mark(acc, len(pages))
    # what the brain needs now
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
    # to the learning repo (one commit), when it is set up
    if files:
        try:
            import learn_sync
            if learn_sync.configured():
                files[f"inbox/royale_cards/{_safe(acc)}_{stamp}/cards.json"] = json.dumps(
                    pages, ensure_ascii=False, indent=1).encode("utf-8")
                learn_sync.commit_files(files, f"royale cards: {len(pages)} card pages from {acc}")
                log.info(f"Clash Royale: {len(pages)} card pages sent to the learning repo")
        except Exception as e:
            log.info(f"Clash Royale: sending the card pages failed — {e}")
    log.info(f"Clash Royale: studied {len(pages)} cards (deck + collection)")
    return pages


def _safe(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"
