"""
Clash Farmer intro (about 3 s at 60 fps), painted with QPainter:
 1. a night battlefield fades in: deep blue storm sky with drifting clouds, a burning village skyline,
    flickering fires along the ground and embers rising through the air
 2. the crest drops in from above and SLAMS down (impact flash, shock ring, camera shake, burst of sparks)
 3. the 3D gold wordmark punches in under it, a light shine sweeps across the letters
 4. a chunky game-style loading bar fills; then everything fades out into the main window
"""
import math, random, time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QWidget

from .. import icons, logo, theme
from ..i18n import tr

DURATION = 3.0
W, H = 960, 600
T_SLAM = 0.95       # crest hits the ground
T_WORD = 1.25       # wordmark punches in
CY = 172            # crest center


def clamp(v, a=0.0, b=1.0):
    return max(a, min(b, v))


def ease_out_back(t, s=1.6):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in(t):
    t = clamp(t)
    return t * t * t


def ease_io(t):
    return 0.5 - 0.5 * math.cos(math.pi * clamp(t))


class Intro(QWidget):
    finished = Signal()

    def __init__(self, duration=DURATION):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.duration = duration
        self.status = tr("splash_loading")
        self.crest = icons.pixmap("crest", 180, dpr=2.0)
        self.word = logo.wordmark_pixmap(360, dpr=2.0, glow=0.6)
        rnd = random.Random(11)
        self.rnd = rnd
        # skyline: houses + towers of the burning village (x, width, height, roof)
        self.sky = []
        x = -20
        while x < W + 40:
            w = rnd.randint(40, 110)
            self.sky.append((x, w, rnd.randint(40, 120), rnd.random() < 0.6))
            x += w + rnd.randint(-10, 30)
        self.fires = [(rnd.uniform(40, W - 40), rnd.uniform(H - 130, H - 80), rnd.uniform(0.7, 1.6), rnd.uniform(0, 6)) for _ in range(9)]
        self.clouds = [(rnd.uniform(-200, W), rnd.uniform(-40, 220), rnd.uniform(160, 340), rnd.uniform(6, 22)) for _ in range(9)]
        self.embers = [self._ember(initial=True) for _ in range(120)]
        self.sparks = []
        self.t0 = None
        self.ready = False
        self.end_at = None
        self._done = False
        self._last = None
        self._slammed = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._frame)

    def _ember(self, initial=False):
        r = self.rnd
        fx, fy, _s, _p = r.choice(self.fires) if hasattr(self, "fires") else (W / 2, H - 100, 1, 0)
        return [fx + r.uniform(-30, 30), r.uniform(80, H) if initial else fy + r.uniform(-10, 10),
                r.uniform(-14, 14), r.uniform(-90, -35), r.uniform(1.2, 3.2), r.uniform(0, 6.28)]

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        geo = self.screen().availableGeometry() if self.screen() else None
        if geo: self.move(geo.center().x() - W // 2, geo.center().y() - H // 2)
        self.t0 = self._last = time.perf_counter()
        self.show()
        self.timer.start(16)

    def mark_ready(self):
        self.ready = True
        self.end_at = max(self.duration, self.elapsed() + 0.5)

    def set_status(self, text):
        self.status = text

    def elapsed(self):
        return 0.0 if self.t0 is None else time.perf_counter() - self.t0

    def _frame(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        t = self.elapsed()
        for e in self.embers:
            e[0] += (e[2] + 18 * math.sin(t * 1.3 + e[5])) * dt
            e[1] += e[3] * dt
            if e[1] < -10: e[:] = self._ember()
        if t >= T_SLAM and not self._slammed:
            self._slammed = True
            for _ in range(70):
                a = self.rnd.uniform(math.pi * 1.05, math.pi * 1.95)
                v = self.rnd.uniform(140, 520)
                self.sparks.append([W / 2, CY + 60, math.cos(a) * v, math.sin(a) * v, self.rnd.uniform(0.5, 1.1), 0.0])
        for s in self.sparks:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += 620 * dt
            s[5] += dt
        self.sparks = [s for s in self.sparks if s[5] < s[4]]
        if self.end_at is not None and t >= self.end_at and not self._done:
            self._done = True
            self.timer.stop()
            self.hide()
            self.finished.emit()
            return
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, e):
        t = self.elapsed()
        out = clamp((t - (self.end_at - 0.4)) / 0.4) if self.end_at else 0.0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(1 - ease_io(out))
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(0, 0, W, H).adjusted(1, 1, -1, -1), 22, 22)
        p.setClipPath(frame)
        shake = 0.0
        if T_SLAM <= t < T_SLAM + 0.35:
            k = 1 - (t - T_SLAM) / 0.35
            shake = 9 * k
        p.save()
        if shake:
            p.translate(math.sin(t * 90) * shake, math.cos(t * 77) * shake * 0.6)
        intro_fade = ease_io(t / 0.6)
        self._scene(p, t, intro_fade)
        self._crest(p, t)
        self._wordmark(p, t)
        p.restore()
        if T_SLAM <= t < T_SLAM + 0.25: # impact flash
            p.fillRect(QRectF(0, 0, W, H), QColor(255, 236, 190, int(140 * (1 - (t - T_SLAM) / 0.25))))
        self._bar(p, t)
        # vignette + frame
        v = QRadialGradient(W / 2, H / 2, W * 0.7)
        v.setColorAt(0.55, QColor(0, 0, 0, 0))
        v.setColorAt(1, QColor(0, 0, 0, 200))
        p.fillRect(QRectF(0, 0, W, H), v)
        p.setClipping(False)
        p.setPen(QPen(QColor(245, 183, 64, 90), 1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(frame)
        p.end()

    def _scene(self, p, t, fade):
        sky = QLinearGradient(0, 0, 0, H)
        sky.setColorAt(0, QColor(8, 16, 38))
        sky.setColorAt(0.55, QColor(18, 30, 58))
        sky.setColorAt(0.8, QColor(48, 26, 30))
        sky.setColorAt(1, QColor(10, 8, 10))
        p.fillRect(QRectF(-20, -20, W + 40, H + 40), sky)
        mg = QRadialGradient(W - 150, 95, 120)
        mg.setColorAt(0, QColor(200, 220, 255, 70))
        mg.setColorAt(1, QColor(200, 220, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(mg)
        p.drawEllipse(QPointF(W - 150, 95), 120, 120)
        moon = QRadialGradient(W - 160, 85, 34)
        moon.setColorAt(0, QColor(236, 242, 255))
        moon.setColorAt(1, QColor(170, 186, 220))
        p.setBrush(moon)
        p.drawEllipse(QPointF(W - 150, 95), 30, 30)
        # storm clouds drifting slowly
        for cx, cy, r, sp in self.clouds:
            x = (cx + t * sp) % (W + 400) - 200
            g = QRadialGradient(x, cy, r)
            g.setColorAt(0, QColor(36, 52, 86, 150))
            g.setColorAt(0.6, QColor(24, 36, 62, 80))
            g.setColorAt(1, QColor(20, 30, 50, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(x, cy), r * 1.6, r * 0.7)
        # glow of the fires on the horizon
        hz = QLinearGradient(0, H - 260, 0, H - 60)
        flick = 0.85 + 0.15 * math.sin(t * 9) * math.sin(t * 5.3)
        hz.setColorAt(0, QColor(255, 120, 30, 0))
        hz.setColorAt(1, QColor(255, 110, 30, int(110 * flick)))
        p.fillRect(QRectF(0, H - 260, W, 200), hz)
        # burning village skyline (silhouettes)
        base = H - 108
        p.setBrush(QColor(10, 9, 14))
        p.setPen(Qt.NoPen)
        for x, w, h, roof in self.sky:
            poly = QPolygonF([QPointF(x, base), QPointF(x, base - h), QPointF(x + w, base - h), QPointF(x + w, base)])
            p.drawPolygon(poly)
            if roof:
                p.drawPolygon(QPolygonF([QPointF(x - 8, base - h), QPointF(x + w / 2, base - h - w * 0.45), QPointF(x + w + 8, base - h)]))
            # a few lit windows
            if (x // 7) % 3 == 0:
                p.setBrush(QColor(255, 170, 60, int(120 + 80 * math.sin(t * 6 + x))))
                p.drawRect(QRectF(x + w * 0.3, base - h * 0.6, 6, 8))
                p.setBrush(QColor(10, 9, 14))
        ground = QLinearGradient(0, base, 0, H)
        ground.setColorAt(0, QColor(22, 14, 12))
        ground.setColorAt(1, QColor(6, 5, 6))
        p.fillRect(QRectF(0, base, W, H - base), ground)
        # fires
        for fx, fy, s, ph in self.fires:
            self._fire(p, fx, fy, s, t + ph)
        # embers
        for x, y, _vx, _vy, size, ph in self.embers:
            a = int(clamp((y / H) * 1.4) * 230 * (0.6 + 0.4 * math.sin(t * 8 + ph)))
            p.setBrush(QColor(255, 170 + int(60 * math.sin(ph)), 60, a))
            p.drawEllipse(QPointF(x, y), size, size)
        # fade the scene in from black
        if fade < 1: p.fillRect(QRectF(0, 0, W, H), QColor(0, 0, 0, int(255 * (1 - fade))))

    def _fire(self, p, x, y, s, t):
        p.setPen(Qt.NoPen)
        rad = 110 * s
        glow = QRadialGradient(x, y - 10 * s, rad)
        glow.setColorAt(0, QColor(255, 140, 40, 70))
        glow.setColorAt(0.45, QColor(255, 110, 30, 28))
        glow.setColorAt(1, QColor(255, 90, 20, 0))
        p.setBrush(glow)
        p.drawEllipse(QPointF(x, y - 10 * s), rad, rad)
        for i, (col, k) in enumerate(((QColor(255, 80, 20, 210), 1.0), (QColor(255, 160, 40, 230), 0.7), (QColor(255, 236, 160, 240), 0.38))):
            hgt = (46 + 14 * math.sin(t * 11 + i)) * s * k
            wid = 18 * s * k
            sway = 5 * math.sin(t * 7 + i * 1.7) * s
            path = QPainterPath(QPointF(x - wid, y))
            path.cubicTo(QPointF(x - wid, y - hgt * 0.5), QPointF(x + sway - wid * 0.3, y - hgt * 0.7), QPointF(x + sway, y - hgt))
            path.cubicTo(QPointF(x + sway + wid * 0.3, y - hgt * 0.7), QPointF(x + wid, y - hgt * 0.5), QPointF(x + wid, y))
            path.closeSubpath()
            p.setBrush(col)
            p.drawPath(path)

    def _crest(self, p, t):
        if t < 0.35: return
        k = clamp((t - 0.35) / (T_SLAM - 0.35))
        size = 170
        cx = W / 2
        if t < T_SLAM: # falling from above, growing slightly
            cy = -size + (CY + size) * ease_in(k)
            sc = 1.25 - 0.25 * ease_in(k)
        else:          # squash on impact, then settle and float
            dt = t - T_SLAM
            cy = CY + 4 * math.sin((t - T_SLAM) * 2.2) * clamp(dt / 0.6)
            squash = math.exp(-dt * 10) * math.cos(dt * 30) * 0.12
            sc = 1.0 + squash
        if t >= T_SLAM: # shock ring + halo
            dt = t - T_SLAM
            if dt < 0.6:
                r = 60 + 420 * ease_io(dt / 0.6)
                p.setPen(QPen(QColor(255, 214, 120, int(200 * (1 - dt / 0.6))), 3))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(cx, CY + 60), r, r * 0.42)
            halo = QRadialGradient(cx, CY, 200)
            halo.setColorAt(0, QColor(255, 190, 80, int(90 * clamp(dt * 3))))
            halo.setColorAt(1, QColor(255, 190, 80, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QPointF(cx, CY), 200, 200)
        for x, y, _vx, _vy, life, age in self.sparks:
            a = int(255 * (1 - age / life))
            p.setPen(QPen(QColor(255, 220, 140, a), 2.2, Qt.SolidLine, Qt.RoundCap))
            p.drawPoint(QPointF(x, y))
        p.save()
        p.translate(cx, cy)
        p.scale(sc * (1 + (0.06 if t >= T_SLAM and t < T_SLAM + 0.08 else 0)), sc * (1 - (0.08 if t >= T_SLAM and t < T_SLAM + 0.08 else 0)))
        p.drawPixmap(QRectF(-size / 2, -size / 2, size, size), self.crest, QRectF(self.crest.rect()))
        p.restore()

    def _wordmark(self, p, t):
        if t < T_WORD: return
        k = clamp((t - T_WORD) / 0.45)
        sc = 0.4 + 0.6 * ease_out_back(k, 2.2)
        pw = self.word.width() / self.word.devicePixelRatio()
        ph = self.word.height() / self.word.devicePixelRatio()
        p.save()
        p.setOpacity(p.opacity() * clamp(k * 3))
        p.translate(W / 2, 402)
        p.scale(sc, sc)
        word = self.word
        sh = (t - T_WORD - 0.35) / 0.9
        if 0 < sh < 2: # shine sweep across the letters only (painted onto a copy with SourceAtop)
            from PySide6.QtGui import QPixmap
            word = QPixmap(self.word)
            q = QPainter(word)
            q.setCompositionMode(QPainter.CompositionMode_SourceAtop)
            x = -80 + (pw + 160) * (sh % 1)
            g = QLinearGradient(x - 45, 0, x + 45, ph)
            g.setColorAt(0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 240, 190))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            q.fillRect(QRectF(0, 0, pw, ph), g)
            q.end()
        p.drawPixmap(QRectF(-pw / 2, -ph / 2, pw, ph), word, QRectF(word.rect()))
        p.restore()

    def _bar(self, p, t):
        if t < 0.3: return
        a = clamp((t - 0.3) / 0.4)
        prog = clamp(t / self.end_at) if self.end_at else min(0.9, t / self.duration)
        r = QRectF(W / 2 - 190, H - 56, 380, 14)
        p.save()
        p.setOpacity(p.opacity() * a)
        track = QPainterPath()
        track.addRoundedRect(r, 8, 8)
        p.fillPath(track, QColor(0, 0, 0, 170))
        p.setPen(QPen(QColor("#1A0D01"), 2))
        p.drawPath(track)
        inner = r.adjusted(3, 3, -3, -3)
        fill = QPainterPath()
        fill.addRoundedRect(QRectF(inner.left(), inner.top(), max(10.0, inner.width() * prog), inner.height()), 5, 5)
        g = QLinearGradient(0, inner.top(), 0, inner.bottom())
        g.setColorAt(0, QColor("#FFE58A"))
        g.setColorAt(0.5, QColor("#F5B740"))
        g.setColorAt(1, QColor("#C9821A"))
        p.fillPath(fill, g)
        p.setPen(QPen(QColor(245, 183, 64, 160), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(track)
        p.setPen(QColor(255, 240, 210, 200))
        p.setFont(theme.ui_font(9, 600))
        p.drawText(QRectF(0, H - 38, W, 24), Qt.AlignCenter, self.status)
        p.restore()
