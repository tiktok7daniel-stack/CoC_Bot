"""
Screens 4-8 - Attack & farming, five sub-tabs:
 plans  : battle recorder + recordings, single-point option, the attack loadouts (formation cards)
 search : storage protection + loot filter
 attack : home / builder attacks per cycle, walls between farming attacks
 army   : picture gallery of troops / spells / sieges / pets + deployment timing
 end    : battle end method, leave delay, smart end, hard timeout
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QVBoxLayout, QWidget

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import (Box, Combo, FloatField, GlassCard, IconButton, NumField, StatusPill, Toggle, bind_combo,
                                bind_num, bind_toggle, combo_row, float_row, form_row, label, note, num_row, retext,
                                toggle_row)
from ..widgets.unit_grid import UnitGallery
from .base import Screen, grid

WHERE = [("sides", "w_sides"), ("left", "w_left"), ("right", "w_right"), ("bottom", "w_bottom")]
SPELLS_WHERE = [("center", "w_center"), ("none", "w_none")]


class PlanCard(Box):
    """One attack loadout. Edits go straight into store.S["plans"][i]."""

    def __init__(self, screen, i):
        super().__init__(radius=18)
        self.screen, self.i = screen, i
        store = screen.store
        p = store.S["plans"][i]
        active = store.S.get("active_plan") == p.get("name")
        if active: self.set_border(TOKENS["purple"])
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(2)
        head = QHBoxLayout()
        num = QLabel(str(i + 1))
        num.setFixedSize(28, 24)
        num.setAlignment(Qt.AlignCenter)
        num.setStyleSheet(f"background: {TOKENS['violet']}; color: white; border-radius: 7px; font-weight: 800;")
        head.addWidget(num)
        self.name = QLineEdit(p.get("name", ""))
        self.name.setMaximumWidth(220)
        self.name.editingFinished.connect(self._rename)
        head.addWidget(self.name, 1)
        if active:
            head.addWidget(StatusPill("ok", tr("pl_active")))
        else:
            use = IconButton("check", "pl_use", kind="primary", size=13)
            use.clicked.connect(lambda: screen.set_active(p.get("name", "")))
            head.addWidget(use)
        v.addLayout(head)
        rec = QComboBox()
        rec.addItem(tr("pl_rec_none"), "")
        for r in screen.recordings: rec.addItem(r["name"], r["name"])
        j = rec.findData(p.get("recording", ""))
        rec.setCurrentIndex(max(0, j))
        rec.activated.connect(lambda _i: self._set("recording", rec.currentData()))
        rec.setMinimumWidth(180)
        v.addWidget(form_row("pl_rec", "pl_rec_sub", rec))
        army = QLineEdit(p.get("army", ""))
        army.setPlaceholderText(tr("pl_army_ph"))
        army.setFixedWidth(180)
        army.textEdited.connect(lambda t: self._set("army", t))
        v.addWidget(form_row("pl_army", "pl_army_sub", army))
        macro = QComboBox()
        macro.addItem(tr("al_none"), "")
        for a in getattr(screen, "armies", []): macro.addItem(a["name"], a["name"])
        j = macro.findData(p.get("army_macro", ""))
        macro.setCurrentIndex(max(0, j))
        macro.activated.connect(lambda _i: self._set("army_macro", macro.currentData()))
        macro.setMinimumWidth(180)
        v.addWidget(form_row("al_plan", "al_plan_sub", macro))
        for key, field, items in (("pl_troops", "troops_where", WHERE), ("pl_heroes", "heroes_where", WHERE),
                                  ("pl_clan", "clan_where", WHERE), ("pl_spells", "spells_where", SPELLS_WHERE)):
            c = Combo(items, 220)
            c.set_value(p.get(field, items[0][0]))
            c.currentIndexChanged.connect(lambda _i, c=c, f=field: self._set(f, c.value()))
            v.addWidget(form_row(key, None, c))
        for key, sub, field in (("pl_spells_delay", "pl_spells_delay_sub", "spells_delay"),
                                ("pl_abil", "pl_abil_sub", "abilities_after"), ("pl_wave_after", None, "second_wave_after")):
            f = FloatField(0, 600, 1, 90)
            f.setValue(float(p.get(field, 0) or 0))
            f.valueChanged.connect(lambda val, fl=field: self._set(fl, val))
            v.addWidget(form_row(key, sub, f, "seconds"))
        wave = QLineEdit(p.get("second_wave_spells", ""))
        wave.setLayoutDirection(Qt.LeftToRight)
        wave.setFixedWidth(180)
        wave.setPlaceholderText("healing, rage")
        v.addWidget(form_row("pl_wave", "pl_wave_sub2", wave))
        picker = UnitGallery(screen.api, ("spells",), selectable=True, size=40, searchable=False)
        picker.set_selected([x.strip() for x in str(p.get("second_wave_spells", "")).split(",") if x.strip()])
        picker.selection_changed.connect(lambda names: (wave.setText(",".join(names)), self._set("second_wave_spells", ",".join(names))))
        wave.textEdited.connect(lambda t: (self._set("second_wave_spells", t), picker.set_selected([x.strip() for x in t.split(",") if x.strip()])))
        v.addWidget(picker)

    def plan(self):
        return self.screen.store.S["plans"][self.i]

    def _set(self, field, value):
        self.plan()[field] = value
        self.screen.store.changed()

    def _rename(self):
        new = self.name.text().strip()
        p = self.plan()
        old = p.get("name", "")
        if not new or new == old: return
        p["name"] = new
        S = self.screen.store.S
        if S.get("active_plan") == old: S["active_plan"] = new
        self.screen.store.changed()


class AttackScreen(Screen):
    key, title_key, icon_name = "atk", "sub_atk", "swords"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.recordings = []
        self.armies = []
        L = self.make_tabs([("plans", "as_plans", "layers"), ("search", "as_search", "search"), ("attack", "as_attack", "swords"),
                            ("army", "as_army", "army"), ("end", "as_end", "flag")])
        st = self.store

        # ======================= plans: recorder
        rec = GlassCard("rec_title", "video", "rec_sub", glow=True)
        row = QHBoxLayout()
        row.addWidget(label(key="rec_name"), 0)
        self.rec_name = QLineEdit()
        self.rec_name.setPlaceholderText("meteor_golems")
        self.rec_name.setFixedWidth(220)
        row.addWidget(self.rec_name)
        start = IconButton("record", "rec_start", kind="go", size=15)
        start.clicked.connect(self.start_recording)
        row.addWidget(start)
        row.addStretch(1)
        rec.add(row)
        self.rec_live = QLabel("")
        self.rec_live.setWordWrap(True)
        self.rec_live.hide()
        rec.add(self.rec_live)
        self.rec_list = QVBoxLayout()
        self.rec_list.setSpacing(6)
        rec.add(self.rec_list)
        rec.add(note("rec_note", "warn", TOKENS["warn"]))
        L["plans"].addWidget(rec)
        # ======================= plans: loadouts
        plans = GlassCard("pl_title", "layers", "pl_sub")
        self.classic = Box(radius=18)
        ch = QHBoxLayout(self.classic)
        ch.setContentsMargins(14, 12, 14, 12)
        self.classic_ic = QLabel()
        ch.addWidget(self.classic_ic)
        cb = QVBoxLayout()
        cb.setSpacing(0)
        cb.addWidget(label(key="pl_classic", role="h3"))
        cb.addWidget(label(key="pl_classic_sub", role="sub"))
        ch.addLayout(cb, 1)
        self.classic_btn = IconButton("check", "pl_use", size=13)
        self.classic_btn.clicked.connect(lambda: self.set_active(""))
        ch.addWidget(self.classic_btn)
        plans.add(self.classic)
        self.plans_host = QWidget()
        self.plans_grid = QGridLayout(self.plans_host)
        self.plans_grid.setContentsMargins(0, 0, 0, 0)
        self.plans_grid.setSpacing(12)
        plans.add(self.plans_host)
        plans.add(note("pl_note"))
        L["plans"].addWidget(plans)
        L["plans"].addStretch(1)

        # ======================= search
        w, g = grid(2)
        lf = GlassCard("lf_title", "filter", "lf_every_sub")
        lf.add(label(key="lf_every", role="sub", wrap=True))
        self.lf_state = label("", "sub", wrap=True)
        lf.add(self.lf_state)
        g.addWidget(lf, 0, 0)
        L["search"].addWidget(w)
        L["search"].addStretch(1)

        # ======================= attack
        w, g = grid(2)
        atk = GlassCard("attack_title", "swords", "attack_sub")
        atk.add(toggle_row(st, "t_home_attacks", "tasks.home_attacks"))
        atk.add(num_row(st, "home_attacks_n", "attack.home_attacks_per_cycle", "home_attacks_n_sub", "attacks_unit", 1, 50, 1, 90))
        atk.add(toggle_row(st, "t_builder_attacks", "tasks.builder_attacks"))
        atk.add(num_row(st, "builder_attacks_n", "attack.builder_attacks_per_cycle", None, "attacks_unit", 0, 50, 1, 90))
        g.addWidget(atk, 0, 0)
        farm = GlassCard("farm_title", "brick", "farm_sub")
        farm.add(toggle_row(st, "farm_on", "attack.farm.enabled", "farm_on_sub"))
        farm.add(toggle_row(st, "farm_max_walls", "attack.farm.max_walls", "farm_max_walls_sub"))
        farm.add(toggle_row(st, "wall_farming", "walls.during_farming", "wall_farming_sub"))
        g.addWidget(farm, 0, 1)
        L["attack"].addWidget(w)
        L["attack"].addStretch(1)

        # ======================= army
        from ..widgets.army_library import ArmyLibrary
        lib_card = GlassCard("al_title", "eye", "al_sub", glow=True)
        self.army_lib = ArmyLibrary(ctx)
        lib_card.add(self.army_lib)
        L["army"].addWidget(lib_card)
        timing = GlassCard("army_title", "army", "army_sub")
        timing.add(float_row(st, "deploy_time", "attack.troop_deploy_time", "deploy_time_sub", "seconds", 0, 30, 0.5))
        rng = QHBoxLayout()
        a = bind_num(st, NumField(0, 100, 1, 70), "attack.slot_first")
        b = bind_num(st, NumField(0, 100, 1, 70), "attack.slot_last")
        rng.addWidget(a)
        rng.addWidget(QLabel("—"))
        rng.addWidget(b)
        timing.add(form_row("slot_range", "slot_range_sub", rng))
        timing.add(toggle_row(st, "exclude_cc", "attack.exclude_clan_troops"))
        timing.add(float_row(st, "hero_retap", "attack.hero_retap", "hero_retap_sub", "seconds", 0, 120, 1))
        L["army"].addWidget(timing)
        gal = GlassCard("ug_title", "image", "ug_sub")
        gal.add(UnitGallery(self.api))
        L["army"].addWidget(gal)
        L["army"].addStretch(1)

        # ======================= end
        end = GlassCard("battle_end_title", "flag", "battle_end_sub")
        end.add(combo_row(st, "battle_end", "attack.battle_end",
                          [("wait", "be_wait"), ("restart", "be_restart"), ("leave", "be_leave")], "battle_end_hint", 340))
        end.add(float_row(st, "leave_after", "attack.leave_after", "leave_after_sub", "seconds", 0, 180, 1))
        end.add(toggle_row(st, "smart_end", "attack.smart_end", "smart_end_sub"))
        end.add(num_row(st, "smart_end_after", "attack.smart_end_after", "smart_end_after_sub", "seconds", 5, 120, 5, 90))
        end.add(num_row(st, "surrender_after", "attack.surrender_after", "surrender_after_sub", "seconds", 0, 600, 5, 90))
        L["end"].addWidget(end)
        L["end"].addStretch(1)

        st.loaded.connect(self.render_plans)
        st.on_change(self._update_lf)
        self.poller.record_status.connect(self.on_record_status)
        on_lang(self.render_plans)
        self.load_recordings()

    # ---------------------------------------------------------------- recordings
    def on_show(self):
        self.load_recordings()
        self.army_lib.load()

    def _got_armies(self, r):
        if isinstance(r, dict) and "items" in r:
            self.armies = r["items"]
            self.render_plans()

    def load_recordings(self):
        self.api.get("/api/armies", self._got_armies)

        def got(r):
            if not isinstance(r, dict) or "items" not in r: return
            self.recordings = r["items"]
            self.render_recordings()
            self.render_plans()
        self.api.get("/api/recordings", got)

    def render_recordings(self):
        while self.rec_list.count():
            it = self.rec_list.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        if not self.recordings:
            self.rec_list.addWidget(label(key="rec_empty", role="sub"))
            return
        for r in self.recordings:
            row = Box(radius=13)
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 6, 8, 6)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("film", 18, "#E9D3A6"))
            h.addWidget(ic)
            h.addWidget(label(r["name"], "h3"))
            h.addWidget(label(f"{r.get('touches', 0)} {tr('rec_taps')} · {int(r.get('duration') or 0)} {tr('seconds')}", "dim"), 1)
            d = IconButton("trash", "rec_delete", kind="ghost", icon_color=TOKENS["bad"], size=14)
            d.clicked.connect(lambda _=False, n=r["name"]: self.delete_recording(n))
            h.addWidget(d)
            self.rec_list.addWidget(row)

    def delete_recording(self, name):
        if QMessageBox.question(self, "Clash Farmer", tr("rec_confirm")) != QMessageBox.Yes: return
        self.api.post("/api/recordings/delete", {"name": name}, lambda r: self.load_recordings())

    def start_recording(self):
        name = self.rec_name.text().strip()
        if not name:
            self.ctx.toast(tr("rec_need_name"), "bad")
            return

        def done(r):
            if not isinstance(r, dict) or not r.get("ok"):
                self.ctx.toast(tr("rec_need_name"), "bad")
                return
            self.ctx.toast(tr("rec_started"), "ok")
            self.poller.watch_recording = True
            self._rec_shown = ""
            self.poller.refresh("record_status")
        self.api.post(f"/api/record/{self.store.account}", {"name": name}, done)

    def on_record_status(self, st):
        text = st.get("text")
        if not text: return
        col = {"failed": TOKENS["bad"], "saved": TOKENS["ok"], "recording": TOKENS["bad"]}.get(text, TOKENS["info"])
        self.rec_live.setText(tr("rs_" + text))
        self.rec_live.setStyleSheet(f"color: {col}; font-size: 11pt; font-weight: 700;")
        self.rec_live.show()
        if text == "recording" and getattr(self, "_rec_shown", "") != "recording":
            self.ctx.banner(tr("rs_banner"), "rec", "record")
        self._rec_shown = text
        if text in ("saved", "failed"):
            self.poller.watch_recording = False
            self.load_recordings()

    # ---------------------------------------------------------------- loadouts
    def set_active(self, name):
        self.store.S["active_plan"] = name
        self.store.changed()
        self.render_plans()

    def render_plans(self):
        S = self.store.S
        if not S: return
        active = S.get("active_plan", "")
        self.classic.set_border(TOKENS["purple"] if not active else TOKENS["border"])
        self.classic_ic.setPixmap(icons.pixmap("ok" if not active else "dash_circle", 20, TOKENS["purple"] if not active else TOKENS["dim"]))
        self.classic_btn.setVisible(bool(active))
        while self.plans_grid.count():
            it = self.plans_grid.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        for i, _p in enumerate(S.get("plans", [])):
            self.plans_grid.addWidget(PlanCard(self, i), i // 2, i % 2)
        self._update_lf()

    def _update_lf(self):
        """Loot filter needs the Next button and the enemy loot numbers learned (done automatically)."""
        self.lf_state.setText("")             # no loot filter any more: every base is attacked
        return
        ok = all(k in self._taught for k in ("next_button", "enemy_gold"))
        self.lf_state.setText(tr("lf_ready") if ok else tr("lf_need"))
        self.lf_state.setProperty("role", "ok" if ok else "warn")
        self.lf_state.style().unpolish(self.lf_state)
        self.lf_state.style().polish(self.lf_state)

    def on_sub(self, key):
        if key == "search":
            def got(r):
                if isinstance(r, dict) and "taught" in r:
                    self._taught = r["taught"]
                    self._update_lf()
            self.api.get("/api/teach", got)
