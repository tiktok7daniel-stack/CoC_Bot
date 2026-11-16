"""
Interaction polish for every button in the app, installed once on the QApplication:
 - press ripple: a soft light circle expands from the exact point you clicked and fades (450 ms)
 - hover glow: main-action buttons (gold / green / red) light up with an animated halo, the text glows
Nothing to wire per widget: new buttons get it automatically.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPointF, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QPainter, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QGraphicsDropShadowEffect, QWidget

GLOW = {"primary": QColor(245, 183, 64), "go": QColor(61, 214, 140), "stop": QColor(240, 85, 90), "warn": QColor(245, 183, 64)}


class Ripple(QWidget):
    def __init__(self, host, pos, color):
        super().__init__(host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setGeometry(host.rect())
        self.pos0, self.color, self.k = QPointF(pos), color, 0.0
        r = host.rect()
        self.maxr = max(r.width(), r.height()) * 1.1
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(460)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self.anim.start()

    def _step(self, v):
        self.k = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rad = 8 + self.maxr * self.k
        c = QColor(self.color)
        c.setAlpha(int(90 * (1 - self.k)))
        g = QRadialGradient(self.pos0, rad)
        g.setColorAt(0, c)
        g.setColorAt(0.7, c)
        c2 = QColor(c)
        c2.setAlpha(0)
        g.setColorAt(1, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(self.pos0, rad, rad)
        p.end()


class FX(QObject):
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.MouseButtonPress, QEvent.Enter, QEvent.Leave) or not isinstance(obj, QAbstractButton):
            return False
        if not obj.isEnabled(): return False
        kind = obj.property("kind")
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            if kind not in ("win", "winclose"):
                col = QColor(26, 18, 6) if kind == "primary" else (QColor(255, 255, 255) if kind not in ("go",) else QColor(4, 23, 13))
                Ripple(obj, ev.position(), col)
        elif kind in GLOW:
            self._glow(obj, GLOW[kind], t == QEvent.Enter)
        return False

    def _glow(self, w, col, on):
        eff = w.graphicsEffect()
        if eff is not None and not isinstance(eff, QGraphicsDropShadowEffect): return
        if eff is None:
            if not on: return
            eff = QGraphicsDropShadowEffect(w)
            eff.setOffset(0, 0)
            c = QColor(col)
            c.setAlpha(150)
            eff.setColor(c)
            eff.setBlurRadius(0)
            w.setGraphicsEffect(eff)
        anim = getattr(w, "_fx_anim", None)
        if anim is None:
            anim = QVariantAnimation(w)
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(lambda v, e=eff: e.setBlurRadius(v))
            w._fx_anim = anim
        anim.stop()
        anim.setStartValue(eff.blurRadius())
        anim.setEndValue(28.0 if on else 0.0)
        anim.start()


_fx = None


def install(app):
    global _fx
    if _fx is None:
        _fx = FX(app)
        app.installEventFilter(_fx)
    return _fx
