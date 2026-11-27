"""
Glassmorphism card components — Luxury Dark Obsidian & Crimson.
"""
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QRectF, QPointF, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QLinearGradient, QRadialGradient, QColor, QPen, QBrush, QFont
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QGraphicsDropShadowEffect

from ..theme import TOKENS, LIGHT, ui_font
from ..i18n import tr
from .. import icons


class GlassCard(QFrame):
    """
    Luxury glassmorphism card with crimson accent glow.
    Backward compatible with existing GlassCard API.
    """

    def __init__(self, title_key=None, icon_name=None, sub_key=None, glow=False, parent=None, pad=16):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._hover = False
        self._glow = glow
        self._glow_anim = 0.0

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 16)
        self.v.setSpacing(12)

        self.header = None
        self.tools = None

        if title_key:
            self.header = QHBoxLayout()
            self.header.setSpacing(10)
            self.header.setAlignment(Qt.AlignTop | Qt.AlignLeft)

            if icon_name:
                from ..icons import pixmap
                badge = QLabel()
                badge.setFixedSize(32, 32)
                badge.setPixmap(icons.pixmap(icon_name, 28, "#E11D48"))
                self.header.addWidget(badge)

            box = QVBoxLayout()
            box.setSpacing(0)
            self.title = QLabel(tr(title_key))
            self.title.setFont(ui_font(11, QFont.Weight(700)))
            self.title.setStyleSheet("color: #F4F4F5;")
            box.addWidget(self.title)
            self.header.addLayout(box, 1)

            self.tools = QHBoxLayout()
            self.tools.setSpacing(6)
            self.header.addLayout(self.tools)
            self.v.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        self.v.addLayout(self.body)
        self.v.addStretch(1)

        self.setStyleSheet("""
            QFrame {
                background: transparent;
                border: none;
            }
        """)

    def add(self, w, stretch=0):
        if hasattr(w, 'count'):  # QLayout
            self.v.insertLayout(self.v.count() - 1, w, stretch)
        else:
            self.v.insertWidget(self.v.count() - 1, w, stretch)
        return w

    def add_tool(self, w):
        if self.tools:
            self.tools.addWidget(w)
        return w

    def paintEvent(self, e):
        from ..theme import TOKENS
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)
        r = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)

        # Base glass surface
        p.fillPath(path, QColor("#121216"))

        # Top sheen
        sheen = QLinearGradient(r.topLeft(), r.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 11))
        sheen.setColorAt(0.24, QColor(255, 255, 255, 0))
        p.fillPath(path, sheen)

        # Border
        p.setPen(QPen(QColor("#2A2A3A"), 1))
        p.drawPath(path)

    def add_widget(self, widget, stretch=0):
        """Alias for add() for clarity."""
        return self.add(widget, stretch)


class GlassPanel(QFrame):
    """Simpler glass panel without header."""

    def __init__(self, parent=None, pad=16):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, e):
        from ..theme import TOKENS
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)
        r = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, QColor("#121216"))
        p.setPen(QPen(QColor("#2A2A3A"), 1))
        p.drawPath(path)


class ElevatedCard(QFrame):
    """Elevated card with crimson accent on hover."""

    def __init__(self, parent=None, pad=16):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._hover = False
        self._hover_progress = 0.0

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(16, 14, 16, 16)
        self.v.setSpacing(12)

        self.setStyleSheet("background: transparent; border: none;")

    def add(self, w, stretch=0):
        if hasattr(w, 'count'):
            self.v.addLayout(w, stretch)
        else:
            self.v.addWidget(w, stretch)
        return w

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        from ..theme import TOKENS
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)
        r = self.rect().adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)

        p.fillPath(path, QColor("#121216"))

        # Top sheen
        sheen = QLinearGradient(self.rect().topLeft(), self.rect().bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 11))
        sheen.setColorAt(0.24, QColor(255, 255, 255, 0))
        p.fillPath(path, sheen)

        # Border with crimson accent on hover
        if self._hover:
            p.setPen(QPen(QColor("#E11D48"), 1.5))
        else:
            p.setPen(QPen(QColor("#2A2A3A"), 1))
        p.drawPath(path)