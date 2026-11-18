"""
The first thing the program shows: which game? Clash of Clans or Clash Royale — each has its own full face
(its own screens, its own accounts). "Remember" opens straight into the last one next time; the sidebar's
"change game" brings this back.
"""
import os, sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QAbstractButton

from .. import icons
from ..i18n import tr
from ..theme import TOKENS

_ROOT = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class GameCard(QAbstractButton):
    def __init__(self, key, title_key, sub_key, color, art=None, icon_name=None):
        super().__init__()
        self.key, self.color = key, QColor(color)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(300, 340)
        self._hover = False
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 26, 22, 22)
        v.setSpacing(12)
        pic = QLabel()
        pic.setAlignment(Qt.AlignCenter)
        pm = QPixmap(art) if art and os.path.exists(art) else icons.pixmap(icon_name or "crest", 120)
        pic.setPixmap(pm.scaled(130, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        pic.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(pic, 1)
        t = QLabel(tr(title_key))
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"font-size: 22px; font-weight: 800; color: {color};")
        t.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(t)
        s = QLabel(tr(sub_key))
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignCenter)
        s.setProperty("role", "sub")
        s.setAttribute(Qt.WA_TransparentForMouseEvents)
        v.addWidget(s)

    def enterEvent(self, e):
        self._hover = True; self.update()

    def leaveEvent(self, e):
        self._hover = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(TOKENS["glass2"])
        p.setBrush(bg)
        c = QColor(self.color)
        c.setAlpha(255 if self._hover else 110)
        pen = p.pen(); pen.setColor(c); pen.setWidth(3 if self._hover else 2); p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 22, 22)


class GameChooser(QDialog):
    chosen = Signal(str)

    def __init__(self, parent, remember=False):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(f"QDialog {{ background: {TOKENS.get('bg', '#0b0710')}; border: 1px solid {TOKENS['border']};"
                           f" border-radius: 24px; }}")
        v = QVBoxLayout(self)
        v.setContentsMargins(36, 30, 36, 26)
        v.setSpacing(18)
        crest = QLabel()
        crest.setPixmap(icons.pixmap("crest", 56))
        crest.setAlignment(Qt.AlignCenter)
        v.addWidget(crest)
        h = QLabel(tr("gc_title"))
        h.setAlignment(Qt.AlignCenter)
        h.setStyleSheet("font-size: 26px; font-weight: 800;")
        v.addWidget(h)
        sub = QLabel(tr("gc_sub"))
        sub.setAlignment(Qt.AlignCenter)
        sub.setProperty("role", "sub")
        v.addWidget(sub)
        row = QHBoxLayout()
        row.setSpacing(26)
        cards_dir = os.path.join(_ROOT, "assets", "royale", "cards")
        self.coc = GameCard("coc", "gm_coc", "gc_coc_sub", "#f5b740", icon_name="crest")
        self.royale = GameCard("royale", "gm_royale", "gc_royale_sub", "#60a5fa",
                               art=os.path.join(cards_dir, "hog_rider.jpg"))
        for c in (self.coc, self.royale):
            c.clicked.connect(lambda _=False, k=c.key: self._pick(k))
            row.addWidget(c)
        v.addLayout(row)
        self.remember = QCheckBox(tr("gc_remember"))
        self.remember.setChecked(bool(remember))
        v.addWidget(self.remember, 0, Qt.AlignHCenter)

    def _pick(self, key):
        self.chosen.emit(key)
        self.accept()
