"""
The live screen's tracker: consume the bot's detections when available, and run the local arena detector on the live
video when the bot telemetry is stale or has no tracked units. This keeps the YOLO overlay useful while inspecting a
manual match or a stalled bot, without duplicating inference during normal tracked play.

  in       each look of the bot: everything both eye models found (unfiltered: name, ours / theirs, place, confidence)
           with the time its picture was TAKEN (royale.live_view "dets" / "seen_t")
  track    each detection joins the track of the same unit (same name and nearest; a nearby track of another name
           too when the eyes flicker between two names — its name is then voted by confidence); an alpha-beta filter
           keeps each unit's place and speed in the picture's own time
  show     on every picture (up to 240 a second) each track is drawn where its unit is NOW: its place moved by its
           speed for the time since that picture was taken — the bot's delay is made up, the box sits on its unit;
           a unit missed for a look or two keeps its box (coasting, 0.5 s) instead of blinking out

"""
import threading, time

BOX_W, BOX_H, BOX_UP = 0.057, 0.042, 0.011      # a unit's box in screen fractions (as royale.live_view draws them)


class Track:
    __slots__ = ("names", "mine", "x", "y", "vx", "vy", "t", "hits", "conf", "size")

    def __init__(self, name, mine, x, y, t, conf, size=None):
        self.names, self.mine = {name: conf}, mine
        self.x, self.y, self.t, self.conf = x, y, t, conf
        self.vx = self.vy = 0.0
        self.hits = 1
        self.size = size

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
        self.video = video
        self.tracks = []
        self._lock = threading.Lock()
        self._last = 0.0
        self._bot_empty_since = None
        self._seen = None
        self.rate, self._n, self._n_t = 0.0, 0, time.time()
        self.lat = None                    # 6.9.17: how old the bot's looks are when they arrive here (smoothed)
        self.local_boxes = []
        self.local_state = "waiting"
        self.local_fps = 0.0
        self.local_ms = 0.0
        self._local_t = 0.0
        self._want = False
        self._worker = None

    def start(self):
        self._want = True
        if self.video is not None and (self._worker is None or not self._worker.is_alive()):
            self._worker = threading.Thread(target=self._vision_loop, daemon=True, name="royale-live-vision")
            self._worker.start()

    def stop(self):
        self._want = False

    def _vision_loop(self):
        """Latest-frame-only fallback; it yields to bot detections and never queues stale screenshots."""
        seq = -1
        last_infer = 0.0
        while self._want:
            now = time.monotonic()
            bot_active = self.active()
            has_tracks = bool(self.visible())
            if bot_active and has_tracks:
                self.local_boxes = []
                self.local_state = "bot"
                time.sleep(0.12)
                continue
            if bot_active and self._bot_empty_since is not None and now - self._bot_empty_since < 0.8:
                self.local_state = "bot_empty"
                time.sleep(0.08)
                continue
            interval = 0.40 if bot_active else 0.20  # low-rate assist if the bot is reporting no units
            if now - last_infer < interval:
                time.sleep(0.02)
                continue
            sample = self.video.latest_array() if self.video is not None else None
            if not sample or now - sample[2] > 0.5:
                self.local_state = "waiting"
                time.sleep(0.08)
                continue
            frame_seq, frame, _decoded_t = sample
            if frame_seq == seq:
                time.sleep(0.025)
                continue
            seq, last_infer = frame_seq, now
            try:
                from royale import strong_eyes
                if not strong_eyes.ready():
                    self.local_state = "loading"
                    strong_eyes.ensure()
                    time.sleep(0.1)
                    continue
                t0 = time.perf_counter()
                detections = strong_eyes.detect(frame, conf=0.35)
                self.local_ms = (time.perf_counter() - t0) * 1000
                h, w = frame.shape[:2]
                boxes = []
                for name, conf, x0, y0, x1, y1 in detections:
                    unit = strong_eyes.unit_name(name)
                    if not unit or conf < 0.35:
                        continue
                    boxes.append({"n": unit, "c": round(float(conf), 2),
                                  "b": [max(0.0, x0 / w), max(0.0, y0 / h),
                                        min(1.0, x1 / w), min(1.0, y1 / h)]})
                self.local_boxes = boxes[:50]
                self.local_state = "ready"
                self._local_t = time.time()
                self.local_fps = 1.0 / max(0.001, interval + self.local_ms / 1000.0)
            except Exception as e:
                self.local_state = "error"
                self.local_boxes = []
                self.local_error = f"{type(e).__name__}: {e}"[:160]
                time.sleep(0.5)

    def active(self):
        return time.time() - self._last < 1.0

    def feed(self, dets, seen_t):
        """One look of the bot: [[name, ours, x, y, conf]] found in the picture taken at seen_t (wall clock)."""
        if not dets and dets != []: return
        t = float(seen_t or time.time())
        if t == self._seen: return
        self._seen = t
        if dets:
            self._bot_empty_since = None
        elif self._bot_empty_since is None:
            self._bot_empty_since = time.monotonic()
        lat = max(0.0, time.time() - t)
        self.lat = lat if self.lat is None else 0.8 * self.lat + 0.2 * lat
        with self._lock:
            free = list(self.tracks)
            for detection in sorted(dets, key=lambda d: -d[4]):
                name, mine, x, y, conf = detection[:5]
                size = tuple(detection[5:7]) if len(detection) >= 7 else None
                best, bd = None, 0.08
                for tr in free:
                    if tr.mine != mine: continue
                    px, py = tr.at(t)
                    d = abs(px - x) + abs(py - y)
                    if tr.name != name: d += 0.05            # another name: only when really close (a flicker)
                    if d < bd: best, bd = tr, d
                if best is None:
                    self.tracks.append(Track(name, mine, x, y, t, conf, size))
                    continue
                free.remove(best)
                dt = max(1e-3, t - best.t)
                px, py = best.x + best.vx * dt, best.y + best.vy * dt
                rx, ry = x - px, y - py
                best.x, best.y = px + self.A * rx, py + self.A * ry
                if dt < 0.6:
                    best.vx = max(-0.4, min(0.4, best.vx + self.B * rx / dt))
                    best.vy = max(-0.4, min(0.4, best.vy + self.B * ry / dt))
                best.t, best.conf, best.size = t, conf, size
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
                w, h = tr.size or (BOX_W, BOX_H)
                out.append((tr.name, tr.mine, x, y if tr.size else y - BOX_UP, w, h))
            return out

    def visible_rich(self, now=None):
        """Detailed visible tracks with velocities so AiPicture interpolates smoothly and preserves HP bars."""
        now = now or time.time()
        with self._lock:
            out = []
            for tr in self.tracks:
                if tr.conf < 0.3 and tr.hits < 2: continue
                x, y = tr.at(now)
                w, h = tr.size or (BOX_W, BOX_H)
                out.append({"n": tr.name, "m": tr.mine, "l": 1.0, "cx": x, "cy": y if tr.size else y - BOX_UP,
                            "w": w, "h": h, "vx": tr.vx, "vy": tr.vy, "t": now})
            return out
