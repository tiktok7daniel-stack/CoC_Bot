"""
Village intelligence (Clash Farmer):
 - scan(upgrader): opens the builder menu, reads every row with OCR -> upgradeable items (name, cost,
   resource, affordable) and running upgrades (name + time left -> exact finish time), the free builders
   and the lab state; saved to ~/.CoC_Bot/village/<id>.json for the window to show.
 - commands from the window (1-tap upgrade, batch walls, rescan) queued in ~/.CoC_Bot/commands/<id>.json
   and run by the bot between its own steps.
 - notifier thread: when a saved finish time passes it notifies (Telegram on the phone + a log line the
   window turns into a desktop notification).
"""
import json, re, threading, time
from pathlib import Path

DIR = Path.home() / ".CoC_Bot" / "village"
CMD_DIR = Path.home() / ".CoC_Bot" / "commands"
SKIP_WORDS = ("suggested", "upgrad", "builder", "research", "other", "all", "boost", "ready", "info", "new")
TIME_RX = re.compile(r"(?:(\d+)\s*d)?\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?", re.I)


# ====================================================================== storage
def _safe(id):
    return "".join(c for c in str(id) if c.isalnum() or c in "-_") or "main"


def load(id):
    try: return json.loads((DIR / f"{_safe(id)}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {"items": [], "timers": [], "t": 0}


def save(id, data):
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{_safe(id)}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def parse_duration(text):
    """'2d 14h' / '5h 22m' / '45m 10s' / '30s' -> seconds (None when it is not a duration)."""
    t = (text or "").lower().replace(" ", "")
    if not re.search(r"\d+[dhms]", t): return None
    m = TIME_RX.fullmatch(t) or TIME_RX.search(t)
    if not m or not any(m.groups()): return None
    d, h, mi, s = (int(g) if g else 0 for g in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def parse_cost(text):
    digits = re.sub(r"[^0-9]", "", (text or "").replace("O", "0").replace("o", "0"))
    return int(digits) if len(digits) >= 2 else None


# ====================================================================== commands
def push_command(id, cmd, **kw):
    CMD_DIR.mkdir(parents=True, exist_ok=True)
    p = CMD_DIR / f"{_safe(id)}.json"
    try: queue = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): queue = []
    queue.append(dict(kw, cmd=cmd, t=time.time()))
    p.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
    return len(queue)


def pending(id):
    p = CMD_DIR / f"{_safe(id)}.json"
    try: return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    except (OSError, ValueError): return []


def take_commands(id, max_age=1800):
    p = CMD_DIR / f"{_safe(id)}.json"
    if not p.exists(): return []
    try: queue = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): queue = []
    try: p.unlink()
    except OSError: pass
    return [c for c in queue if time.time() - float(c.get("t", 0)) < max_age]


# ====================================================================== OCR scan (bot process)
def _rows(boxes, tol=0.022):
    rows = []
    for b in sorted(boxes, key=lambda b: (b[2] + b[4]) / 2):
        cy = (b[2] + b[4]) / 2
        if rows and abs(rows[-1]["cy"] - cy) < tol:
            rows[-1]["boxes"].append(b)
            rows[-1]["cy"] = (rows[-1]["cy"] + cy) / 2
        else:
            rows.append({"cy": cy, "boxes": [b]})
    return rows


def _resource_of(section):
    """Which resource icon sits next to the cost (gold yellow / elixir pink / dark purple-black)."""
    import numpy as np
    px = section.reshape(-1, 3).astype(int)
    r, g, b = px[:, 0], px[:, 1], px[:, 2]
    gold = int(((r > 200) & (g > 170) & (b < 110)).sum())
    elixir = int(((r > 190) & (g < 120) & (b > 170)).sum())
    dark = int(((r < 90) & (g < 80) & (b < 110) & (b > r)).sum())
    best = max((gold, "gold"), (elixir, "elixir"), (dark // 3, "dark"))
    return best[1] if best[0] > 15 else "gold"


def scan(upgrader, account):
    """Read the builder menu; returns the saved snapshot. Runs on the bot's thread (it taps the game)."""
    import utils
    from utils import Frame_Handler, Input_Handler, logger, ocr_boxes, spell_check
    data = load(account)
    items, timers, seen = [], [], set()
    try:
        try: data["builders_free"] = upgrader.get_home_builders(2)
        except Exception: pass
        try: data["lab_free"] = bool(upgrader.home_lab_available(2))
        except Exception: pass
        upgrader._click_build_button()
        time.sleep(0.6)
        upgrader._click_home_builders()
        time.sleep(0.8)
        frame = Frame_Handler.get_frame(grayscale=False)
        menu, ml, mt, mr, mb = upgrader._get_upgrade_menu(frame, return_bounds=True)
        last_sig = None
        for page in range(8):
            frame = Frame_Handler.get_frame(grayscale=False)
            crop = Frame_Handler.crop(frame, ml, mt, mr, mb)
            boxes = ocr_boxes(crop)
            sig = " ".join(b[0] for b in boxes)
            if sig == last_sig: break     # the list stopped moving: end reached
            last_sig = sig
            h, w = crop.shape[:2]
            for row in _rows(boxes):
                words = [b for b in row["boxes"] if re.search(r"[A-Za-z]{3,}", b[0])]
                nums = [b for b in row["boxes"] if re.search(r"\d", b[0])]
                label = " ".join(b[0] for b in sorted(words, key=lambda b: b[1])).strip()
                if not label or any(label.lower().startswith(sw) for sw in SKIP_WORDS): continue
                name = spell_check(re.sub(r"\s*x\d+$", "", label.lower()),
                                   ["buildings/home-village", "traps/home-village", "heroes", "guardians"], phrase_level=True) or label
                secs = next((parse_duration(b[0]) for b in nums if parse_duration(b[0])), None)
                if secs:
                    key = ("t", name)
                    if key in seen: continue
                    seen.add(key)
                    timers.append({"name": str(name).title(), "kind": "builder", "ends": time.time() + secs, "total": secs})
                    continue
                cost_box = max(nums, key=lambda b: len(re.sub(r"[^0-9]", "", b[0])), default=None)
                cost = parse_cost(cost_box[0]) if cost_box else None
                if cost is None: continue
                key = ("i", name, cost)
                if key in seen: continue
                seen.add(key)
                y1, y2 = int(max(0, row["cy"] - 0.025) * h), int(min(1, row["cy"] + 0.025) * h)
                section = crop[y1:y2, :]
                x2 = int(min(1, cost_box[3] + 0.08) * w)
                icon = crop[y1:y2, int(cost_box[3] * w):x2] if x2 > int(cost_box[3] * w) else section
                items.append({"name": str(name).title(), "cost": cost, "res": _resource_of(icon) if icon.size else "gold",
                              "available": bool(upgrader._get_sufficient_resources(section)),
                              "wall": "wall" in str(name).lower()})
            Input_Handler.swipe_up(x=(ml + mr) / 2, y1=mb - 0.05, y2=mt + 0.15, duration=300, hold_end_time=200)
            time.sleep(0.6)
        Input_Handler.click_exit(x=0.99, y=0.01, n=4, delay=0.1)   # close the builder menu
    except Exception:
        logger.exception("Village scan failed")
    # keep timers that were not visible this time but are still running (e.g. the lab)
    old = [t for t in data.get("timers", []) if t.get("ends", 0) > time.time() and t["name"] not in {x["name"] for x in timers}]
    data.update({"items": items or data.get("items", []), "timers": timers + old, "t": time.time()})
    save(account, data)
    logger.info(f"Village scanned: {len(items)} upgrades, {len(timers)} running")
    return data


# ====================================================================== notifier (bot process)
def check_timers(account, notify, stale=6 * 3600):
    """A saved finish time that passed -> log + notify once. Finished long ago (bot was off) -> marked silently."""
    from utils import logger
    data = load(account)
    changed, now = False, time.time()
    for t in data.get("timers", []):
        if t.get("done") or t.get("ends", 0) > now: continue
        t["done"] = True
        changed = True
        if now - t.get("ends", 0) > stale: continue
        kind = "Lab research" if t.get("kind") == "lab" else "Upgrade"
        logger.info(f"{kind} finished: {t['name']}")
        try:
            notify(("انتهى البحث في المعمل: " if t.get("kind") == "lab" else "اكتمل تطوير ") + t["name"]
                   + (" — المعمل جاهز لبحث جديد" if t.get("kind") == "lab" else " — عندك بنّاء فاضي دلوقتي"))
        except Exception: pass
    if changed: save(account, data)
    return changed


def start_notifier(account, notify):
    """Every 30 s: check_timers."""
    def loop():
        while True:
            time.sleep(30)
            try: check_timers(account, notify)
            except Exception: pass
    threading.Thread(target=loop, daemon=True, name="village-notifier").start()
