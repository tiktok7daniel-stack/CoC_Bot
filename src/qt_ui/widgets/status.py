"""
Status pills, live indicators, and status dots — Luxury Dark Obsidian & Crimson.
Zero emojis - uses crisp SVG icons from icons.py.
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, Property
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen, QFont
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout

from ..theme import TOKENS, ui_font
from ..i18n import tr
from ..icons import icons, pixmap as icon_pixmap


class StatusPill(QLabel):
    """
    Rounded pill with colored dot indicator and text.
    States: ok, warn, bad, info, idle, running, stopped.
    Uses crisp SVG icons via Qt rendering (zero Unicode emojis in display).
    """

    STATES = {
        "ok":        "ok",
        "running":   "ok",
        "ready":     "ok",
        "info":      "info",
        "idle":      "info",
        "warn":      "warn",
        "warning":   "warn",
        "bad":       "bad",
        "error":     "bad",
        "stopped":   "dim",
        "paused":    "warn",
        "scheduled": "warn",
    }

    def __init__(self, key="stopped", text=None, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.RichText)
        self.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.set(key, text)

    def set(self, key, text=None):
        tone = self.STATES.get(key, "dim")
        c = TOKENS.get(tone, TOKENS["text"])
        bg = TOKENS.get(f"{tone}_bg", "rgba(255,255,255,0.04)")
        dot = icons.img_tag("dot", 13, c)
        txt = text if text is not None else tr("st_" + key)
        self.setText(f'{dot}&nbsp;{txt}')
        self.setStyleSheet(f"""
            QLabel {{
                background: {bg};
                border: 1px solid {TOKENS['border_solid']};
                border-radius: 13px;
                padding: 4px 14px;
                font-weight: 600;
                font-size: 9.5pt;
            }}
        """)


class LiveDot(QLabel):
    """
    Animated live indicator dot with pulse animation.
    States: live (crimson pulse), recording (crimson solid), idle (dim).
    """

    def __init__(self, size=10, parent=None):
        super().__init__()
        self.setFixedSize(16, 16)
        self._state = "idle"
        self._pulse = 0.0
        self._anim = QPropertyAnimation(self, b"pulse", self)
        self._anim.setDuration(1000)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

    def set_state(self, state: str):
        """State: live, recording, idle"""
        self._state = state
        if state == "live":
            self._anim.setStartValue(0.3)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self._anim.stop()

    def pulse(self):
        return self._pulse

    def set_pulse(self, v):
        self._pulse = v
        self.update()

    pulse = Property(float, pulse, set_pulse)

    def paintEvent(self, e):
        from ..theme import TOKENS
        p = QPainter(self)
        p.setRenderHint(p.Antialiasing)

        # Colors based on state
        if self._state == "live":
            c = QColor("#E11D48")
            alpha = int(120 + 135 * self._pulse)
        elif self._state == "recording":
            c = QColor("#E11D48")
            alpha = 255
        else:
            c = QColor("#71717A")
            alpha = 180

        c.setAlpha(alpha)

        p.setRenderHint(p.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        r = self.rect().adjusted(3, 3, -3, -3)
        p.drawEllipse(r)

        # Pulse ring for live state
        if self._state == "live":
            p.setPen(QPen(QColor("#E11D48"), max(1, int(3 * (1 - self._pulse)))))
            p.setBrush(Qt.NoBrush)
            ring_r = r.adjusted(-int(4 * self._pulse), -int(4 * self._pulse),
                                 int(4 * self._pulse), int(4 * self._pulse))
            p.drawEllipse(ring_r)


class LiveStatusBadge(QWidget):
    """
    Combined live dot + text badge for HUD.
    Shows: LIVE / REC / IDLE with crimson pulse.
    """

    def __init__(self, text="LIVE", parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(6)

        self.dot = LiveDot()
        self.label = QLabel("LIVE")
        self.label.setFont(ui_font(9, QFont.Weight(700)))
        self.label.setStyleSheet("color: #F4F4F5;")

        h.addWidget(self.dot)
        h.addWidget(self.label)

    def set_state(self, state: str):
        """live, recording, idle"""
        self.dot.set_state(state)
        labels = {"live": "LIVE", "recording": "REC", "idle": "IDLE"}
        self.label.setText(labels.get(state, "IDLE"))

    def set_text(self, text):
        self.label.setText(text)


class StatusRow(QWidget):
    """Horizontal row: label + status pill/value."""

    def __init__(self, title_key, value_widget, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        label = QLabel(tr(title_key))
        label.setFont(ui_font(9, QFont.Weight(500)))
        label.setStyleSheet("color: #A1A1AA;")

        h.addWidget(label)
        h.addStretch(1)
        h.addWidget(value_widget)

        self.setStyleSheet("background: transparent;")