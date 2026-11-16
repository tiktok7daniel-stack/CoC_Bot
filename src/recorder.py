"""
Battle recording & replay.

Recording: while the user attacks by hand, the emulator's raw touch events are read with
`adb shell getevent -lt <touch device>` and stored as finger downs / moves / ups with their
time since the recording started (positions as fractions of the touch device range).
Replay: the same fingers are sent back through minitouch at the same times.
Recordings live in ~/.CoC_Bot/recordings/<name>.json (local, per user).
"""
import bisect, collections, json, re, time, subprocess, threading
from pathlib import Path

# every touch the bot itself sends (time.monotonic()): touches seen on the screen that are not in here are yours
BOT_TOUCHES = collections.deque(maxlen=50000)

def bot_touched():
    BOT_TOUCHES.append(time.monotonic())

REC_DIR = Path.home() / ".CoC_Bot" / "recordings"
REQ_DIR = Path.home() / ".CoC_Bot" / "record_requests"

def _safe(name):
    return "".join(c for c in str(name) if c.isalnum() or c in "-_ ")[:40].strip() or "battle"

def list_recordings():
    out = []
    for p in sorted(REC_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name", p.stem), "created": d.get("created"), "duration": d.get("duration"),
                        "touches": sum(1 for e in d.get("events", []) if e["type"] == "down")})
        except (OSError, ValueError):
            continue
    return out

def load(name):
    p = REC_DIR / f"{_safe(name)}.json"
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return None

def delete(name):
    try: (REC_DIR / f"{_safe(name)}.json").unlink()
    except OSError: pass

def request(id, name):
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DIR / f"{id}.json").write_text(json.dumps({"name": name, "t": time.time()}), encoding="utf-8")

def pending(id):
    return (REQ_DIR / f"{id}.json").exists()

def take_request(id, max_age=600):
    """The waiting "record a battle" request (requests older than 10 minutes are dropped)."""
    p = REQ_DIR / f"{id}.json"
    if not p.exists(): return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = None
    try: p.unlink()
    except OSError: pass
    if d and time.time() - float(d.get("t", 0)) > max_age: return None
    return d

def set_status(id, text):
    """What the recording is doing now (shown on the loadouts page)."""
    REQ_DIR.mkdir(parents=True, exist_ok=True)
    (REQ_DIR / f"{id}.status").write_text(json.dumps({"text": text, "t": time.time()}), encoding="utf-8")

def get_status(id):
    try: return json.loads((REQ_DIR / f"{id}.status").read_text(encoding="utf-8"))
    except (OSError, ValueError): return None

# ---------------------------------------------------------------- touch device discovery

def find_touch_device(shell):
    """-> (device path, max_x, max_y) of the multi-touch input device."""
    out = shell("getevent -pl")
    dev, best = None, None
    cur, maxx, maxy = None, None, None
    for line in out.splitlines():
        m = re.match(r"add device \d+: (\S+)", line.strip())
        if m:
            if cur and maxx and maxy and best is None: best = (cur, maxx, maxy)
            cur, maxx, maxy = m.group(1), None, None
            continue
        mx = re.search(r"ABS_MT_POSITION_X\s*:.*max (\d+)", line)
        my = re.search(r"ABS_MT_POSITION_Y\s*:.*max (\d+)", line)
        if mx: maxx = int(mx.group(1))
        if my: maxy = int(my.group(1))
    if cur and maxx and maxy and best is None: best = (cur, maxx, maxy)
    return best

# ---------------------------------------------------------------- recording

class Recorder:
    """Reads getevent from a subprocess and turns it into finger events."""

    def __init__(self, adb_exe, serial, device, max_x, max_y):
        self.cmd = [adb_exe, "-s", serial, "shell", "getevent", "-lt", device]
        self.max_x, self.max_y = max_x, max_y
        self.events, self.proc, self.t0 = [], None, None
        self.slot = 0
        self.slots = {}   # slot -> {"active", "x", "y", "dirty", "new"}
        self.ts0 = self.ts = None  # kernel timestamps of the touch events (exact timing even if adb output is buffered)

    def start(self):
        kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if hasattr(subprocess, "CREATE_NO_WINDOW") else {}
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1, **kw)
        self.t0 = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()

    def stop(self):
        try: self.proc.terminate()
        except Exception: pass

    def _emit(self, type, slot, s):
        t = round(self.ts - self.ts0, 3) if self.ts is not None else round(time.monotonic() - self.t0, 3)
        e = {"t": t, "type": type, "id": slot, "k": self.ts, "m": time.monotonic()}
        if type != "up": e.update(fx=round(s["x"] / self.max_x, 5), fy=round(s["y"] / self.max_y, 5))
        if type == "move" and self.events and self.events[-1]["type"] == "move" and self.events[-1]["id"] == slot \
                and t - self.events[-1]["t"] < 0.04:
            self.events[-1] = e # thin out moves (max ~25 per second per finger)
        else:
            self.events.append(e)

    def _read(self):
        for line in self.proc.stdout:
            parts = line.split()
            if len(parts) < 3: continue
            code, val = parts[-2], parts[-1]
            m = re.match(r"\[\s*([\d.]+)\]", line.strip())
            if m:
                self.ts = float(m.group(1))
                if self.ts0 is None: self.ts0 = self.ts
            if code == "ABS_MT_SLOT":
                self.slot = int(val, 16)
            elif code == "ABS_MT_TRACKING_ID":
                s = self.slots.setdefault(self.slot, {"active": False, "x": 0, "y": 0, "dirty": False, "new": False})
                if val.lower() == "ffffffff":
                    if s["active"]: self._emit("up", self.slot, s)
                    s["active"] = False
                else:
                    s["active"], s["new"] = True, True
            elif code in ("ABS_MT_POSITION_X", "ABS_MT_POSITION_Y"):
                s = self.slots.setdefault(self.slot, {"active": True, "x": 0, "y": 0, "dirty": False, "new": True})
                s["x" if code.endswith("X") else "y"] = int(val, 16)
                s["dirty"] = True
            elif code == "SYN_REPORT":
                for sl, s in self.slots.items():
                    if s["active"] and s["new"]:
                        self._emit("down", sl, s); s["new"] = s["dirty"] = False
                    elif s["active"] and s["dirty"]:
                        self._emit("move", sl, s); s["dirty"] = False

    def save(self, name):
        REC_DIR.mkdir(parents=True, exist_ok=True)
        events = [{k: v for k, v in e.items() if k not in ("k", "m")} for e in self.events]
        data = {"name": name, "created": time.time(), "duration": events[-1]["t"] if events else 0,
                "max": [self.max_x, self.max_y], "events": events}
        (REC_DIR / f"{_safe(name)}.json").write_text(json.dumps(data), encoding="utf-8")
        return data

# ---------------------------------------------------------------- replay

def replay(data, connection, should_stop=lambda: False):
    """Send the recorded fingers through a minitouch connection at the recorded times."""
    from pyminitouch import CommandBuilder
    mx, my = int(connection.max_x), int(connection.max_y)
    start = time.monotonic()
    taps, checked = 0, 0.0
    for e in data.get("events", []):
        if time.monotonic() - checked > 2: # should_stop may be slow (asks the GUI)
            checked = time.monotonic()
            if should_stop(): break
        wait = e["t"] - (time.monotonic() - start)
        if wait > 0: time.sleep(wait)
        b = CommandBuilder()
        cid = int(e["id"]) % 10
        if e["type"] == "down":
            b.down(cid, int(e["fx"] * mx), int(e["fy"] * my), 100); taps += 1
        elif e["type"] == "move":
            b.move(cid, int(e["fx"] * mx), int(e["fy"] * my), 100)
        else:
            b.up(cid)
        b.commit()
        bot_touched()
        connection.send(b._content)
    # release every finger in case the recording ended mid-touch
    b = CommandBuilder()
    for cid in range(10): b.up(cid)
    b.commit()
    try: connection.send(b._content)
    except Exception: pass
    return taps


# ---------------------------------------------------------------- your own taps on top of a replay
def user_strokes(events, since=None, until=None, tol=0.3):
    """
    The fingers (down .. up) seen on the screen that the bot did not send itself: yours.
    events: Recorder events (with "k" kernel time and "m" arrival time). since / until: time.monotonic() limits.
    """
    if not events: return []
    ks = [e for e in events if e.get("k") is not None]
    off = min(e["m"] - e["k"] for e in ks) if ks else 0.0       # kernel clock -> monotonic (the fastest arrival)
    est = lambda e: e["k"] + off if e.get("k") is not None else e["m"]
    bot = sorted(BOT_TOUCHES)
    strokes, cur = [], {}
    for e in events:
        sid = e["id"]
        if e["type"] == "down": cur[sid] = [e]
        elif sid in cur:
            cur[sid].append(e)
            if e["type"] == "up": strokes.append(cur.pop(sid))
    strokes += list(cur.values())
    out = []
    for st in strokes:
        t = est(st[0])
        if since is not None and t < since: continue
        if until is not None and t > until: continue
        i = bisect.bisect_left(bot, t - tol)
        if i < len(bot) and bot[i] <= t + tol: continue          # the bot's own touch
        out.append([dict(e, est=est(e)) for e in st])
    return out


def merge_user_part(name, strokes, t0):
    """Add your taps (seen while the recording was replayed) to the recording, at the time you made them."""
    data = load(name)
    if not data or not strokes: return 0
    new = []
    for st in strokes:
        for e in st:
            n = {"t": round(max(0.0, e["est"] - t0), 3), "type": e["type"], "id": int(e["id"]) % 5 + 5}
            if e["type"] != "up": n.update(fx=e["fx"], fy=e["fy"])
            new.append(n)
    downs = sum(1 for n in new if n["type"] == "down")
    if not downs: return 0
    ev = sorted(data.get("events", []) + new, key=lambda e: e["t"])
    data["events"] = ev
    data["duration"] = ev[-1]["t"]
    data.setdefault("merged", []).append({"t": time.time(), "taps": downs})
    REC_DIR.mkdir(parents=True, exist_ok=True)
    (REC_DIR / f"{_safe(data.get('name', name))}.json").write_text(json.dumps(data), encoding="utf-8")
    return downs
