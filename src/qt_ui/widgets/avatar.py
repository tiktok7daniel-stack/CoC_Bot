"""
Account profile: a picture (round, gold ring) and a display name for every account.
Pictures live on this computer in ~/.CoC_Bot/avatars/<account>.png (square crop, 256 px);
display names in the app settings "profiles": {account: {"name": ...}}.
Every Avatar on screen updates as soon as a picture changes (profiles.changed).
"""
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QFileDialog, QWidget

from ..theme import TOKENS, ui_font

DIR = Path.home() / ".CoC_Bot" / "avatars"


class _Hub(QObject):
    changed = Signal(str)        # account whose picture / name changed


profiles = _Hub()
_cache = {}


def picture(acc):
    """QPixmap of the account picture, or None."""
    p = DIR / f"{acc}.png"
    if not p.exists(): return None
    key = (acc, p.stat().st_mtime)
    if key not in _cache:
        pm = QPixmap(str(p))
        _cache[key] = pm if not pm.isNull() else None
    return _cache[key]


def display_name(store, acc):
    return ((store.APP.get("profiles") or {}).get(acc) or {}).get("name") or acc


def set_display_name(store, acc, name):
    prof = store.APP.setdefault("profiles", {})
    prof.setdefault(acc, {})["name"] = name.strip()
    store.changed()
    profiles.changed.emit(acc)


def choose_picture(parent, acc):
    """File dialog -> square-cropped 256 px PNG. -> True when a picture was set."""
    path, _ = QFileDialog.getOpenFileName(parent, "Picture", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
    if not path: return False
    return set_picture(acc, path)


def set_picture(acc, path):
    img = QImage(path)
    if img.isNull(): return False
    side = min(img.width(), img.height())
    # tall pictures (phone wallpapers): a bit above the middle, where the face usually is
    y = int((img.height() - side) * (0.42 if img.height() > img.width() * 1.2 else 0.5))
    img = img.copy((img.width() - side) // 2, y, side, side).scaled(256, 256, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    DIR.mkdir(parents=True, exist_ok=True)
    ok = img.save(str(DIR / f"{acc}.png"), "PNG")
    if ok: profiles.changed.emit(acc)
    return ok


def remove_picture(acc):
    try: (DIR / f"{acc}.png").unlink()
    except OSError: pass
    profiles.changed.emit(acc)


class Avatar(QWidget):
    """Round account picture with a gold ring (initial letter on gold when there is no picture)."""

    def __init__(self, acc="", size=40, ring=True, parent=None):
        super().__init__(parent)
        self.acc, self.ring = acc, ring
        self.setFixedSize(size, size)
        profiles.changed.connect(self._changed)

    def set_account(self, acc):
        self.acc = acc
        self.update()

    def _changed(self, acc):
        if acc == self.acc: self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        s = self.width()
        ring = max(2.0, s * 0.06) if self.ring else 0
        outer = QRectF(0.5, 0.5, s - 1, s - 1)
        inner = outer.adjusted(ring + 1, ring + 1, -ring - 1, -ring - 1)
        if self.ring:
            g = QLinearGradient(outer.topLeft(), outer.bottomRight())
            g.setColorAt(0, QColor("#FFE58A"))
            g.setColorAt(0.5, QColor("#F5B740"))
            g.setColorAt(1, QColor("#9A5F0E"))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(outer)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.setClipPath(clip)
        pm = picture(self.acc)
        if pm is not None:
            p.drawPixmap(inner, pm, QRectF(pm.rect()))
        else:
            g = QLinearGradient(inner.topLeft(), inner.bottomRight())
            g.setColorAt(0, QColor("#2A2214"))
            g.setColorAt(1, QColor("#14110C"))
            p.fillPath(clip, g)
            p.setPen(QColor(TOKENS["accent_hi"]))
            p.setFont(ui_font(max(8.0, s * 0.30), 800))
            p.drawText(inner, Qt.AlignCenter, (self.acc or "?")[:1].upper())
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 90), 1))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(inner)
        p.end()
