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
from collections import deque
from itertools import count
import math, threading, time

BOX_W, BOX_H, BOX_UP = 0.057, 0.042, 0.011      # a unit's box in screen fractions (as royale.live_view draws them)


class Track:
    __slots__ = ("names", "mine", "x", "y", "vx", "vy", "t", "hits", "conf", "size", "id", "origin", "trail", "life")

    def __init__(self, name, mine, x, y, t, conf, size=None, track_id=0):
        self.names, self.mine = {name: conf}, mine
        self.x, self.y, self.t, self.conf = x, y, t, conf
        self.vx = self.vy = 0.0
        self.hits = 1
        self.size = size
        self.id = track_id
        self.life = 1.0
        self.origin = (x, y)
        self.trail = deque([(x, y)], maxlen=8)

    @property
    def name(self):
        return max(self.names, key=self.names.get)

    def at(self, now):
        # 6.9.17: also BEFORE its last look (the synced screen shows a picture up to ~0.4 s old): moved back on its speed
        k = max(-0.4, min(0.35, now - self.t))
        return self.x + self.vx * k, self.y + self.vy * k


class LiveTracker:
    A, B = 0.7, 0.3                       # alpha-beta: how much a new detection corrects the place / the speed
    COAST = 0.55
    HIGH = 0.35
    LOW = 0.22

    def __init__(self, video=None):
        self.video = video
        self.tracks = []
        self._ids = count(1)
        self.local_tracker = LiveTracker() if video is not None else None
        self._lock = threading.Lock()
        self._last = 0.0
        self._bot_empty_since = None
        self._seen = None
        self._authoritative = False
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
        from royale.team_color import TeamColor
        colors = TeamColor()
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
            if bot_active and self._bot_empty_since is not None and now - self._bot_empty_since < 0.25:
                self.local_state = "bot_empty"
                time.sleep(0.08)
                continue
            interval = max(0.18 if bot_active else 1 / 15, self.local_ms / 1000 * (2.5 if bot_active else 1.8))
            if now - last_infer < interval:
                time.sleep(min(0.015, interval - (now - last_infer)))
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
                    if not strong_eyes.ensure():
                        time.sleep(0.1)
                        continue
                t0 = time.perf_counter()
                detections = strong_eyes.detect(frame, conf=self.LOW)
                h, w = frame.shape[:2]
                colors.prepare(frame)
                boxes, found = [], []
                for name, conf, x0, y0, x1, y1 in detections:
                    unit = strong_eyes.unit_name(name)
                    if not unit:
                        continue
                    team, confidence = colors.team((x0, y0, x1, y1))
                    mine = (team == "ally") if team and confidence >= 2.0 else None
                    b = [max(0.0, x0 / w), max(0.0, y0 / h), min(1.0, x1 / w), min(1.0, y1 / h)]
                    a, b0, c, d = b
                    if a >= c or b0 >= d:
                        continue
                    if conf >= self.HIGH:
                        boxes.append({"n": unit, "c": float(conf), "b": b})
                    found.append([unit, mine, (a + c) / 2, (b0 + d) / 2, float(conf), c - a, d - b0])
                captured_at = time.time() - max(0.0, time.monotonic() - _decoded_t)
                self.local_tracker.feed(found[:50], captured_at)
                self.local_boxes = boxes[:50]
                self.local_state = "ready"
                self._local_t = time.time()
                cost_ms = (time.perf_counter() - t0) * 1000
                self.local_ms = cost_ms if not self.local_ms else 0.8 * self.local_ms + 0.2 * cost_ms
                self.local_fps = self.local_tracker.rate
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
        if self._seen is not None and t <= self._seen:
            return
        self._seen = t
        if dets:
            self._bot_empty_since = None
        elif self._bot_empty_since is None:
            self._bot_empty_since = time.monotonic()
        lat = max(0.0, time.time() - t)
        self.lat = lat if self.lat is None else 0.8 * self.lat + 0.2 * lat
        with self._lock:
            authoritative = all(len(d) >= 8 for d in dets) if dets else self._authoritative
            if authoritative != self._authoritative or time.time() - self._last > 1.0:
                self.tracks.clear()
            self._authoritative = authoritative
            free = [tr for tr in self.tracks if 0 < t - tr.t <= self.COAST]
            if authoritative:
                known = {tr.id: tr for tr in free}
                matches = [(known[d[7]], d) for d in dets if d[7] in known]
                new = [d for d in dets if d[7] not in known]
                recovery = []
                replaced = {d[7] for d in new}
                self.tracks = [tr for tr in self.tracks if tr.id not in replaced]
            else:
                strong = [d for d in dets if d[4] >= self.HIGH]
                weak = [d for d in dets if self.LOW <= d[4] < self.HIGH]
                matches, new, free = self._match(free, strong, t)
                recovery, _, _ = self._match(free, weak, t, weak=True)
            for detection in new:
                name, mine, x, y, conf = detection[:5]
                size = tuple(detection[5:7]) if len(detection) >= 7 else None
                track = Track(name, mine, x, y, t, conf, size, detection[7] if authoritative else next(self._ids))
                if authoritative:
                    track.life = detection[8] if len(detection) >= 9 else 1.0
                self.tracks.append(track)
            for best, detection in matches + recovery:
                name, mine, x, y, conf = detection[:5]
                size = tuple(detection[5:7]) if len(detection) >= 7 else None
                dt = max(1e-3, t - best.t)
                px, py = best.x + best.vx * dt, best.y + best.vy * dt
                rx, ry = x - px, y - py
                best.x, best.y = px + self.A * rx, py + self.A * ry
                if dt < 0.6:
                    best.vx = max(-0.4, min(0.4, best.vx + self.B * rx / dt))
                    best.vy = max(-0.4, min(0.4, best.vy + self.B * ry / dt))
                best.t = t
                best.conf = max(conf, best.conf * 0.85)
                if size is not None:
                    best.size = tuple(0.7 * v + 0.3 * old for v, old in zip(size, best.size or size))
                if authoritative or best.mine is None:
                    best.mine = mine
                if math.hypot(best.trail[-1][0] - best.x, best.trail[-1][1] - best.y) > 0.002:
                    best.trail.append((best.x, best.y))
                if authoritative:
                    best.names = {name: conf}
                    best.life = detection[8] if len(detection) >= 9 else 1.0
                else:
                    best.names[name] = best.names.get(name, 0.0) + conf
                best.hits += 1
            self.tracks = [tr for tr in self.tracks if t - tr.t <= self.COAST]
        self._last = time.time()
        self._n += 1
        if time.time() - self._n_t >= 1.0:
            self.rate, self._n, self._n_t = self._n / (time.time() - self._n_t), 0, time.time()

    @staticmethod
    def _match(tracks, detections, t, weak=False):
        if not tracks or not detections:
            return [], detections, tracks
        from scipy.optimize import linear_sum_assignment
        costs = []
        for tr in tracks:
            px, py = tr.at(t)
            gate = min(0.075, 0.025 + 0.13 * (t - tr.t))
            row = []
            for d in detections:
                name, team, x, y = d[:4]
                distance = math.hypot(px - x, py - y)
                wrong_side = team is not None and tr.mine is not None and team != tr.mine
                different_name = name != tr.name
                if wrong_side or distance > gate or (different_name and (weak or distance > 0.022)):
                    row.append(1e3)
                    continue
                overlap = 0.0
                if tr.size and len(d) >= 7:
                    tw, th = tr.size
                    w, h = d[5:7]
                    iw = max(0.0, min(px + tw / 2, x + w / 2) - max(px - tw / 2, x - w / 2))
                    ih = max(0.0, min(py + th / 2, y + h / 2) - max(py - th / 2, y - h / 2))
                    overlap = iw * ih / max(1e-6, tw * th + w * h - iw * ih)
                row.append(distance + (0.012 if different_name else 0.0) + 0.012 * (1 - overlap))
            costs.append(row)
        rows, cols = linear_sum_assignment(costs)
        pairs = [(i, j) for i, j in zip(rows, cols) if costs[i][j] < 1e3]
        used_tracks = {i for i, _ in pairs}
        used_dets = {j for _, j in pairs}
        return ([(tracks[i], detections[j]) for i, j in pairs],
                [d for j, d in enumerate(detections) if j not in used_dets],
                [tr for i, tr in enumerate(tracks) if i not in used_tracks])

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
                if now - tr.t > self.COAST or (tr.conf < 0.3 and tr.hits < 2): continue
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
                if now - tr.t > self.COAST or (tr.conf < 0.3 and tr.hits < 2): continue
                x, y = tr.at(now)
                w, h = tr.size or (BOX_W, BOX_H)
                out.append({"id": tr.id, "n": tr.name, "m": tr.mine, "l": tr.life, "c": tr.conf,
                            "cx": x, "cy": y if tr.size else y - BOX_UP, "w": w, "h": h,
                            "vx": tr.vx, "vy": tr.vy, "t": now, "origin": tr.origin, "trail": tuple(tr.trail)})
            return out
