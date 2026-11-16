"""
Free things the game gives: the daily "Free!" gift in the village (bottom right of the shop), the free "Claim!"
rewards of the season pass. Collected now and then (every few hours) when the bot is in the village.

Safe by design: a button is pressed only when it says Free / Claim / Collect, is a green button, and nothing about
money is next to it (€ $ £ price, gems, buy, purchase, offer). Anything unknown: the picture goes to Claude.
"""
import json, re, time
from pathlib import Path

from utils import Frame_Handler, Input_Handler, logger, ocr_boxes

EVERY = 3 * 3600
STATE = Path.home() / ".CoC_Bot" / "daily_rewards.json"
WORDS = ("free", "claim", "collect")
MONEY = ("€", "$", "£", "gem", "buy", "purchase", "offer", "discount", "price", "usd", "egp", "sar")
FREE_BOX = (0.88, 0.40, 0.99, 0.62)        # the green "Free!" box on the right of the village


def _state():
    try: return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _save(d):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def _green(frame, x, y):
    px = Frame_Handler.crop(frame, x - 0.025, y - 0.02, x + 0.025, y + 0.02)
    if px.size == 0: return False
    r, g, b = (px[..., i].astype(int).mean() for i in range(3))
    return g >= r - 5 and g > b + 35          # green or yellow-green (the "Free!" box)


def _is_word(word):
    """Free / Claim / Collect, also read with a wrong letter ("Faeel", "Clam")."""
    from rapidfuzz import fuzz
    if not word or len(word) > 9: return False
    return any(word.startswith(w) or fuzz.ratio(word[:len(w) + 1], w) >= 60 and word[0] == w[0] for w in WORDS)


def safe_buttons(frame, area=(0.0, 0.0, 1.0, 1.0)):
    """Free / Claim / Collect buttons (green, no money near them) -> [(x, y, word)]."""
    x1, y1, x2, y2 = area
    boxes = [b for b in ocr_boxes(Frame_Handler.crop(frame, *area)) if b[5] > 0.25]
    g = lambda bx, by: (x1 + bx * (x2 - x1), y1 + by * (y2 - y1))
    out = []
    for t, bx1, by1, bx2, by2, _c in boxes:
        word = re.sub(r"[^a-z]", "", t.lower())
        if not _is_word(word): continue
        cx, cy = g((bx1 + bx2) / 2, (by1 + by2) / 2)
        if not _green(frame, cx, cy): continue
        near = " ".join(o[0].lower() for o in boxes
                        if abs(g(0, (o[2] + o[4]) / 2)[1] - cy) < 0.15 and abs(g((o[1] + o[3]) / 2, 0)[0] - cx) < 0.14)
        if any(m in near for m in MONEY): continue
        out.append((cx, cy, word))
    return out


def claim_visible(max_taps=8):
    """Press every safe Free / Claim button on the screen now (e.g. the season pass). -> how many."""
    n = 0
    for _ in range(max_taps):
        frame = Frame_Handler.get_frame(grayscale=False)
        btns = safe_buttons(frame)
        if not btns: break
        x, y, w = btns[0]
        Input_Handler.click(x, y)
        n += 1
        time.sleep(1.2)
        # a reward window may open: tap away from buttons to close it
        Input_Handler.click(0.5, 0.08)
        time.sleep(0.6)
    if n: logger.info(f"Free rewards claimed: {n}")
    return n


def free_gift():
    """The daily "Free!" gift in the village. -> True if something was claimed."""
    import utils
    frame = Frame_Handler.get_frame(grayscale=False)
    btns = safe_buttons(frame, FREE_BOX)
    if not btns: return False
    x, y, _w = btns[0]
    Input_Handler.click(x, y)
    time.sleep(1.8)
    got = 0
    for _ in range(4):
        frame = Frame_Handler.get_frame(grayscale=False)
        b = safe_buttons(frame)
        if not b: break
        Input_Handler.click(b[0][0], b[0][1])
        got += 1
        time.sleep(1.5)
    if got: logger.info("Daily free gift claimed")
    else:
        try:
            import learn_sync
            learn_sync.report_stuck(utils.INSTANCE_ID, Frame_Handler.get_frame(grayscale=False), [], "free_gift")
        except Exception:
            pass
    Input_Handler.click_exit(n=2)
    time.sleep(0.5)
    try: utils.to_home_base()
    except Exception: pass
    return got > 0


def run(force=False):
    """Every few hours, from the village: the free gift. -> what was done."""
    st = _state()
    if not force and time.time() - st.get("t", 0) < EVERY: return {}
    st["t"] = time.time()
    _save(st)
    done = {}
    try: done["gift"] = free_gift()
    except Exception: logger.debug("free gift failed", exc_info=True)
    return done
