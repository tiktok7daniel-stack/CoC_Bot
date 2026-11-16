"""
Animated check seal (the "done" / "learned" moment), ~0.9 s:
  1. the seal pops in (scale with a soft overshoot + a small turn)
  2. the white check draws itself stroke by stroke
  3. a light ring expands and fades, a few sparks fly out
AnimatedSeal(size, gold=False).play()   static final frame with .finish()
"""
import math, random

from PySide6.QtCore import QByteArray, QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from .. import icons

DURATION = 900.0
_bases = {}


def _base(gold, px):
    """The seal without its check mark, rendered once per size."""
    key = (gold, px)
    if key not in _bases:
        svg = icons.GLYPHS["verified_gold" if gold else "verified"]
        cut = svg.index('<path d="M10.6 16.6')          # the two check strokes are the last elements
        svg = svg[:cut] + "</svg>"
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, px, px))
        p.end()
        _bases[key] = pm
    return _bases[key]


def _back(t, s=2.2):
    t = max(0.0, min(1.0, t)) - 1
    return t * t * ((s + 1) * t + s) + 1


def _out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class AnimatedSeal(QWidget):
    def __init__(self, size=22, gold=False, autoplay=False, parent=None):
        super().__init__(parent)
        self.seal, self.gold = size, gold
        pad = int(size * 0.45)                 # room for the ring and sparks
        self.setFixedSize(size + pad * 2, size + pad * 2)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.k = 1.0
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._step)
        rnd = random.Random(size)
        self.sparks = [(rnd.uniform(0, math.tau), rnd.uniform(0.75, 1.15)) for _ in range(8)]
        self.autoplay = autoplay

    def showEvent(self, e):
        super().showEvent(e)
        if self.autoplay:
            self.autoplay = False
            self.play()

    def play(self):
        self.k = 0.0
        self.clock.start()
        self.timer.start(16)
        self.update()

    def finish(self):
        self.timer.stop()
        self.k = 1.0
        self.update()

    def _step(self):
        self.k = min(1.0, self.clock.elapsed() / DURATION)
        if self.k >= 1.0: self.timer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        c = QPointF(self.width() / 2, self.height() / 2)
        s, k = self.seal, self.k
        col = QColor("#FFD36E") if self.gold else QColor("#55E39D")
        # 3. ring + sparks (behind the seal)
        rk = (k - 0.30) / 0.70
        if 0 < rk < 1:
            r = s * 0.5 + s * 0.42 * _out(rk)
            ring = QColor(col)
            ring.setAlphaF(0.85 * (1 - rk))
            p.setPen(QPen(ring, max(1.2, s * 0.07)))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r, r)
            for ang, sp in self.sparks:
                d = s * 0.55 + s * 0.38 * sp * _out(rk)
                pt = QPointF(c.x() + math.cos(ang) * d, c.y() + math.sin(ang) * d)
                spk = QColor(col)
                spk.setAlphaF(1 - rk)
                p.setPen(Qt.NoPen)
                p.setBrush(spk)
                p.drawEllipse(pt, max(1.0, s * 0.05), max(1.0, s * 0.05))
        # 1. the seal pops in
        sk = _back(k / 0.38)
        if sk > 0:
            p.save()
            p.translate(c)
            p.rotate(-25 * (1 - min(1.0, k / 0.38)))
            p.scale(sk, sk)
            base = _base(self.gold, int(s * 2))
            p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), base, QRectF(base.rect()))
            p.restore()
        # 2. the check draws itself (same stroke as the static seal: M10.6 16.6 l3.6 3.6 7.4-7.8 in a 32 box)
        ck = _out((k - 0.25) / 0.40)
        if ck > 0:
            f = s / 32.0
            o = QPointF(c.x() - s / 2, c.y() - s / 2)
            path = QPainterPath(o + QPointF(10.6 * f, 16.6 * f))
            path.lineTo(o + QPointF(14.2 * f, 20.2 * f))
            path.lineTo(o + QPointF(21.6 * f, 12.4 * f))
            part = QPainterPath(path.pointAtPercent(0))
            steps = 24
            for i in range(1, steps + 1):
                t = ck * i / steps
                part.lineTo(path.pointAtPercent(path.percentAtLength(path.length() * t)))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(0, 0, 0, 70), 3.6 * f, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(part.translated(0, 0.8 * f))
            p.setPen(QPen(QColor("#FFFFFF"), 3.0 * f, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(part)
        p.end()
