"""
Grid of troop / spell / siege / pet pictures (the images uploaded to the project, served by the bot).
Used as a searchable gallery (Army tab) and as a click-to-select picker (second-wave spells).
Pictures are fetched once and cached for the whole app.
"""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import icons
from ..i18n import on_lang, tr, unit_name
from ..theme import TOKENS
from .controls import FlowLayout, label

_PIX = {}
_WAITING = {}


def unit_pixmap(api, group, name, done):
    """done(QPixmap) once the picture is loaded (immediately when cached)."""
    key = (group, name)
    if key in _PIX:
        done(_PIX[key])
        return
    if key in _WAITING:
        _WAITING[key].append(done)
        return
    _WAITING[key] = [done]

    def got(data):
        pm = QPixmap()
        if data: pm.loadFromData(data)
        _PIX[key] = pm
        for fn in _WAITING.pop(key, []):
            try: fn(pm)
            except RuntimeError: pass
    api.get(f"/unit/{group}/{name}.png", got, raw=True)


class UnitTile(QFrame):
    clicked = Signal(str)

    def __init__(self, api, group, name, size=64, selectable=False, caption=True):
        super().__init__()
        self.group, self.name, self.selectable = group, name, selectable
        self.selected = False
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(2)
        self.img = QLabel()
        self.img.setFixedSize(size, size)
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setPixmap(icons.pixmap("image", size // 2, TOKENS["dim"]))
        v.addWidget(self.img, 0, Qt.AlignHCenter)
        self.cap = None
        if caption:
            self.cap = QLabel(unit_name(name))
            self.cap.setAlignment(Qt.AlignCenter)
            self.cap.setWordWrap(True)
            self.cap.setStyleSheet(f"color: {TOKENS['muted']}; font-size: 8pt;")
            self.cap.setFixedWidth(size + 18)
            v.addWidget(self.cap)
            on_lang(lambda: self.cap.setText(unit_name(name)))
        self.setToolTip(unit_name(name))
        if selectable: self.setCursor(Qt.PointingHandCursor)
        unit_pixmap(api, group, name, self._set)
        self._style()

    def _set(self, pm):
        if not pm.isNull():
            self.img.setPixmap(pm.scaled(self.img.size() * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation).scaled(
                self.img.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_selected(self, v):
        self.selected = v
        self._style()

    def _style(self):
        if self.selected:
            css = f"background: rgba(255,30,66,0.24); border: 2px solid {TOKENS['purple']}; border-radius: 12px;"
        else:
            css = f"background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 12px;"
        self.setStyleSheet(f"UnitTile {{ {css} }}")
        if self.selectable and not self.selected:
            self.img.setStyleSheet("opacity: 0.6;")

    def mousePressEvent(self, e):
        if self.selectable and e.button() == Qt.LeftButton: self.clicked.emit(self.name)


class UnitGallery(QWidget):
    """All groups with a search box; selectable=True turns it into a picker of one group."""
    selection_changed = Signal(list)

    def __init__(self, api, groups=("troops", "spells", "sieges", "pets"), selectable=False, size=64, searchable=True):
        super().__init__()
        self.api, self.groups, self.selectable, self.size = api, groups, selectable, size
        self.catalog = {}
        self.tiles = []
        self.selected = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self.search = None
        if searchable:
            self.search = QLineEdit()
            self.search.setProperty("role", "search")
            self.search.setPlaceholderText(tr("army_search_ph"))
            self.search.addAction(icons.icon("search", TOKENS["muted"], 16), QLineEdit.LeadingPosition)
            self.search.textChanged.connect(self._filter)
            on_lang(lambda: self.search.setPlaceholderText(tr("army_search_ph")))
            v.addWidget(self.search)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        v.addLayout(self.body)
        api.get("/api/units", self._got)

    def _got(self, data):
        if not isinstance(data, dict) or data.get("error"): return
        self.catalog = data
        self.build()

    def build(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        self.tiles = []
        titles = {"troops": "ug_troops", "spells": "ug_spells", "sieges": "ug_sieges", "pets": "ug_pets"}
        for g in self.groups:
            names = self.catalog.get(g, [])
            if not names: continue
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(0, 0, 0, 0)
            bv.setSpacing(6)
            if len(self.groups) > 1:
                bv.addWidget(label(f"{tr(titles[g])}  ({len(names)})", "h3"))
            host = QWidget()
            flow = FlowLayout(host, 8)
            for n in names:
                t = UnitTile(self.api, g, n, self.size, self.selectable, caption=not self.selectable or self.size >= 48)
                t.set_selected(n in self.selected)
                t.clicked.connect(self._toggle)
                flow.addWidget(t)
                self.tiles.append(t)
            bv.addWidget(host)
            self.body.addWidget(box)
        if self.search: self._filter(self.search.text())

    def _filter(self, text):
        q = (text or "").strip().lower()
        for t in self.tiles:
            t.setVisible(not q or q in t.name.lower() or q in unit_name(t.name).lower())

    def set_selected(self, names):
        self.selected = [n for n in names if n]
        for t in self.tiles: t.set_selected(t.name in self.selected)

    def _toggle(self, name):
        if name in self.selected: self.selected.remove(name)
        else: self.selected.append(name)
        for t in self.tiles: t.set_selected(t.name in self.selected)
        self.selection_changed.emit(list(self.selected))
