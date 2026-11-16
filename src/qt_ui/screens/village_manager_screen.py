"""
Screen 15 - Village manager: a computer-vision studio to teach the bot buttons and number regions.
Left: the live emulator screenshot (capture, zoom / pan, crosshair readout, resizable selection box).
Right: the trainable items by group with learned / not learned badges, preview of the saved template,
forget; screens the bot didn't recognise (load one to teach from it); routines (taught tap sequences).
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import Box, GlassCard, IconButton, StatusPill, Toggle, label, note
from ..widgets.roi_canvas import RoiCanvas
from .base import Screen, page

GROUP_KEYS = {"farm": "tg_farm", "army": "tg_army", "general": "tg_general", "collect": "tg_collect",
              "battle": "tg_battle", "custom": "tg_custom"}


class TeachItem(Box):
    def __init__(self, screen, item, learned):
        super().__init__(radius=10)
        self.screen, self.key = screen, item["key"]
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 7, 8, 7)
        h.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("ok" if learned else "dash_circle", 18, TOKENS["ok"] if learned else TOKENS["dim"]))
        h.addWidget(ic)
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(label(tr("tk_" + self.key) if tr("tk_" + self.key) != "tk_" + self.key else self.key))
        meta = learned or {}
        sub = tr("auto_badge") if meta.get("auto") else (tr("learned") if learned else tr("not_learned"))
        box.addWidget(label(sub, "dim"))
        h.addLayout(box, 1)
        self.thumb = QLabel()
        self.thumb.setFixedHeight(28)
        h.addWidget(self.thumb)
        if learned and item.get("kind") == "button":
            screen.api.get(f"/api/teach/template/{self.key}", self._thumb, raw=True)
        if learned:
            f = IconButton("trash", kind="ghost", icon_color=TOKENS["bad"], size=13, tip_key="forget")
            f.clicked.connect(lambda: screen.forget(self.key))
            h.addWidget(f)
        self.set_selected(False)

    def _thumb(self, data):
        if not data: return
        pm = QPixmap()
        pm.loadFromData(data)
        if not pm.isNull(): self.thumb.setPixmap(pm.scaledToHeight(28, Qt.SmoothTransformation))

    def set_selected(self, v):
        self.set_border(TOKENS["gold"] if v else TOKENS["border"])

    def mousePressEvent(self, e):
        self.screen.select_item(self.key)


class VillageManagerScreen(Screen):
    key, title_key, icon_name = "teach", "sub_teach", "hammer"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.catalog, self.taught, self.items = [], {}, {}
        self.current = None
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)
        self.root.addWidget(split, 1)

        # ---------------- studio (canvas)
        left = GlassCard("teach_title", "crosshair", "teach_sub", glow=True)
        tools = QHBoxLayout()
        cap = IconButton("camera", "capture_shot", kind="primary", size=15)
        cap.clicked.connect(self.capture)
        tools.addWidget(cap)
        for ic, tip, fn in (("zoomin", "zoom_in", lambda: self.canvas.zoom(1.25)), ("zoomout", "zoom_out", lambda: self.canvas.zoom(0.8)),
                            ("expand", "zoom_fit", lambda: self.canvas.fit())):
            b = IconButton(ic, size=15, tip_key=tip)
            b.clicked.connect(fn)
            tools.addWidget(b)
        tools.addStretch(1)
        self.coords = QLabel("X: —   Y: —")
        self.coords.setStyleSheet(f"font-family: 'JetBrains Mono'; color: {TOKENS['muted']};")
        tools.addWidget(self.coords)
        left.add(tools)
        self.canvas = RoiCanvas()
        self.canvas.setMinimumSize(640, 380)
        self.canvas.cursor_moved.connect(lambda x, y: self.coords.setText(f"X: {x}   Y: {y}"))
        self.canvas.selection_changed.connect(self._sel_changed)
        left.add(self.canvas, 1)
        bottom = QHBoxLayout()
        self.cur_label = label(key="draw_hint", role="sub", wrap=True)
        bottom.addWidget(self.cur_label, 1)
        self.save_btn = IconButton("save", "save_selection", kind="go", size=15)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_selection)
        bottom.addWidget(self.save_btn)
        left.add(bottom)
        split.addWidget(left)

        # ---------------- items + discovered + routines
        right_sa, rv = page(12)
        items = GlassCard("teach_items", "list", "teach_items_sub")
        self.items_box = QVBoxLayout()
        self.items_box.setSpacing(6)
        items.add(self.items_box)
        rv.addWidget(items)
        disc = GlassCard("auto_title", "sparkle", "auto_sub")
        self.disc_box = QVBoxLayout()
        self.disc_box.setSpacing(6)
        disc.add(self.disc_box)
        rv.addWidget(disc)
        rout = GlassCard("routines_title", "layers", "routines_sub")
        self.rout_box = QVBoxLayout()
        self.rout_box.setSpacing(8)
        rout.add(self.rout_box)
        rv.addWidget(rout)
        rv.addStretch(1)
        right_sa.setMinimumWidth(380)
        split.addWidget(right_sa)
        split.setSizes([900, 420])
        self.canvas.show_message(tr("no_shot"))
        self.store.loaded.connect(self.render_routines)
        on_lang(self.render_items)

    # ---------------------------------------------------------------- data
    def on_show(self):
        self.load()
        self.load_shot()

    def load(self):
        def got(r):
            if not isinstance(r, dict) or "catalog" not in r: return
            self.catalog, self.taught = r["catalog"], r.get("taught", {}) or {}
            self.render_items()
            self.render_routines()
        self.api.get("/api/teach", got)
        self.api.get(f"/api/discovered/{self.store.account}", self.render_discovered)

    def load_shot(self, tries=0):
        def got(data):
            if data and self.canvas.set_image(data):
                if self.current: self._show_saved(self.current)
            elif tries > 0:
                QTimer.singleShot(1200, lambda: self.load_shot(tries - 1))
            else:
                self.canvas.show_message(tr("no_shot"))
        self.api.get(f"/api/teach/capture/{self.store.account}?t={id(self)}", got, raw=True)

    def capture(self):
        def done(r):
            if not isinstance(r, dict) or not r.get("ok"):
                self.ctx.toast(tr("need_running"), "bad")
                return
            QTimer.singleShot(1500, lambda: self.load_shot(6))
        self.api.post(f"/api/teach/capture/{self.store.account}", {}, done)

    def render_items(self):
        while self.items_box.count():
            it = self.items_box.takeAt(0)
            w = it.widget()
            if w: w.deleteLater()
        self.items = {}
        groups = []
        for c in self.catalog:
            if c["group"] not in groups: groups.append(c["group"])
        for g in groups:
            self.items_box.addWidget(label(tr(GROUP_KEYS.get(g, g)), "h3"))
            for c in self.catalog:
                if c["group"] != g: continue
                it = TeachItem(self, c, self.taught.get(c["key"]))
                self.items[c["key"]] = it
                self.items_box.addWidget(it)
        if self.current in self.items: self.items[self.current].set_selected(True)

    def select_item(self, key):
        self.current = key
        for k, it in self.items.items(): it.set_selected(k == key)
        name = tr("tk_" + key)
        hint = tr("th_" + key)
        self.cur_label.setText(f"{name}: {hint}" if hint != "th_" + key else name)
        self.cur_label.setProperty("role", None)
        self._show_saved(key)
        self._sel_changed(self.canvas.selection())

    def _show_saved(self, key):
        for it in self.canvas.saved_items: self.canvas.scene_.removeItem(it)
        self.canvas.saved_items = []
        meta = self.taught.get(key)
        if meta and meta.get("rect"): self.canvas.show_saved(meta["rect"])

    def _sel_changed(self, sel):
        self.save_btn.setEnabled(bool(sel) and bool(self.current))

    def save_selection(self):
        rect = self.canvas.selection()
        if not rect or not self.current: return

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("taught_ok") if tr("taught_ok") != "taught_ok" else tr("saved"), "ok")
                self.canvas.clear_selection()
                self.load()
            else:
                self.ctx.toast((r or {}).get("error", tr("save_err")), "bad")
        self.api.post("/api/teach/save", {"id": self.store.account, "key": self.current, "rect": list(rect)}, done)

    def forget(self, key):
        self.api.post("/api/teach/forget", {"key": key}, lambda r: self.load())

    # ---------------------------------------------------------------- discovered screens
    def render_discovered(self, r):
        while self.disc_box.count():
            it = self.disc_box.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        items = (r or {}).get("items", []) if isinstance(r, dict) else []
        if not items:
            self.disc_box.addWidget(label(key="disc_empty", role="sub", wrap=True))
            return
        for d in items[:12]:
            row = Box(radius=10)
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 6, 8, 6)
            thumb = QLabel()
            thumb.setFixedSize(96, 54)
            thumb.setStyleSheet("background: #000; border-radius: 6px;")
            h.addWidget(thumb)
            if d.get("shot"):
                self.api.get(f"/api/discovered/{self.store.account}/img/{d['shot']}",
                             lambda data, t=thumb: self._set_thumb(t, data), raw=True)
            box = QVBoxLayout()
            box.setSpacing(0)
            words = ", ".join(d.get("words", [])[:4])
            box.addWidget(label(words or "—", wrap=True))
            act = d.get("action", "")
            box.addWidget(label(f"{tr('disc_pressed')} {act[4:]}" if act.startswith("tap:") else tr("disc_none"), "dim"))
            h.addLayout(box, 1)
            use = IconButton("crosshair", "disc_teach", size=13)
            use.clicked.connect(lambda _=False, f=d.get("full", ""): self.use_discovered(f))
            h.addWidget(use)
            self.disc_box.addWidget(row)

    def _set_thumb(self, label_w, data):
        if not data: return
        pm = QPixmap()
        pm.loadFromData(data)
        if not pm.isNull(): label_w.setPixmap(pm.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def use_discovered(self, full):
        self.api.post(f"/api/discovered/{self.store.account}/use", {"full": full}, lambda r: self.load_shot(2))

    # ---------------------------------------------------------------- routines
    def render_routines(self):
        while self.rout_box.count():
            it = self.rout_box.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        routines = self.store.S.get("routines", []) if self.store.S else []
        for ri, r in enumerate(routines):
            box = Box(radius=12)
            v = QVBoxLayout(box)
            v.setContentsMargins(12, 8, 12, 10)
            head = QHBoxLayout()
            head.addWidget(label(tr("rt_" + r.get("name", "")) if tr("rt_" + r.get("name", "")) != "rt_" + r.get("name", "") else r.get("name", ""), "h3"), 1)
            tg = Toggle()
            tg.setChecked(bool(r.get("enabled")))
            tg.toggled.connect(lambda val, i=ri: self._rt_set(i, "enabled", bool(val)))
            head.addWidget(tg)
            v.addLayout(head)
            for si, step in enumerate(r.get("steps", [])):
                sh = QHBoxLayout()
                n = QLabel(str(si + 1))
                n.setFixedSize(22, 20)
                n.setAlignment(Qt.AlignCenter)
                n.setStyleSheet(f"background: {TOKENS['violet']}; border-radius: 6px; color: white; font-weight: 700;")
                sh.addWidget(n)
                learned = step.get("key") in self.taught
                sh.addWidget(label(tr("tk_" + step.get("key", "")), None), 1)
                st_ic = QLabel()
                st_ic.setPixmap(icons.pixmap("ok" if learned else "warn", 15, TOKENS["ok"] if learned else TOKENS["warn"]))
                sh.addWidget(st_ic)
                rm = IconButton("x", kind="ghost", size=12, icon_color=TOKENS["muted"])
                rm.clicked.connect(lambda _=False, i=ri, s=si: self._rt_remove(i, s))
                sh.addWidget(rm)
                v.addLayout(sh)
            add = QHBoxLayout()
            combo = QComboBox()
            for c in self.catalog:
                if c.get("kind") == "button": combo.addItem(tr("tk_" + c["key"]), c["key"])
            add.addWidget(combo, 1)
            ab = IconButton("plus", "add", size=13)
            ab.clicked.connect(lambda _=False, i=ri, cb=combo: self._rt_add(i, cb.currentData()))
            add.addWidget(ab)
            v.addLayout(add)
            self.rout_box.addWidget(box)

    def _rt_set(self, i, field, value):
        self.store.S["routines"][i][field] = value
        self.store.changed()

    def _rt_remove(self, i, s):
        self.store.S["routines"][i]["steps"].pop(s)
        self.store.changed()
        self.render_routines()

    def _rt_add(self, i, key):
        if not key: return
        cat = next((c for c in self.catalog if c["key"] == key), {})
        self.store.S["routines"][i].setdefault("steps", []).append({"key": key, "multi": bool(cat.get("multi")), "wait": 0.8})
        self.store.changed()
        self.render_routines()
