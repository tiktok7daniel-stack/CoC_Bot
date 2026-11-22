"""
The live screen's tracker (5.97): every unit the bot's eyes find, followed smoothly on every displayed picture.

  in       each look of the bot: everything both eye models found (unfiltered: name, ours / theirs, place, confidence)
           with the time its picture was TAKEN (royale.live_view "dets" / "seen_t")
  track    each detection joins the track of the same unit (same name and nearest; a nearby track of another name
           too when the eyes flicker between two names — its name is then voted by confidence); an alpha-beta filter
           keeps each unit's place and speed in the picture's own time
  show     on every picture (up to 240 a second) each track is drawn where its unit is NOW: its place moved by its
           speed for the time since that picture was taken — the bot's delay is made up, the box sits on its unit;
           a unit missed for a look or two keeps its box (coasting, 0.5 s) instead of blinking out

No second model runs in the app (in 5.96 it did: twice the heavy work, everything slower).
"""
import threading, time

BOX_W, BOX_H, BOX_UP = 0.057, 0.042, 0.011      # a unit's box in screen fractions (as royale.live_view draws them)


class Track:
    __slots__ = ("names", "mine", "x", "y", "vx", "vy", "t", "hits", "conf")

    def __init__(self, name, mine, x, y, t, conf):
        self.names, self.mine = {name: conf}, mine
        self.x, self.y, self.t, self.conf = x, y, t, conf
        self.vx = self.vy = 0.0
        self.hits = 1

    @property
    def name(self):
        return max(self.names, key=self.names.get)

    def at(self, now):
        # 6.9.17: also BEFORE its last look (the synced screen shows a picture up to ~0.4 s old): moved back on its speed
        k = max(-0.4, min(0.35, now - self.t))
        return self.x + self.vx * k, self.y + self.vy * k


class LiveTracker:
    A, B = 0.7, 0.3                       # alpha-beta: how much a new detection corrects the place / the speed
    COAST = 0.5                           # seconds a unit keeps its box without being seen

    def __init__(self, video=None):
        self.tracks = []
        self._lock = threading.Lock()
        self._last = 0.0
        self._seen = None
        self.rate, self._n, self._n_t = 0.0, 0, time.time()
        self.lat = None                    # 6.9.17: how old the bot's looks are when they arrive here (smoothed)

    # kept for the screen's calls (no model thread any more)
    def start(self): pass
    def stop(self): pass

    def active(self):
        return time.time() - self._last < 1.0

    def feed(self, dets, seen_t):
        """One look of the bot: [[name, ours, x, y, conf]] found in the picture taken at seen_t (wall clock)."""
        if not dets and dets != []: return
        t = float(seen_t or time.time())
        if t == self._seen: return
        self._seen = t
        lat = max(0.0, time.time() - t)
        self.lat = lat if self.lat is None else 0.8 * self.lat + 0.2 * lat
        with self._lock:
            free = list(self.tracks)
            for name, mine, x, y, conf in sorted(dets, key=lambda d: -d[4]):
                best, bd = None, 0.08
                for tr in free:
                    if tr.mine != mine: continue
                    px, py = tr.at(t)
                    d = abs(px - x) + abs(py - y)
                    if tr.name != name: d += 0.05            # another name: only when really close (a flicker)
                    if d < bd: best, bd = tr, d
                if best is None:
                    self.tracks.append(Track(name, mine, x, y, t, conf))
                    continue
                free.remove(best)
                dt = max(1e-3, t - best.t)
                px, py = best.x + best.vx * dt, best.y + best.vy * dt
                rx, ry = x - px, y - py
                best.x, best.y = px + self.A * rx, py + self.A * ry
                if dt < 0.6:
                    best.vx = max(-0.4, min(0.4, best.vx + self.B * rx / dt))
                    best.vy = max(-0.4, min(0.4, best.vy + self.B * ry / dt))
                best.t, best.conf = t, conf
                best.names[name] = best.names.get(name, 0.0) + conf
                best.hits += 1
            self.tracks = [tr for tr in self.tracks if t - tr.t <= self.COAST]
        self._last = time.time()
        self._n += 1
        if time.time() - self._n_t >= 1.0:
            self.rate, self._n, self._n_t = self._n / (time.time() - self._n_t), 0, time.time()

    def sync_delay(self):
        """How far behind real time the screen shows the game so the boxes sit on their units: the looks' age + 20 ms
        (0 = not synced: the looks are too old to wait for, > 0.45 s, or none come)."""
        if not self.active() or self.lat is None or self.lat > 0.45: return 0.0
        return self.lat + 0.02

    def visible(self, now=None):
        """[(name, ours, cx, cy, w, h)] screen fractions where each unit is now."""
        now = now or time.time()
        with self._lock:
            out = []
            for tr in self.tracks:
                if tr.conf < 0.3 and tr.hits < 2: continue
                x, y = tr.at(now)
                out.append((tr.name, tr.mine, x, y - BOX_UP, BOX_W, BOX_H))
            return out
