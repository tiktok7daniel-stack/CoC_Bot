"""
Clash Farmer 3D intro (2.8 s, ~60 fps), painted with QPainter only (no OpenGL needed):
 - a field of 3D crystal particles flying toward the camera (perspective projection = parallax depth)
 - the crest swings in around the Y axis with a real perspective transform, then floats and sways
 - "CLASH FARMER" in metallic gold with a light shimmer sweeping across it
 - a glass loading bar, then the whole intro fades and scales out into the main window
"""
import math, random, time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from .. import icons, theme
from ..i18n import tr

DURATION = 2.8
W, H = 680, 420


def ease_out_back(t, s=1.4):
    t -= 1
    return t * t * ((s + 1) * t + s) + 1


def ease_in_out(t):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


class Intro(QWidget):
    finished = Signal()

    def __init__(self, duration=DURATION):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.duration = duration
        self.status = tr("splash_loading")
        self.crest = icons.pixmap("crest", 150, dpr=2.0)
        rnd = random.Random(7)
        self.parts = [[rnd.uniform(-1, 1), rnd.uniform(-1, 1), rnd.uniform(0.15, 1.0), rnd.random() < 0.55,
                       rnd.uniform(0, math.tau)] for _ in range(90)]
        self.t0 = None
        self.ready = False            # set when the main window is built; the intro never ends before that
        self.end_at = None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._frame)
        self._last = None
        self._done = False

    def start(self):
        geo = self.screen().availableGeometry() if self.screen() else None
        if geo: self.move(geo.center().x() - W // 2, geo.center().y() - H // 2)
        self.t0 = time.perf_counter()
        self._last = self.t0
        self.show()
        self.timer.start(16)

    def mark_ready(self):
        """The main window is built: finish at the planned 2.8 s, or with a short fade if it took longer."""
        self.ready = True
        self.end_at = max(self.duration, self.elapsed() + 0.45)

    def set_status(self, text):
        self.status = text
        self.update()

    def elapsed(self):
        return 0.0 if self.t0 is None else time.perf_counter() - self.t0

    def _frame(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        for p in self.parts: # fly toward the camera, respawn far away
            p[2] -= dt * 0.42
            p[4] += dt * 2.0
            if p[2] <= 0.05:
                p[0], p[1], p[2] = random.uniform(-1, 1), random.uniform(-1, 1), 1.0
        t = self.elapsed()
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
        out = max(0.0, min(1.0, (t - (self.end_at - 0.35)) / 0.35)) if self.end_at else 0.0   # fade/scale out
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(1.0 - ease_in_out(out))
        if out > 0:
            s = 1 + 0.08 * ease_in_out(out)
            p.translate(W / 2, H / 2)
            p.scale(s, s)
            p.translate(-W / 2, -H / 2)
        r = QRectF(0, 0, W, H).adjusted(1, 1, -1, -1)
        frame = QPainterPath()
        frame.addRoundedRect(r, 26, 26)
        p.fillPath(frame, QColor("#06060A"))
        p.save()
        p.setClipPath(frame)
        pulse = 0.5 + 0.5 * math.sin(t * 3.2)
        for cx, cy, rad, col, a in ((W / 2, 150, 300, (255, 30, 66), 90 + 50 * pulse), (W * 0.15, H, 260, (255, 184, 0), 40),
                                    (W * 0.88, 30, 220, (255, 30, 66), 50)):
            g = QRadialGradient(cx, cy, rad)
            g.setColorAt(0, QColor(*col, int(a)))
            g.setColorAt(1, QColor(*col, 0))
            p.fillRect(r, g)
        self._particles(p, t)
        self._logo(p, t)
        self._title(p, t)
        self._bar(p, t)
        p.restore()
        b = QLinearGradient(r.topLeft(), r.bottomRight())
        b.setColorAt(0, QColor(255, 30, 66, 220))
        b.setColorAt(0.5, QColor(255, 184, 0, 160))
        b.setColorAt(1, QColor(255, 184, 0, 30))
        p.setPen(QPen(QBrush(b), 1.5))
        p.drawPath(frame)
        p.end()

    def _particles(self, p, t):
        fov = 260.0
        cx, cy = W / 2, H / 2 - 20
        p.setPen(Qt.NoPen)
        for x, y, z, gold, rot in sorted(self.parts, key=lambda q: -q[2]):
            sx, sy = cx + x * fov / z * 1.2, cy + y * fov / z * 0.8
            size = max(1.2, 5.5 / z)
            a = int(max(0, min(1, (1.0 - z) * 1.6)) * 230)
            if a <= 4: continue
            col = QColor(255, 196, 40, a) if gold else QColor(255, 40, 80, a)
            p.save()
            p.translate(sx, sy)
            p.rotate(math.degrees(rot))
            diamond = QPolygonF([QPointF(0, -size * 1.5), QPointF(size, 0), QPointF(0, size * 1.5), QPointF(-size, 0)])
            p.setBrush(col)
            p.drawPolygon(diamond)
            if size > 3:
                p.setBrush(QColor(255, 255, 255, a // 2))
                p.drawPolygon(QPolygonF([QPointF(0, -size * 1.5), QPointF(size * 0.5, -size * 0.3), QPointF(0, 0)]))
            p.restore()

    def _logo(self, p, t):
        k = min(1.0, t / 1.15)
        angle = -100 * (1 - ease_out_back(k)) if k < 1 else 14 * math.sin((t - 1.15) * 2.4)
        scale = 0.55 + 0.45 * ease_out_back(k) if k < 1 else 1.0
        bob = 6 * math.sin(t * 2.2)
        size = 150
        cx, cy = W / 2, 140 + bob
        halo = QRadialGradient(cx, cy, 120)
        halo.setColorAt(0, QColor(255, 30, 66, int(120 * min(1, t * 2))))
        halo.setColorAt(1, QColor(255, 30, 66, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), 120, 120)
        # ground reflection ellipse (sells the 3D)
        sh = QRadialGradient(cx, 236, 70)
        sh.setColorAt(0, QColor(255, 184, 0, 70))
        sh.setColorAt(1, QColor(255, 184, 0, 0))
        p.setBrush(sh)
        p.drawEllipse(QPointF(cx, 236), 80, 12)
        tr3d = QTransform()
        tr3d.translate(cx, cy)
        tr3d.rotate(angle, Qt.YAxis, 900)
        tr3d.scale(scale, scale)
        p.save()
        p.setTransform(tr3d, True)
        p.setOpacity(p.opacity() * min(1.0, t * 3))
        p.drawPixmap(QRectF(-size / 2, -size / 2, size, size), self.crest, QRectF(self.crest.rect()))
        p.restore()

    def _title(self, p, t):
        k = max(0.0, min(1.0, (t - 0.55) / 0.6))
        if k <= 0: return
        font = QFont(theme.ui_font(34, QFont.Black))
        font.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        path = QPainterPath()
        text = "CLASH FARMER"
        path.addText(0, 0, font, text)
        br = path.boundingRect()
        y = 290 + 18 * (1 - ease_in_out(k))
        path.translate(W / 2 - br.width() / 2 - br.left(), y)
        br = path.boundingRect()
        p.save()
        p.setOpacity(p.opacity() * ease_in_out(k))
        metal = QLinearGradient(0, br.top(), 0, br.bottom())
        metal.setColorAt(0, QColor("#FFF6C8"))
        metal.setColorAt(0.45, QColor("#FFD700"))
        metal.setColorAt(0.55, QColor("#C98A00"))
        metal.setColorAt(1, QColor("#FFE58A"))
        p.setPen(QPen(QColor(120, 0, 20, 200), 3))
        p.drawPath(path.translated(0, 2))
        p.setPen(Qt.NoPen)
        p.fillPath(path, metal)
        # shimmer: a bright band sweeping left -> right across the letters
        sx = br.left() - 120 + (br.width() + 240) * (((t - 0.9) / 1.1) % 1.0)
        sh = QLinearGradient(sx - 60, br.top(), sx + 60, br.bottom())
        sh.setColorAt(0, QColor(255, 255, 255, 0))
        sh.setColorAt(0.5, QColor(255, 255, 255, 210))
        sh.setColorAt(1, QColor(255, 255, 255, 0))
        if t > 0.9: p.fillPath(path, sh)
        p.setPen(QColor(255, 220, 200, 150))
        p.setFont(theme.ui_font(10))
        p.drawText(QRectF(0, br.bottom() + 8, W, 22), Qt.AlignCenter, tr("app_sub"))
        p.restore()

    def _bar(self, p, t):
        prog = min(1.0, t / self.end_at) if self.end_at else min(0.92, t / self.duration)
        r = QRectF(W / 2 - 170, H - 46, 340, 8)
        glass = QPainterPath()
        glass.addRoundedRect(r, 4, 4)
        p.fillPath(glass, QColor(255, 255, 255, 22))
        p.setPen(QPen(QColor(255, 184, 0, 60), 1))
        p.drawPath(glass)
        f = QPainterPath()
        f.addRoundedRect(QRectF(r.left(), r.top(), max(8.0, r.width() * ease_in_out(prog) if prog < 1 else r.width()), r.height()), 4, 4)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor("#FF1E42"))
        g.setColorAt(1, QColor("#FFB800"))
        p.fillPath(f, g)
        p.setPen(QColor(255, 255, 255, 120))
        p.setFont(theme.ui_font(9))
        p.drawText(QRectF(0, H - 34, W, 22), Qt.AlignCenter, self.status)
