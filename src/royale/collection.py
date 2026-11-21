"""
The bot reads the player's Clash Royale collection by itself, from the screen: every card and its level.
  Cards tab -> Collection -> each "Level N" label is a card: the picture above it is matched against the 121 card
  pictures the eyes know, the label is read -> {card: level}; then it scrolls down until nothing new shows up.
Saved in ~/.CoC_Bot/learn/royale_collection_<account>.json for the deck choice (royale.deck_pick.choose_offline).
"""
import json, re, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "learn"
_REF = {"refs": None}


def _path(acc):
    return DIR / f"royale_collection_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"


def _sig(img):
    """A small colour picture of the card's art (its top 70%: the level label covers the bottom)."""
    import numpy as np
    from PIL import Image
    im = img if isinstance(img, Image.Image) else Image.fromarray(img)
    w, h = im.size
    im = im.crop((int(w * 0.08), int(h * 0.08), int(w * 0.92), int(h * 0.70))).convert("RGB").resize((20, 16))
    a = np.asarray(im, np.float32)
    return (a - a.mean()) / (a.std() + 1e-6)


def refs():
    if _REF["refs"] is None:
        import os
        from PIL import Image
        from royale.vision.constants import IMAGES_DIR
        from royale.brain import cards_db
        real = set(cards_db())                                  # card pictures only (not the other icons)
        d = os.path.join(IMAGES_DIR, "cards")
        out = {}
        for f in os.listdir(d):
            if f.endswith(".jpg") and "_ev" not in f and f[:-4] in real:
                out[f[:-4]] = _sig(Image.open(os.path.join(d, f)))
        _REF["refs"] = out
    return _REF["refs"]


def identify(art):
    """A card's picture -> (card name, distance) — the closest of the known pictures."""
    import numpy as np
    s = _sig(art)
    best = min(refs().items(), key=lambda kv: float(np.abs(kv[1] - s).mean()))
    return best[0], float(np.abs(best[1] - s).mean())


def read_screen(frame, words):
    """frame: RGB picture of the collection; words: [(text, box)] -> {card: level} of the cards on it."""
    H, W = frame.shape[:2]
    out = {}
    for t, b in words:
        m = re.search(r"level\s*(\d{1,2})", t.replace("|", "1").replace("l1", "11"), re.I)
        if not m: continue
        lv = int(m.group(1))
        if not 1 <= lv <= 16: continue
        cx, cy = (b[1] + b[3]) / 2 * W, (b[2] + b[4]) / 2 * H
        cw = 0.19 * W                                       # 4 cards a row
        ch = cw * 1.24
        x0, x1 = int(cx - cw / 2), int(cx + cw / 2)
        y1 = int(cy + 0.02 * W)
        y0 = int(y1 - ch)
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H: continue
        # a boosted card (the pink clock-arrow badge at its top right) is at that level only for a while: skipped
        bx0, by0 = int(cx + cw * 0.25), max(0, int(y0 - cw * 0.15))
        badge = frame[by0:int(y0 + cw * 0.35), bx0:min(W, int(cx + cw * 0.62))].astype(int)
        if badge.size and (((badge[..., 0] > 190) & (badge[..., 1] < 170) & (badge[..., 2] > 190)).mean() > 0.12):
            continue
        name, dist = identify(frame[y0:y1, x0:x1])
        if dist < 0.75 and (name not in out or out[name] < lv):
            out[name] = lv
    return out


def scan(acc, log, max_pages=40):
    """Opens the collection and reads it all. -> {card: level}"""
    from royale import game
    from royale.account import _tab, _bad, TABS, TAB_Y
    _tab("cards")
    ws = game.words(game.frame())
    c = game.find_word(ws, "collection", y_max=0.25)
    if c:
        game.tap(*c); time.sleep(1.2)
    found, still = {}, 0
    import utils
    for page in range(max_pages):
        fr = game.frame()
        ws = game.words(fr)
        if _bad(ws): break
        new = read_screen(fr, [(t, b) for t, b in ws])
        before = len(found)
        for k, v in new.items():
            found[k] = max(found.get(k, 0), v)
        still = still + 1 if len(found) == before else 0
        if still >= 2: break
        try:
            utils.Input_Handler.drag(0.5, 0.78, 0.5, 0.33, 0.5, 0.1, 12)            # one screen down, smoothly
        except Exception:
            game.tap(0.5, 0.5)
        time.sleep(1.0)
    game.tap(TABS["battle"], TAB_Y)
    if found:
        DIR.mkdir(parents=True, exist_ok=True)
        _path(acc).write_text(json.dumps({"t": time.time(), "levels": found}), encoding="utf-8")
        log.info(f"Clash Royale: read the collection — {len(found)} cards and their levels")
    return found


def load(acc, max_age=7 * 86400):
    try:
        d = json.loads(_path(acc).read_text(encoding="utf-8"))
        if time.time() - d.get("t", 0) < max_age: return d.get("levels") or {}
    except (OSError, ValueError):
        pass
    return {}
