"""
Console log widget — monospace, color-coded output.
Zero emojis, pure Qt widgets for log display.
"""
from PySide6.QtCore import Qt, QTimer, QTime
from PySide6.QtGui import QPainter, QTextCursor, QTextCharFormat, QColor
from PySide6.QtWidgets import QTextEdit, QWidget, QVBoxLayout, QLabel


class ConsoleLog(QTextEdit):
    """
    Scrollable console log viewer with color-coded output.
    Monospace font, timestamps optional.
    """

    def __init__(self, parent=None, show_timestamps=True):
        super().__init__(parent)
        self._show_timestamps = show_timestamps
        self._timestamp_format = "HH:mm:ss"
        self._setup()

    def _setup(self):
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.NoWrap)
        from ..theme import mono_font
        self.setFont(mono_font(10))
        self.setStyleSheet("""
            background: #0A0A0C;
            color: #F4F4F5;
            border: 1px solid #2A2A3A;
            border-radius: 8px;
            padding: 8px;
        """)

    def append(self, text, level="info", color=None):
        """Append a log line with optional level and color."""
        from ..theme import TOKENS
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        fmt.setFontFamily("JetBrains Mono")

        if color is None:
            color_map = {
                "debug": TOKENS.get("dim", "#71717A"),
                "info": TOKENS.get("info", "#38BDF8"),
                "ok": TOKENS.get("ok", "#10B981"),
                "warn": TOKENS.get("warn", "#F59E0B"),
                "error": TOKENS.get("bad", "#EF4444"),
            }
            color = color_map.get(level, TOKENS["text"])

        fmt.setForeground(QColor(color))

        timestamp = ""
        if self._show_timestamps:
            timestamp = QTime.currentTime().toString(self._timestamp_format) + " "

        line = f"{timestamp}{text}\n"
        cursor.insertText(line, fmt)
        self.setTextCursor(cursor)

        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class LogPanel(QWidget):
    """Vertical log panel with header."""

    def __init__(self, parent=None, title="Console Log"):
        super().__init__(parent)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(8, 8, 8, 8)
        self.v.setSpacing(4)

        self.header = QLabel(title)
        self.header.setProperty("role", "h3")
        self.header.setStyleSheet("color: #F4F4F5;")
        self.v.addWidget(self.header)

        self.log = ConsoleLog()
        self.v.addWidget(self.log, 1)

    def append(self, text, level="info", color=None):
        self.log.append(text, level, color)

    def clear(self):
        self.log.clear()