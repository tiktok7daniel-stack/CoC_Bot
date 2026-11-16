"""
Clash Farmer - Upgrade Deck: what the bot knows about the village and instant control over it.
 - header: free builders, lab state, last scan, queued commands; rescan + batch wall upgrade
 - live timers: every running upgrade with a countdown and a progress bar (green when finished)
 - catalog: every upgradeable item from the last scan (name, cost, resource, affordable) filtered by
   category, each with "Upgrade now" (1-tap, the bot does it between its own steps) and "Pin to top"
   (moves it to the first priority level so the normal upgrade loop always picks it first)
Data: GET /api/village/<id>; commands: POST /api/village/<id>/command.
"""
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import icons
from ..api import fmt_num
from ..i18n import tr
from ..theme import TOKENS
from ..widgets.controls import Box, Chip, GlassCard, IconButton, NumField, StatusPill, label, note
from .base import Screen, grid, page

CATEGORIES = [
    ("all", "dk_all", None),
    ("walls", "dk_walls", ("wall",)),
    ("def", "dk_def", ("cannon", "archer", "mortar", "air defense", "wizard", "sweeper", "tesla", "bomb", "x-bow",
                       "inferno", "eagle", "scatter", "monolith", "spell tower", "multi", "ricochet", "firespitter",
                       "trap", "mine", "tower")),
    ("army", "dk_army", ("king", "queen", "warden", "champion", "prince", "barracks", "army camp", "spell factory",
                         "laboratory", "clan castle", "workshop", "pet house", "blacksmith", "hero")),
    ("res", "dk_res", ("gold mine", "collector", "drill", "storage", "town hall")),
]


def category_of(name):
    n = (name or "").lower()
    for key, _t, words in CATEGORIES[1:]:
        if any(w in n for w in words): return key
    return "other"


def fmt_left(sec):
    sec = int(max(0, sec))
    d, h, m, s = sec // 86400, (sec % 86400) // 3600, (sec % 3600) // 60, sec % 60
    return (f"{d}{tr('d_short')}  " if d else "") + f"{h:02d}:{m:02d}:{s:02d}"


def fmt_ago(sec):
    sec = int(max(0, sec))
    if sec < 60: return tr("dk_now")
    if sec < 3600: return f"{sec // 60} {tr('m_short')}"
    if sec < 86400: return f"{sec // 3600} {tr('h_short')}"
    return f"{sec // 86400} {tr('d_short')}"


class ProgressBar(QWidget):
    """Thin glass bar: crimson -> gold while running, emerald when finished."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(8)
        self.value, self.done = 0.0, False

    def set(self, value, done):
        self.value, self.done = max(0.0, min(1.0, value)), done
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 4, 4)
        p.fillPath(path, QColor(255, 255, 255, 18))
        w = r.width() * (1.0 if self.done else self.value)
        if w > 1:
            fill = QPainterPath()
            fr = QRectF(r.left(), r.top(), w, r.height())
            if self.layoutDirection() == Qt.RightToLeft: fr.moveRight(r.right())
            fill.addRoundedRect(fr, 4, 4)
            g = QLinearGradient(fr.topLeft(), fr.topRight())
            if self.done:
                g.setColorAt(0, QColor("#10B981")); g.setColorAt(1, QColor("#34D399"))
            else:
                g.setColorAt(0, QColor("#F5B740")); g.setColorAt(1, QColor("#F5B740"))
            p.fillPath(fill, g)
        p.end()


class TimerRow(Box):
    def __init__(self, t):
        super().__init__(radius=12)
        self.t = t
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 9, 12, 10)
        v.setSpacing(6)
        h = QHBoxLayout()
        self.ic = QLabel()
        h.addWidget(self.ic)
        name = label(t.get("name", "?"), "h3")
        h.addWidget(name, 1)
        self.left = label("", "num")
        h.addWidget(self.left)
        v.addLayout(h)
        self.bar = ProgressBar()
        v.addWidget(self.bar)
        self.tick()

    def tick(self):
        now = time.time()
        ends = float(self.t.get("ends", 0))
        total = float(self.t.get("total") or 0)
        left = ends - now
        done = left <= 0
        kind = self.t.get("kind", "builder")
        self.ic.setPixmap(icons.pixmap("verified", 20) if done else
                          icons.pixmap("flask" if kind == "lab" else "builder_hammer", 18, "#F5B740"))
        self.left.setText(tr("dk_done") if done else fmt_left(left))
        self.left.setStyleSheet(f"color: {TOKENS['ok'] if done else '#FFD36E'}; font-weight: 700;")
        self.bar.set(1 - left / total if total > 0 else 0.0, done)
        self.set_border("rgba(16,185,129,0.55)" if done else TOKENS["border"])


class ItemCard(Box):
    def __init__(self, screen, item, pinned):
        super().__init__(radius=14, top="#F5B740" if pinned else None)
        self.screen, self.item = screen, item
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        h = QHBoxLayout()
        h.addWidget(label(item.get("name", "?"), "h3"), 1)
        ok = item.get("available")
        pill = StatusPill("ok" if ok else "warn", tr("dk_affordable") if ok else tr("dk_short"))
        h.addWidget(pill)
        v.addLayout(h)
        c = QHBoxLayout()
        ic = QLabel()
        res = item.get("res") or "gold"
        ic.setPixmap(icons.pixmap(res if res in ("gold", "elixir", "dark") else "gold", 18,
                                  {"gold": "#FFD36E", "elixir": "#E879F9", "dark": "#A78BFA"}.get(res, "#FFD36E")))
        c.addWidget(ic)
        c.addWidget(label(fmt_num(item.get("cost")) if item.get("cost") else "—", "num"))
        c.addStretch(1)
        if pinned: c.addWidget(label("📌 " + tr("dk_pinned"), "dim"))
        v.addLayout(c)
        b = QHBoxLayout()
        up = IconButton("bolt", "dk_upgrade_now", "primary")
        up.clicked.connect(lambda: screen.upgrade(item.get("name")))
        b.addWidget(up, 1)
        pin = IconButton("map_pin", None, "ghost", tip_key="dk_pin")
        pin.clicked.connect(lambda: screen.pin(item.get("name")))
        b.addWidget(pin)
        v.addLayout(b)


class UpgradeDeckScreen(Screen):
    key, title_key, icon_name = "deck", "sub_deck", "bolt"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page()
        self.root.addWidget(sa)
        self.data = {}
        self.cat = "all"

        # ---------------- header: what the bot knows right now
        head = GlassCard("dk_title", "crown", "dk_sub", glow=True)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.k_builders = self._kpi(row, "builder_hammer", "dk_builders")
        self.k_lab = self._kpi(row, "flask", "dk_lab")
        self.k_running = self._kpi(row, "hourglass", "dk_running")
        self.k_scan = self._kpi(row, "clock", "dk_last_scan")
        head.add(row)
        act = QHBoxLayout()
        act.setSpacing(8)
        rescan = IconButton("refresh", "dk_rescan", "warn")
        rescan.clicked.connect(lambda: self.command("scan"))
        act.addWidget(rescan)
        act.addStretch(1)
        act.addWidget(label(key="dk_batch_walls"))
        self.wall_count = NumField(1, 500, 1)
        self.wall_count.setValue(10)
        self.wall_count.setFixedWidth(90)
        act.addWidget(self.wall_count)
        walls = IconButton("brick", "dk_batch_go", "primary")
        walls.clicked.connect(lambda: self.command("walls", count=self.wall_count.value()))
        act.addWidget(walls)
        head.add(act)
        self.pending = label("", "dim")
        head.add(self.pending)
        v.addWidget(head)

        # ---------------- timers + catalog side by side
        w, g = grid(2)
        g.setColumnStretch(0, 2)
        g.setColumnStretch(1, 3)
        tc = GlassCard("dk_timers", "hourglass", "dk_timers_sub")
        self.timer_box = QVBoxLayout()
        self.timer_box.setSpacing(8)
        tc.add(self.timer_box)
        self.no_timers = note("dk_no_timers")
        tc.add(self.no_timers)
        g.addWidget(tc, 0, 0)
        cc = GlassCard("dk_catalog", "layers", "dk_catalog_sub")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.chips = {}
        for key, tk, _w in CATEGORIES:
            ch = Chip(key=tk)
            ch.clicked.connect(lambda _=False, k=key: self.set_cat(k))
            chips.addWidget(ch)
            self.chips[key] = ch
        chips.addStretch(1)
        cc.add(chips)
        self.items_w = QWidget()
        self.items_g = QGridLayout(self.items_w)
        self.items_g.setContentsMargins(0, 4, 0, 0)
        self.items_g.setSpacing(10)
        cc.add(self.items_w)
        self.no_items = note("dk_no_items", "lightbulb")
        cc.add(self.no_items)
        g.addWidget(cc, 0, 1)
        v.addWidget(w)
        v.addStretch(1)
        self.set_cat("all")

        self.rows = []
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self.tick)
        self.ticker.start(1000)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh)
        self.poll.start(8000)
        self.store.account_changed.connect(lambda _a: self.refresh())
        QTimer.singleShot(400, self.refresh)

    def _kpi(self, row, icon_name, key):
        b = Box(radius=12)
        h = QHBoxLayout(b)
        h.setContentsMargins(12, 8, 12, 8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 22, "#F5B740"))
        h.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        val = label("—", "kpi")
        col.addWidget(val)
        col.addWidget(label(key=key, role="dim"))
        h.addLayout(col, 1)
        row.addWidget(b, 1)
        return val

    # ---------------------------------------------------------------- data
    def on_show(self):
        self.refresh()

    def refresh(self):
        acc = self.store.account
        if not acc: return
        self.api.get(f"/api/village/{acc}", self.got)

    def got(self, d):
        if not isinstance(d, dict) or d.get("ok") is False: return
        old_sig = (repr(self.data.get("items")), repr(self.data.get("timers")))
        self.data = d
        bf = d.get("builders_free")
        self.k_builders.setText("—" if bf is None else str(bf))
        lab = d.get("lab_free")
        self.k_lab.setText("—" if lab is None else (tr("dk_lab_free") if lab else tr("dk_lab_busy")))
        self.k_running.setText(str(sum(1 for t in d.get("timers", []) if t.get("ends", 0) > time.time())))
        t = d.get("t") or 0
        self.k_scan.setText(fmt_ago(time.time() - t) if t else tr("dk_never"))
        n = len(d.get("pending") or [])
        self.pending.setText(tr("dk_pending").format(n=n) if n else "")
        if (repr(d.get("items")), repr(d.get("timers"))) != old_sig: self.rebuild()

    def rebuild(self):
        # timers
        for r in self.rows: r.setParent(None); r.deleteLater()
        self.rows = []
        timers = sorted(self.data.get("timers", []), key=lambda t: t.get("ends", 0))
        for t in timers[:12]:
            r = TimerRow(t)
            self.timer_box.addWidget(r)
            self.rows.append(r)
        self.no_timers.setVisible(not self.rows)
        self.fill_items()

    def fill_items(self):
        while self.items_g.count():
            it = self.items_g.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        pinned = {n.lower() for n in (self.store.get("priorities.home_base", []) or [[]])[0]} if self.store.get("priorities.home_base") else set()
        items = [i for i in self.data.get("items", []) if self.cat == "all" or category_of(i.get("name")) == self.cat]
        items.sort(key=lambda i: (not i.get("available"), i.get("name", "").lower() not in pinned, i.get("cost") or 0))
        for n, i in enumerate(items[:60]):
            self.items_g.addWidget(ItemCard(self, i, i.get("name", "").lower() in pinned), n // 2, n % 2)
        self.no_items.setVisible(not items)

    def set_cat(self, key):
        self.cat = key
        for k, ch in self.chips.items(): ch.setChecked(k == key)
        self.fill_items()

    def tick(self):
        if not self.isVisible(): return
        for r in self.rows: r.tick()

    # ---------------------------------------------------------------- actions
    def command(self, cmd, **kw):
        acc = self.store.account
        if not acc: return

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("dk_queued_run" if r.get("running") else "dk_queued_idle"), "ok")
                self.refresh()
            else:
                self.ctx.toast(tr("dk_failed"), "bad")
        self.api.post(f"/api/village/{acc}/command", dict(kw, cmd=cmd), done)

    def upgrade(self, name):
        if name: self.command("upgrade", name=name)

    def pin(self, name):
        """Move the item to the first priority level (the regular upgrade loop then always tries it first)."""
        if not name: return
        levels = [list(l) for l in (self.store.get("priorities.home_base") or [])]
        levels = [[x for x in l if x.lower() != name.lower()] for l in levels]
        levels = [l for l in levels if l]
        levels.insert(0, [name])
        self.store.set("priorities.home_base", levels)
        self.store.set("tasks.home_base", True)
        self.store.set("tasks.home_base_priority", True)
        self.store.save(silent=True)
        self.ctx.toast(tr("dk_pinned_ok").format(name=name), "ok")
        self.fill_items()
