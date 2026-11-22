"""
The eyes learn from this PC's own battles: every few seconds of a battle the arena picture is kept together with
what the big model found in it. The weekly training (royale.trainer) adds the sure ones (confidence >= 0.7) to its
data — self-training on the exact screen, emulator and settings the bot plays on, which no dataset on the internet
has. ~/.CoC_Bot/royale_frames/ (the newest 4000 pictures are kept, ~250 MB).
"""
import json, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "royale_frames"
KEEP = 4000
SURE = 0.7
_S = {"t": 0.0, "n": 0}


def clean(dets):
    """6.8: what is kept as a label: no "unit" whose middle sits inside a tower (a tower skin / decoration the model
    misread — self-training on it would teach the mistake again)."""
    towers = []
    for n, c, x0, y0, x1, y1 in dets:
        if n.endswith("-tower") and c >= 0.4:
            mx, my = 0.15 * (x1 - x0), 0.15 * (y1 - y0)
            towers.append((x0 + mx, y0 + my, x1 - mx, y1 - my))
    out = []
    for d in dets:
        n, c, x0, y0, x1, y1 = d
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not n.endswith("-tower") and any(a <= cx <= e and b <= cy <= f for a, b, e, f in towers): continue
        out.append(d)
    return out


def keep(every=4.0, empty=False):
    """Called from the battle loop: the big model's last picture + its detections, every `every` seconds.
    empty=True (6.8): the arena at the very start of a battle, before any card is down — the towers are its only
    labels, so the skins / decorations of THIS account's arena are learned as "nothing" (negative pictures)."""
    if not empty and time.monotonic() - _S["t"] < every: return False
    from royale import strong_eyes
    seen = strong_eyes.last_seen()
    if not seen: return False
    fr, dets = seen
    if empty:
        sure = [d for d in dets if d[0].endswith("-tower") and d[1] >= 0.5]
        if len(sure) < 4: return False                                # the towers must be seen to be the labels
    else:
        sure = clean([d for d in dets if d[1] >= SURE and d[0] not in ("elixir", "clock")])
        if len(sure) < 3: return False                                # an empty arena teaches little
    import cv2
    x0, y0, x1, y1 = strong_eyes.arena_box(fr.shape)
    h, w = fr.shape[:2]
    xa, ya, xb, yb = max(0, int(x0)), max(0, int(y0)), min(w, int(x1)), min(h, int(y1))
    crop = fr[ya:yb, xa:xb]
    if crop.size == 0: return False
    arena = cv2.resize(crop, (strong_eyes.W, strong_eyes.H), interpolation=cv2.INTER_AREA)
    sx, sy = strong_eyes.W / max(1, xb - xa), strong_eyes.H / max(1, yb - ya)
    boxes = [[n, round(c, 3), (a - xa) * sx, (b - ya) * sy, (e - xa) * sx, (f - ya) * sy] for n, c, a, b, e, f in sure]
    DIR.mkdir(parents=True, exist_ok=True)
    stem = time.strftime("%Y%m%d_%H%M%S") + f"_{_S['n'] % 1000:03d}" + ("_empty" if empty else "")
    cv2.imwrite(str(DIR / f"{stem}.jpg"), cv2.cvtColor(arena, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    (DIR / f"{stem}.json").write_text(json.dumps({"boxes": boxes}), encoding="utf-8")
    _S["t"], _S["n"] = time.monotonic(), _S["n"] + 1
    if _S["n"] % 50 == 0:                                             # the oldest go
        pics = sorted(DIR.glob("*.jpg"))
        for p in pics[:max(0, len(pics) - KEEP)]:
            p.unlink(missing_ok=True); p.with_suffix(".json").unlink(missing_ok=True)
    return True


def count():
    return len(list(DIR.glob("*.jpg"))) if DIR.exists() else 0
