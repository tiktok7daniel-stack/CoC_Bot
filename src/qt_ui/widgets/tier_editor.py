"""
Drag-and-drop multi-level priority editor (buildings / lab / pets / builder base).
Value in the store: list of levels, each a list of names, e.g. [["Laboratory", "Hero Hall"], ["Army Camp"]].
Tags can be dragged to another level (or another place in the same level), removed with their x,
and added with an auto-completing input per level.
"""
from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCompleter, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS
from .controls import FlowLayout, IconButton, label

MIME = "application/x-cocbot-tier-tag"

SUGGEST = {
    "home_base": ["Town Hall", "Laboratory", "Blacksmith", "Hero Hall", "Barbarian King", "Archer Queen", "Minion Prince",
                  "Grand Warden", "Royal Champion", "Dragon Duke", "Army Camp", "Barracks", "Dark Barracks", "Spell Factory",
                  "Dark Spell Factory", "Workshop", "Clan Castle", "Pet House", "Gold Mine", "Elixir Collector",
                  "Dark Elixir Drill", "Gold Storage", "Elixir Storage", "Dark Elixir Storage", "Cannon", "Archer Tower",
                  "Mortar", "Air Defense", "Wizard Tower", "Air Sweeper", "Hidden Tesla", "Bomb Tower", "X-Bow",
                  "Inferno Tower", "Eagle Artillery", "Scattershot", "Builder's Hut", "Spell Tower", "Monolith",
                  "Multi-Archer Tower", "Ricochet Cannon", "Firespitter", "Multi-Gear Tower", "Helper Hut", "Wall"],
    "home_lab": ["Barbarian", "Archer", "Giant", "Goblin", "Wall Breaker", "Balloon", "Wizard", "Healer", "Dragon",
                 "P.E.K.K.A", "Baby Dragon", "Miner", "Electro Dragon", "Yeti", "Dragon Rider", "Electro Titan",
                 "Root Rider", "Thrower", "Minion", "Hog Rider", "Valkyrie", "Golem", "Witch", "Lava Hound", "Bowler",
                 "Ice Golem", "Headhunter", "Apprentice Warden", "Druid", "Furnace", "Lightning Spell", "Healing Spell",
                 "Rage Spell", "Jump Spell", "Freeze Spell", "Clone Spell", "Invisibility Spell", "Recall Spell",
                 "Revive Spell", "Poison Spell", "Earthquake Spell", "Haste Spell", "Skeleton Spell", "Bat Spell",
                 "Overgrowth Spell", "Ice Block Spell", "Wall Wrecker", "Battle Blimp", "Stone Slammer",
                 "Siege Barracks", "Log Launcher", "Flame Flinger", "Battle Drill", "Troop Launcher"],
    "pet_house": ["L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn", "Frosty", "Diggy", "Poison Lizard", "Phoenix",
                  "Spirit Fox", "Angry Jelly", "Sneezy", "Greedy Raven"],
    "builder_base": ["Builder Hall", "Gold Mine", "Elixir Collector", "Gold Storage", "Elixir Storage", "Gem Mine",
                     "Clock Tower", "Builder Barracks", "Army Camp", "Star Laboratory", "Battle Machine", "Battle Copter",
                     "Double Cannon", "Archer Tower", "Hidden Tesla", "Firecrackers", "Crusher", "Guard Post",
                     "Air Bombs", "Multi Mortar", "Roaster", "Giant Cannon", "Mega Tesla", "Lava Launcher",
                     "X-Bow", "O.T.T.O's Outpost", "Healing Hut", "Reinforcement Camp", "Wall"],
    "builder_lab": ["Raged Barbarian", "Sneaky Archer", "Boxer Giant", "Beta Minion", "Bomber", "Baby Dragon",
                    "Cannon Cart", "Night Witch", "Drop Ship", "Power P.E.K.K.A", "Hog Glider", "Electrofire Wizard"],
}


class Tag(QFrame):
    removed = Signal(object)

    def __init__(self, name):
        super().__init__()
        self.name = name
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 3, 4, 3)
        h.setSpacing(4)
        grip = QLabel()
        grip.setPixmap(icons.pixmap("drag", 12, TOKENS["dim"]))
        h.addWidget(grip)
        h.addWidget(QLabel(name))
        x = QToolButton()
        x.setIcon(icons.icon("x", TOKENS["muted"], 12))
        x.setCursor(Qt.PointingHandCursor)
        x.setStyleSheet("QToolButton { border: 0; background: transparent; padding: 2px; } QToolButton:hover { background: rgba(239,68,68,0.25); border-radius: 4px; }")
        x.clicked.connect(lambda: self.removed.emit(self))
        h.addWidget(x)
        self.setCursor(Qt.OpenHandCursor)
        self.setStyleSheet(f"Tag {{ background: rgba(245, 183, 64,0.14); border: 1px solid {TOKENS['border']}; border-radius: 13px; }}"
                           f" Tag:hover {{ border-color: {TOKENS['border_hover']}; }}")
        self._press = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton: self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or (e.position().toPoint() - self._press).manhattanLength() < 8: return
        drag = QDrag(self)
        md = QMimeData()
        md.setData(MIME, self.name.encode("utf-8"))
        drag.setMimeData(md)
        pm = self.grab()
        drag.setPixmap(pm)
        drag.setHotSpot(self._press)
        self.setVisible(False)
        if drag.exec(Qt.MoveAction) != Qt.MoveAction:
            self.setVisible(True)
        self._press = None

    def mouseReleaseEvent(self, e):
        self._press = None


class LevelBox(QFrame):
    """One priority level: number badge, tags (drop target), add input."""
    dropped = Signal(object, str, int)   # level, name, insert index

    def __init__(self, editor, index, names):
        super().__init__()
        self.editor, self.index = editor, index
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(8)
        head = QHBoxLayout()
        badge = QLabel(str(index + 1))
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(26, 22)
        badge.setStyleSheet(f"background: {TOKENS['violet']}; color: white; border-radius: 7px; font-weight: 800;")
        head.addWidget(badge)
        head.addWidget(label(f"{tr('level')} {index + 1}", "h3"))
        head.addStretch(1)
        for ic, tip, fn in (("chevron_down", "down", lambda: editor.move_level(index, 1)),
                            ("chevron_down", "up", lambda: editor.move_level(index, -1)),
                            ("trash", "remove_level", lambda: editor.remove_level(index))):
            b = QToolButton()
            b.setIcon(icons.icon(ic, TOKENS["muted"], 14))
            if tip == "up":
                b.setIcon(icons.icon("chevron_down", TOKENS["muted"], 14))
                b.setStyleSheet("QToolButton { border: 0; padding: 4px; } QToolButton:hover { background: rgba(245, 183, 64,0.2); border-radius: 6px; }")
                b.setArrowType(Qt.UpArrow)
            else:
                b.setStyleSheet("QToolButton { border: 0; padding: 4px; } QToolButton:hover { background: rgba(245, 183, 64,0.2); border-radius: 6px; }")
            if tip == "down": b.setArrowType(Qt.DownArrow)
            b.setToolTip(tr(tip))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            head.addWidget(b)
        v.addLayout(head)
        self.tags_host = QWidget()
        self.flow = FlowLayout(self.tags_host, 6)
        self.tags = []
        for n in names:
            self._add_tag(n)
        v.addWidget(self.tags_host)
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("add_item_ph"))
        comp = QCompleter(editor.suggestions)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.input.setCompleter(comp)
        self.input.returnPressed.connect(self._add_typed)
        comp.activated.connect(lambda _t: self._add_typed())
        v.addWidget(self.input)
        self._hl = False
        self.setStyleSheet(f"LevelBox {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 16px; }}")

    def _add_tag(self, name):
        t = Tag(name)
        t.removed.connect(lambda tag: self.editor.remove_item(self.index, tag.name))
        self.flow.addWidget(t)
        self.tags.append(t)

    def _add_typed(self):
        name = self.input.text().strip()
        if not name: return
        self.input.clear()
        self.editor.add_item(self.index, name)

    def _drop_index(self, pos):
        local = self.tags_host.mapFrom(self, pos)
        best = len(self.tags)
        for i, t in enumerate(self.tags):
            g = t.geometry()
            if g.contains(local) or (local.y() < g.bottom() and local.x() < g.center().x() and self.layoutDirection() == Qt.LeftToRight):
                return i
        return best

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()
            self._hl = True
            self.setStyleSheet(f"LevelBox {{ background: rgba(245, 183, 64,0.12); border: 1px dashed {TOKENS['purple']}; border-radius: 16px; }}")

    def dragLeaveEvent(self, e):
        self._unhl()

    def _unhl(self):
        self.setStyleSheet(f"LevelBox {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 16px; }}")

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(MIME): e.acceptProposedAction()

    def dropEvent(self, e):
        name = bytes(e.mimeData().data(MIME)).decode("utf-8")
        idx = self._drop_index(e.position().toPoint())
        e.setDropAction(Qt.MoveAction)
        e.accept()
        self._unhl()
        self.editor.move_item(name, self.index, idx)


class TierEditor(QWidget):
    changed = Signal()

    def __init__(self, store, path, kind):
        super().__init__()
        self.store, self.path = store, path
        self.suggestions = SUGGEST.get(kind, [])
        self.levels = []
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(10)
        self.host = QVBoxLayout()
        self.host.setSpacing(10)
        self.v.addLayout(self.host)
        row = QHBoxLayout()
        self.add_btn = IconButton("plus", "add_level")
        self.add_btn.clicked.connect(self.add_level)
        row.addWidget(self.add_btn)
        row.addWidget(label(key="drag_hint", role="sub"), 1)
        self.v.addLayout(row)
        store.bind("s", path, self._load)
        on_lang(self.rebuild)

    def _load(self, value):
        self.levels = [list(l) for l in (value or []) if isinstance(l, list)]
        self.rebuild()

    def rebuild(self):
        while self.host.count():
            it = self.host.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        for i, names in enumerate(self.levels):
            self.host.addWidget(LevelBox(self, i, names))

    def _commit(self):
        self.store.set(self.path, [list(l) for l in self.levels if l] or [[]])
        self.levels = [l for l in self.levels if l] or [[]]
        self.rebuild()
        self.changed.emit()

    def add_level(self):
        self.levels.append([])
        self.store.set(self.path, [list(l) for l in self.levels])
        self.rebuild()

    def remove_level(self, i):
        if 0 <= i < len(self.levels): self.levels.pop(i)
        self._commit()

    def move_level(self, i, d):
        j = i + d
        if 0 <= i < len(self.levels) and 0 <= j < len(self.levels):
            self.levels[i], self.levels[j] = self.levels[j], self.levels[i]
            self._commit()

    def add_item(self, li, name):
        if name in self.levels[li]: return
        self.levels[li].append(name)
        self._commit()

    def remove_item(self, li, name):
        if name in self.levels[li]: self.levels[li].remove(name)
        self._commit()

    def move_item(self, name, li, idx):
        src = next((k for k, l in enumerate(self.levels) if name in l), None)
        if src is None: return
        old = self.levels[src].index(name)
        self.levels[src].remove(name)
        if src == li and old < idx: idx -= 1
        idx = max(0, min(idx, len(self.levels[li])))
        self.levels[li].insert(idx, name)
        self._commit()
