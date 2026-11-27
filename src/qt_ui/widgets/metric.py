"""
Metric tiles, KPI cards, and tabular numeric displays — Luxury Dark Obsidian & Crimson.
Tabular monospace numerals for zero-jitter live metrics.
"""
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget

from ..theme import TOKENS, mono_font, ui_font
from ..icons import icons


class MetricTile(QFrame):
    """
    Elevated KPI metric card with tabular numerals.
    Zero-jitter monospace numerals for live counters.
    """

    def __init__(self, key, accent=None, parent=None):
        super().__init__(parent)
        self._accent = accent or TOKENS["crimson"]

        self.setObjectName("MetricTile")
        self.setStyleSheet(f"""
            #MetricTile {{
                background: #1A1A22;
                border: 1px solid #2A2A3A;
                border-radius: 14px;
            }}
        """)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(4)

        self.value = QLabel("0")
        self.value.setProperty("role", "kpi")
        self.value.setAlignment(Qt.AlignCenter)
        self.value.setFont(mono_font(24, QFont.Weight(800)))
        self.value.setStyleSheet(f"color: {self._accent}; font-size: 28pt; font-weight: 800;")
        v.addWidget(self.value)

        from ..theme import tr
        self.cap = QLabel(tr(key) if key else "")
        self.cap.setAlignment(Qt.AlignCenter)
        self.cap.setStyleSheet("color: #A1A1AA; font-size: 9pt;")
        v.addWidget(self.cap)

    def set(self, text):
        self.value.setText(str(text))

    def set_accent(self, color):
        self._accent = color
        self.value.setStyleSheet(f"color: {color}; font-size: 28pt; font-weight: 800;")


class KpiRow(QWidget):
    """Horizontal row of KPI tiles with consistent spacing."""

    def __init__(self, items, parent=None):
        """items: [(key, accent)]"""
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        self.tiles = []
        for key, accent in items:
            tile = MetricTile(key, accent)
            h.addWidget(tile, 1)
            self.tiles.append(tile)

    def set_values(self, values):
        for tile, val in zip(self.tiles, values):
            tile.set(val)


class MetricLabel(QLabel):
    """
    Single metric label with monospace numeral + label.
    For inline metrics in panels.
    """

    def __init__(self, label_text="", value="0", accent=None, parent=None):
        super().__init__(parent)
        self._accent = accent or "#E11D48"

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self.value_label = QLabel("0")
        self.value_label.setFont(mono_font(14, QFont.Weight(800)))
        self.value_label.setStyleSheet(f"color: {self._accent}; font-size: 16pt; font-weight: 800;")
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value_label.setText(str(value))

        self.cap_label = QLabel(label_text)
        self.cap_label.setStyleSheet("color: #A1A1AA; font-size: 9pt;")
        self.cap_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        h.addWidget(self.cap_label, 1)
        h.addWidget(self.value_label)

    def set_value(self, text):
        self.value_label.setText(str(text))

    def set_accent(self, color):
        self._accent = color
        self.value_label.setStyleSheet(f"color: {color}; font-size: 14pt; font-weight: 800;")


class LiveCounter(QLabel):
    """
    Animated live counter with monospace numerals.
    Smoothly transitions between values.
    """

    def __init__(self, value=0, accent=None, parent=None):
        super().__init__(parent)
        self._accent = accent or "#E11D48"
        self._value = float(value)
        self._target = float(value)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setDuration(300)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.setFont(mono_font(18, QFont.Weight(800)))
        self.setStyleSheet(f"color: {self._accent}; font-size: 20pt; font-weight: 800;")
        self.setAlignment(Qt.AlignCenter)
        self.setText(str(int(value)))

    def _get_value(self):
        return self._value

    def _set_value(self, v):
        self._value = v
        self.setText(f"{int(v):,}")

    value = Property(float, _get_value, _set_value)

    def set_target(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def set_accent(self, color):
        self._accent = color
        self.setStyleSheet(f"color: {color}; font-size: 18pt; font-weight: 800;")