"""
Animated Toggle Switch — Luxury Dark Obsidian & Crimson.
Zero emojis, crimson thumb, glass track.
"""
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRectF, Property
from PySide6.QtGui import QPainter, QColor, QPen, QBrush
from PySide6.QtWidgets import QAbstractButton

from ..theme import TOKENS


class AnimatedToggle(QAbstractButton):
    """
    Luxury animated pill switch with crimson thumb.
    Track transitions from glass to crimson gradient.
    Thumb has subtle inner shadow.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(52, 28)
        self._pos = 0.0

        self._anim = self._create_animation()
        self.toggled.connect(self._animate)

    def _create_animation(self):
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(self, b"knob", self)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        return anim

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, v):
        super().setChecked(bool(v))
        self._pos = 1.0 if v else 0.0
        self.update()

    def _get_knob(self):
        return self._pos

    def _set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(52, 28)

    def paintEvent(self, e):
        from ..theme import TOKENS
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)

        r = self.rect().adjusted(1, 1, -1, -1)
        track_rect = QRectF(r)
        track_radius = track_rect.height() / 2

        t = max(0.0, min(1.0, float(self._pos)))

        # Track: glass → crimson gradient
        c0 = QColor("#1A1A22")  # glass2
        c1 = QColor("#E11D48")  # crimson

        track_color = QColor(
            int(c0.red() + (c1.red() - c0.red()) * t),
            int(c0.green() + (c1.green() - c0.green()) * t),
            int(c0.blue() + (c1.blue() - c0.blue()) * t),
        )

        # Track background
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)
        p.setPen(QPen(QColor(225, 29, 72, int(55 + 140 * t)), 1))
        p.setBrush(track_color)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), track_radius, track_radius)

        # Thumb
        d = track_rect.height() - 6
        start_x = track_rect.left() + 3
        end_x = track_rect.right() - 3 - d
        x = start_x + (end_x - start_x) * t

        thumb_rect = QRectF(x, track_rect.top() + 3, d, d)

        # Thumb shadow
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 80))
        p.drawEllipse(thumb_rect.adjusted(1, 1, 1, 1))

        # Thumb
        p.setBrush(QColor("#FFFFFF") if self.isEnabled() else QColor("#71717A"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(thumb_rect)

        # Inner highlight on thumb
        if self.isChecked():
            highlight = QColor(225, 29, 72, 60)
            p.setBrush(highlight)
            p.drawEllipse(thumb_rect.adjusted(2, 2, -2, -2))

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(52, 28)

    def sizePolicy(self):
        from PySide6.QtWidgets import QSizePolicy
        return QSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)