"""
The live screen's own eyes and tracker (5.96): the boxes are found on the very pictures the screen shows, not taken
from the bot (whose answer was 100-200 ms old — the box arrived late, then caught up with its unit).

  detect   the big arena model (royale.strong_eyes, on the graphics card when DirectML is set up) runs on its own
           thread on the newest decoded picture, as often as it can (a graphics card: dozens of times a second)
  track    every detection joins the track of the same unit (same name, nearest); an alpha-beta filter keeps each
           unit's place and speed, measured with the picture's own time
  show     on every displayed picture (up to 240 a second) each track is drawn where its unit is NOW: its filtered
           place moved by its speed for the time since that picture — the box sits on its unit and moves with it
  side     ours / theirs from the bot's boxes (its side model), the nearest one of the same name; theirs by default
"""
import threading, time


class Track:
    __slots__ = ("name", "x", "y", "w", "h", "vx", "vy", "t", "hits", "miss", "conf", "mine")

    def __init__(self, name, x, y, w, h, t, conf):
        self.name, self.x, self.y, self.w, self.h, self.t, self.conf = name, x, y, w, h, t, conf
        self.vx = self.vy = 0.0
        self.hits, self.miss, self.mine = 1, 0, False

    def at(self, now):
        k = max(0.0, min(0.3, now - self.t))
        return self.x + self.vx * k, self.y + self.vy * k


class LiveTracker:
    A, B = 0.65, 0.25                   # alpha-beta filter: how much a new detection corrects place / speed

    def __init__(self, video):
        self.video = video
        self.tracks = []
        self.rate = 0.0
        self.ms = 0.0
        self.ok = False
        self.error = ""
        self._want = False
        self._thread = None
        self._lock = threading.Lock()
        self.bot_boxes = []             # the bot's last boxes (for ours / theirs)

    def start(self):
        self._want = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="live-tracker")
            self._thread.start()

    def stop(self):
        self._want = False

    def active(self):
        return self.ok and time.monotonic() - getattr(self, "_last", 0) < 0.6

    def visible(self, now=None):
        """[(name, mine, cx, cy, w, h)] screen fractions where each unit is now."""
        now = now or time.monotonic()
        with self._lock:
            out = []
            for t in self.tracks:
                if t.hits < 2 and t.conf < 0.6: continue              # one look and unsure: not shown yet
                x, y = t.at(now)
                out.append((t.name, t.mine, x, y, t.w, t.h))
            return out

    def _side(self, name, x, y):
        best, bd = False, 0.12
        for b in self.bot_boxes:
            if b.get("n") != name: continue
            x0, y0, x1, y1 = b["b"]
            d = abs((x0 + x1) / 2 - x) + abs((y0 + y1) / 2 - y)
            if d < bd: best, bd = bool(b.get("m")), d
        return best

    def _update(self, dets, t):
        with self._lock:
            free = list(self.tracks)
            for name, conf, x, y, w, h in sorted(dets, key=lambda d: -d[1]):
                best, bd = None, 0.09
                for tr in free:
                    if tr.name != name: continue
                    px, py = tr.at(t)
                    d = abs(px - x) + abs(py - y)
                    if d < bd: best, bd = tr, d
                if best is None:
                    nt = Track(name, x, y, w, h, t, conf)
                    nt.mine = self._side(name, x, y)
                    self.tracks.append(nt)
                    continue
                free.remove(best)
                dt = max(1e-3, t - best.t)
                px, py = best.x + best.vx * dt, best.y + best.vy * dt
                rx, ry = x - px, y - py
                best.x, best.y = px + self.A * rx, py + self.A * ry
                best.vx = max(-0.5, min(0.5, best.vx + self.B * rx / dt))
                best.vy = max(-0.5, min(0.5, best.vy + self.B * ry / dt))
                best.w, best.h = 0.7 * best.w + 0.3 * w, 0.7 * best.h + 0.3 * h
                best.t, best.conf, best.miss = t, max(conf, 0.8 * best.conf), 0
                best.hits += 1
                if best.hits % 10 == 2: best.mine = self._side(name, best.x, best.y)
            for tr in free:
                tr.miss += 1
            self.tracks = [tr for tr in self.tracks if tr.miss <= 3 and t - tr.t < 0.6]

    def _run(self):
        try:
            from royale import strong_eyes as se
            if se._S.get("sess") is None and se.ONNX.exists(): se._load()
            self.ok = se._S.get("sess") is not None
        except Exception as e:
            self.error, self.ok = f"{type(e).__name__}: {e}"[:120], False
        if not self.ok: return
        last, n, t0 = 0, 0, time.monotonic()
        while self._want:
            fr = self.video.latest_array()
            if fr is None or fr[0] == last:
                time.sleep(0.002)
                continue
            last, arr, ft = fr
            h, w = arr.shape[:2]
            tc = time.perf_counter()
            try:
                raw = se.detect(arr, conf=0.4)
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"[:120]
                time.sleep(0.05)
                continue
            self.ms = 0.8 * self.ms + 0.2 * (time.perf_counter() - tc) * 1000
            dets = []
            for name, conf, x0, y0, x1, y1 in raw:
                u = se.unit_name(name)
                if not u: continue
                dets.append((u, conf, (x0 + x1) / 2 / w, (y0 + y1) / 2 / h, (x1 - x0) / w, (y1 - y0) / h))
            self._update(dets, ft)
            self._last = time.monotonic()
            n += 1
            if time.monotonic() - t0 >= 1.0:
                self.rate, n, t0 = n / (time.monotonic() - t0), 0, time.monotonic()
