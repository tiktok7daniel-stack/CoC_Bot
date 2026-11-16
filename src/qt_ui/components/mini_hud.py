"""
Clash Farmer mini HUD: a small always-on-top floating crystal orb (drag it anywhere on the screen).
Click it to expand a glass panel with four tabs:
 status   : bot state + start / stop / pause
 upgrades : the affordable items from the last village scan, each with a 1-tap upgrade
 timers   : the next running upgrades with live countdowns
 stats    : loot of the session
It reads the same data as the main window (poller + /api/village) so it costs nothing extra.
"""
import math, time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from .. import icons
from ..api import fmt_num, status_key
from ..i18n import tr
from ..theme import TOKENS
from ..widgets.controls import Chip, IconButton, StatusPill, label

ORB = 64


class Orb(QWidget):
    """Pulsing crimson crystal; emits nothing itself, the HUD handles clicks and drags."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(ORB, ORB)
        self.phase = 0.0
        self.color = QColor("#F5B740")

    def step(self):
        self.phase = (self.phase + 0.06) % (2 * math.pi)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = self.rect().center()
        pulse = 0.5 + 0.5 * math.sin(self.phase)
        halo = QRadialGradient(c, ORB / 2)
        col = QColor(self.color)
        col.setAlpha(int(90 + 80 * pulse))
        halo.setColorAt(0, col)
        halo.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(self.rect())
        r = QRectF(10, 10, ORB - 20, ORB - 20)
        body = QRadialGradient(r.center().x() - 8, r.center().y() - 10, r.width())
        body.setColorAt(0, QColor("#2A0A12"))
        body.setColorAt(1, QColor("#050508"))
        p.setBrush(body)
        p.setPen(QPen(QColor("#F5B740"), 1.6))
        p.drawEllipse(r)
        p.drawPixmap(int(r.left() + 6), int(r.top() + 6), icons.pixmap("crest", int(r.width() - 12)))
        p.end()


class Panel(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.fillPath(path, QColor(6, 5, 9, 238))
        sheen = QLinearGradient(r.topLeft(), r.bottomRight())
        sheen.setColorAt(0, QColor(255, 255, 255, 0x22))
        sheen.setColorAt(1, QColor(255, 255, 255, 0x06))
        p.fillPath(path, QBrush(sheen))
        g = QRadialGradient(r.right() - 40, r.top() + 20, 260)
        g.setColorAt(0, QColor(245, 183, 64, 60))
        g.setColorAt(1, QColor(245, 183, 64, 0))
        p.fillPath(path, QBrush(g))
        b = QLinearGradient(r.topLeft(), r.bottomRight())
        b.setColorAt(0, QColor(245, 183, 64, 210))
        b.setColorAt(0.5, QColor(245, 183, 64, 150))
        b.setColorAt(1, QColor(245, 183, 64, 30))
        p.setPen(QPen(QBrush(b), 1.3))
        p.drawPath(path)
        p.end()


class MiniHud(QWidget):
    def __init__(self, window):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.win = window
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Clash Farmer HUD")
        self.expanded = False
        self._drag = None
        self._moved = False
        self.village = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.orb = Orb(self)
        lay.addWidget(self.orb, 0, Qt.AlignRight | Qt.AlignTop)
        self.panel = Panel()
        self.panel.setFixedSize(320, 380)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(14, 12, 14, 12)
        pv.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(label("Clash Farmer", "h3"), 1)
        self.pill = StatusPill("stopped")
        head.addWidget(self.pill)
        pv.addLayout(head)
        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self.tab_btns = {}
        self.stack = QStackedWidget()
        for key, tk in (("status", "hud_status"), ("up", "hud_upgrades"), ("timers", "hud_timers"), ("stats", "hud_stats")):
            b = Chip(key=tk)
            b.clicked.connect(lambda _=False, k=key: self.select(k))
            tabs.addWidget(b)
            self.tab_btns[key] = b
        pv.addLayout(tabs)
        pv.addWidget(self.stack, 1)
        self.pages = {}
        for key in self.tab_btns:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 4, 0, 0)
            v.setSpacing(6)
            self.stack.addWidget(w)
            self.pages[key] = v
        # status page: big controls
        sv = self.pages["status"]
        self.state_lbl = label("", "sub", wrap=True)
        sv.addWidget(self.state_lbl)
        for icon_name, key, kind, action in (("play", "start", "go", "start"), ("pause", "pause_title", "warn", "pause"),
                                             ("stop", "stop", "stop", "stop")):
            b = IconButton(icon_name, key, kind)
            b.clicked.connect(lambda _=False, a=action: self.win.run_action(a))
            sv.addWidget(b)
        open_main = IconButton("expand", "hud_open_main", "ghost")
        open_main.clicked.connect(self.show_main)
        sv.addWidget(open_main)
        sv.addStretch(1)
        self.dyn = {k: [] for k in ("up", "timers", "stats")}
        lay.addWidget(self.panel)
        self.panel.hide()
        self.select("status")
        self.anim = QTimer(self)
        self.anim.timeout.connect(self.orb.step)
        self.anim.start(33)
        self.tick_t = QTimer(self)
        self.tick_t.timeout.connect(self.refresh)
        self.tick_t.start(1000)
        self._n = 0
        self.adjustSize()

    # ---------------------------------------------------------------- show / position
    def place(self):
        geo = self.screen().availableGeometry() if self.screen() else None
        if geo: self.move(geo.right() - self.width() - 24, geo.top() + 120)

    def show_main(self):
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()

    def toggle(self):
        self.expanded = not self.expanded
        right = self.geometry().right()
        self.panel.setVisible(self.expanded)
        self.adjustSize()
        self.move(right - self.width() + 1, self.y())
        if self.expanded: self.refresh(force=True)

    def select(self, key):
        for k, b in self.tab_btns.items(): b.setChecked(k == key)
        self.stack.setCurrentIndex(list(self.tab_btns).index(key))
        self.refresh(force=True)

    # ---------------------------------------------------------------- drag (click without moving toggles)
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.orb.geometry().contains(e.position().toPoint()):
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            pos = e.globalPosition().toPoint() - self._drag
            if (pos - self.pos()).manhattanLength() > 3: self._moved = True
            self.move(pos)

    def mouseReleaseEvent(self, e):
        if self._drag is not None and not self._moved: self.toggle()
        self._drag = None

    # ---------------------------------------------------------------- data
    def _clear(self, key):
        for w in self.dyn[key]: w.setParent(None); w.deleteLater()
        self.dyn[key] = []

    def _add(self, key, w):
        v = self.pages[key]
        v.insertWidget(v.count() - 1 if v.count() and v.itemAt(v.count() - 1).spacerItem() else v.count(), w)
        self.dyn[key].append(w)

    def refresh(self, force=False):
        acc = self.win.poller.account_state()
        k = status_key(acc)
        self.pill.set(k)
        self.orb.color = QColor({"running": "#10B981", "paused": "#F59E0B", "error": "#EF4444"}.get(k, "#F5B740"))
        self.state_lbl.setText(f"{self.win.store.account or '—'}  •  {tr('st_' + k)}")
        if not self.expanded: return
        self._n += 1
        cur = list(self.tab_btns)[self.stack.currentIndex()]
        if cur == "up" and (force or self._n % 10 == 0):
            a = self.win.store.account
            if a: self.win.api.get(f"/api/village/{a}", self._got_village)
        elif cur == "timers":
            self._fill_timers()
        elif cur == "stats" and (force or self._n % 5 == 0):
            self._fill_stats()

    def _got_village(self, d):
        if not isinstance(d, dict) or d.get("ok") is False: return
        self.village = d
        self._clear("up")
        items = [i for i in d.get("items", []) if i.get("available")][:6]
        if not items: self._add("up", label(tr("dk_no_items"), "dim", wrap=True))
        deck = self.win.screens.get("deck")
        for i in items:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label(i.get("name", "?")), 1)
            h.addWidget(label(fmt_num(i.get("cost")), "dim"))
            b = IconButton("bolt", None, "primary", size=13)
            b.setToolTip(tr("dk_upgrade_now"))
            b.clicked.connect(lambda _=False, n=i.get("name"): deck.upgrade(n) if deck else None)
            h.addWidget(b)
            self._add("up", row)
        if not self.pages["up"].count() or not self.pages["up"].itemAt(self.pages["up"].count() - 1).spacerItem():
            self.pages["up"].addStretch(1)

    def _fill_timers(self):
        if not self.village:
            a = self.win.store.account
            if a: self.win.api.get(f"/api/village/{a}", lambda d: (setattr(self, "village", d if isinstance(d, dict) else {}),))
            return
        from ..screens.upgrade_deck_screen import fmt_left
        self._clear("timers")
        now = time.time()
        ts = sorted(self.village.get("timers", []), key=lambda t: t.get("ends", 0))[:7]
        if not ts: self._add("timers", label(tr("dk_no_timers"), "dim", wrap=True))
        for t in ts:
            left = t.get("ends", 0) - now
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(label(t.get("name", "?")), 1)
            if left <= 0:
                seal = QLabel()
                seal.setPixmap(icons.pixmap("verified", 18))
                h.addWidget(seal)
            v = label(tr("dk_done") if left <= 0 else fmt_left(left), "num")
            v.setStyleSheet(f"color: {TOKENS['ok'] if left <= 0 else '#FFD36E'}; font-weight: 700;")
            h.addWidget(v)
            self._add("timers", row)
        if not self.pages["timers"].itemAt(self.pages["timers"].count() - 1).spacerItem(): self.pages["timers"].addStretch(1)

    def _fill_stats(self):
        self._clear("stats")
        st = self.win.poller.last.get("stats") or {}
        tot = st.get("totals") or {}
        for icon_name, key, val in (("swords", "hud_attacks", st.get("attacks", 0)), ("gold", "gold", tot.get("gold", 0)),
                                    ("elixir", "elixir", tot.get("elixir", 0)), ("dark", "dark", tot.get("dark", 0))):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, 16, "#F5B740"))
            h.addWidget(ic)
            h.addWidget(label(tr(key)), 1)
            h.addWidget(label(fmt_num(val), "num"))
            self._add("stats", row)
        if not self.pages["stats"].itemAt(self.pages["stats"].count() - 1).spacerItem(): self.pages["stats"].addStretch(1)
