"""
"What do you want to do today?" — shown as soon as the bot has the game open (once a day per account),
and any time from the home page ("Today's plan").
 - the account (picture + name) it is about
 - quick choices: as usual / farm only / upgrades only / nothing today
 - or pick exactly: attack & farm, buildings, walls, lab, heroes & pets, builder base (big toggle cards)
 - a countdown: without an answer the bot does the usual
"""
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QDialog, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from .. import icons
from ..i18n import tr
from ..theme import TOKENS, ui_font
from ..widgets.avatar import Avatar, display_name
from ..widgets.controls import IconButton, label

ITEMS = [("attack", "swords", "tp_attack", "tp_attack_sub"), ("buildings", "castle", "tp_buildings", "tp_buildings_sub"),
         ("walls", "brick", "tp_walls", "tp_walls_sub"), ("lab", "flask", "tp_lab", "tp_lab_sub"),
         ("heroes", "crown", "tp_heroes", "tp_heroes_sub"), ("builder_base", "moon", "tp_bb", "tp_bb_sub")]
PRESETS = {"usual": None, "farm": {"attack": True, "walls": True},
           "upgrades": {"buildings": True, "walls": True, "lab": True, "heroes": True}}


class Tile(QAbstractButton):
    """Big selectable card: icon, title, one line; gold edge + check seal when chosen."""

    def __init__(self, key, icon_name, title_key, sub_key):
        super().__init__()
        self.key, self.icon_name, self.title_key, self.sub_key = key, icon_name, title_key, sub_key
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(96)
        self.setMinimumWidth(200)
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        on = self.isChecked()
        if on:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(245, 183, 64, 52))
            g.setColorAt(1, QColor(245, 183, 64, 12))
            p.fillPath(path, g)
        else:
            p.fillPath(path, QColor(255, 255, 255, 14 if self._hover else 7))
        p.setPen(QPen(QColor(245, 183, 64, 200) if on else QColor(255, 255, 255, 40 if self._hover else 20), 1.4 if on else 1))
        p.drawPath(path)
        rtl = self.layoutDirection() == Qt.RightToLeft
        ic = icons.pixmap(self.icon_name, 30, TOKENS["accent"] if on else TOKENS["muted"])
        ix = r.right() - 50 if rtl else r.left() + 18
        p.drawPixmap(int(ix), int(r.top() + 18), ic)
        if on:
            seal = icons.pixmap("verified", 22)
            p.drawPixmap(int(r.left() + 12 if rtl else r.right() - 34), int(r.top() + 10), seal)
        tx = QRectF(r.left() + 16, r.top() + 54, r.width() - 32, 22)
        p.setPen(QColor(TOKENS["accent_hi"] if on else TOKENS["text"]))
        p.setFont(ui_font(11.5, 800))
        p.drawText(tx, (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter, tr(self.title_key))
        p.setPen(QColor(TOKENS["muted"]))
        p.setFont(ui_font(8.5))
        p.drawText(QRectF(r.left() + 16, r.top() + 74, r.width() - 32, 18), (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter,
                   tr(self.sub_key))
        p.end()


class TodayDialog(QDialog):
    chosen = Signal(str, dict)

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.acc = ""
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.setFixedWidth(760)
        v = QVBoxLayout(self)
        v.setContentsMargins(30, 26, 30, 24)
        v.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(14)
        self.avatar = Avatar("", 64)
        head.addWidget(self.avatar)
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.title = label("", "h1")
        self.title.setStyleSheet("font-size: 19pt; font-weight: 800;")
        tbox.addWidget(self.title)
        self.sub = label(key="tp_sub", role="sub", wrap=True)
        tbox.addWidget(self.sub)
        head.addLayout(tbox, 1)
        v.addLayout(head)
        # quick choices
        q = QHBoxLayout()
        q.setSpacing(8)
        for key, tk, ic in (("usual", "tp_usual", "refresh"), ("farm", "tp_farm", "swords"), ("upgrades", "tp_upgrades", "hammer"),
                            ("nothing", "tp_nothing", "pause")):
            b = IconButton(ic, tk, "chip", size=14)
            b.setCheckable(False)
            b.clicked.connect(lambda _=False, k=key: self.preset(k))
            q.addWidget(b)
        q.addStretch(1)
        v.addLayout(q)
        v.addWidget(label(key="tp_or_pick", role="overline"))
        g = QGridLayout()
        g.setSpacing(10)
        self.tiles = {}
        for i, (key, ic, tk, sk) in enumerate(ITEMS):
            t = Tile(key, ic, tk, sk)
            g.addWidget(t, i // 3, i % 3)
            self.tiles[key] = t
        v.addLayout(g)
        foot = QHBoxLayout()
        self.count = label("", "dim")
        foot.addWidget(self.count, 1)
        self.go = IconButton("play", "tp_go", "primary", size=16)
        self.go.setMinimumHeight(46)
        self.go.setMinimumWidth(200)
        self.go.clicked.connect(self.confirm)
        foot.addWidget(self.go)
        v.addLayout(foot)
        self.left = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 28, 28)
        p.fillPath(path, QColor(13, 13, 18, 252))
        glow = QLinearGradient(r.topLeft(), r.bottomLeft())
        glow.setColorAt(0, QColor(245, 183, 64, 30))
        glow.setColorAt(0.3, QColor(245, 183, 64, 0))
        p.fillPath(path, glow)
        p.setPen(QPen(QColor(245, 183, 64, 130), 1.3))
        p.drawPath(path)
        p.end()

    # ---------------------------------------------------------------- open
    def open_for(self, acc, left=None, plan=None):
        self.acc = acc
        self.avatar.set_account(acc)
        self.title.setText(tr("tp_title").format(name=display_name(self.win.store, acc)))
        last = (plan or {}).get("do") or self.win.store.APP.get("last_plan_do") or {}
        mode = (plan or {}).get("mode")
        for k, t in self.tiles.items():
            t.setChecked(True if mode in (None, "usual") and not last else bool(last.get(k, mode in (None, "usual"))))
        self.left = int(left) if left else 0
        self.count.setText("")
        if self.left: self.timer.start(1000)
        self._tick(first=True)
        self.adjustSize()
        par = self.win.geometry()
        self.move(par.center().x() - self.width() // 2, par.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    def _tick(self, first=False):
        if not self.left:
            self.count.setText("")
            return
        if not first: self.left -= 1
        if self.left <= 0:
            self.timer.stop()
            self.count.setText(tr("tp_auto_done"))
            QTimer.singleShot(1200, self.hide)
            return
        self.count.setText(tr("tp_countdown").format(s=self.left))

    # ---------------------------------------------------------------- answer
    def preset(self, key):
        if key == "nothing":
            self.send("nothing", {})
            return
        if key == "usual":
            self.send("usual", {})
            return
        on = PRESETS[key]
        for k, t in self.tiles.items(): t.setChecked(bool(on.get(k)))
        self.confirm()

    def confirm(self):
        do = {k: t.isChecked() for k, t in self.tiles.items()}
        if not any(do.values()):
            self.send("nothing", {})
        elif all(do.values()):
            self.send("usual", do)
        else:
            self.send("custom", do)

    def send(self, mode, do):
        self.timer.stop()
        self.win.store.APP["last_plan_do"] = do
        self.chosen.emit(self.acc, {"mode": mode, "do": do})
        self.hide()


class TodayPlanner:
    """Polls for bots that ask, shows the dialog, posts the answer."""

    def __init__(self, win):
        self.win = win
        self.dialog = TodayDialog(win)
        self.dialog.chosen.connect(self._answer)
        self.timer = QTimer(win)
        self.timer.timeout.connect(self.poll)
        self.timer.start(3000)
        self._shown = set()

    def poll(self):
        if self.dialog.isVisible(): return
        self.win.api.get("/api/plan_ask", self._got)

    def _got(self, r):
        if not isinstance(r, dict) or self.dialog.isVisible(): return
        for a in r.get("asking", []):
            key = (a["id"], int(a.get("since", 0)))
            if key in self._shown: continue
            self._shown.add(key)
            self.dialog.open_for(a["id"], a.get("left"))
            if self.win.isMinimized(): self.win.showNormal()
            try:
                self.win.desktop_notify(tr("tp_notify_title"), tr("tp_notify").format(name=display_name(self.win.store, a["id"])), "calendar")
            except Exception:
                pass
            return

    def edit(self, acc=None):
        acc = acc or self.win.store.account
        self.win.api.get(f"/api/plan/{acc}", lambda r: self.dialog.open_for(acc, None, (r or {}).get("plan")))

    def _answer(self, acc, body):
        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.win.banner.show_msg(tr("tp_saved_" + body["mode"]), "ok", "calendar")
                dash = self.win.screens.get("dash")
                if dash is not None and hasattr(dash, "refresh_plan"): dash.refresh_plan()
            else:
                self.win.toast.show_msg(tr("dk_failed"), "bad")
        self.win.api.post(f"/api/plan/{acc}", body, done)
