"""
Screens 11-14 - Main village upgrades, four sub-tabs:
 walls     : wall automation + smart budget reserve
 buildings : buildings / heroes / builder apprentice, priority mode, limits, priority levels
 lab       : laboratory + lab assistant, priority levels
 pets      : pet house, priority levels
"""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit
from PySide6.QtCore import Qt

from ..i18n import tr
from ..widgets.controls import GlassCard, IconButton, bind_line, form_row, label, note, num_row, toggle_row
from ..widgets.tier_editor import TierEditor
from .base import Screen, grid


class VillageScreen(Screen):
    key, title_key, icon_name = "upg", "sub_upg", "home"

    def __init__(self, ctx):
        super().__init__(ctx)
        st = self.store
        L = self.make_tabs([("walls", "walls", "brick"), ("buildings", "buildings", "castle"),
                            ("lab", "lab", "flask"), ("pets", "pets", "paw"), ("official", "ca_tab", "id")])

        # ---------------- walls
        w, g = grid(2)
        wall = GlassCard("wall_auto", "brick", "wall_auto_sub")
        wall.add(toggle_row(st, "wall_enabled", "walls.enabled"))
        wall.add(toggle_row(st, "wall_farming", "walls.during_farming", "wall_farming_sub"))
        wall.add(num_row(st, "run_every", "walls.every_cycles", None, "cycles", 1, 100, 1, 90))
        wall.add(num_row(st, "max_walls_run", "walls.max_per_run", None, "walls_unit", 0, 500, 1, 90))
        wall.add(note("wall_note"))
        g.addWidget(wall, 0, 0)
        bud = GlassCard("smart_budget", "gold", "smart_budget_sub")
        bud.add(toggle_row(st, "budget_enabled", "budget.enabled"))
        bud.add(num_row(st, "keep_gold", "budget.keep_gold", None, None, 0, 10**9, 100000, 150))
        bud.add(num_row(st, "keep_elixir", "budget.keep_elixir", None, None, 0, 10**9, 100000, 150))
        for k in ("bf1", "bf2", "bf3"): bud.add(note(k, "check"))
        g.addWidget(bud, 0, 1)
        L["walls"].addWidget(w)
        L["walls"].addStretch(1)

        # ---------------- buildings
        w, g = grid(2)
        b = GlassCard("home_upgrades", "castle", "home_upgrades_sub")
        b.add(toggle_row(st, "t_home_base", "tasks.home_base"))
        b.add(toggle_row(st, "t_heroes", "tasks.heroes"))
        b.add(toggle_row(st, "t_builder_apprentice", "tasks.builder_apprentice"))
        b.add(toggle_row(st, "use_priority", "tasks.home_base_priority", "use_priority_sub"))
        b.add(toggle_row(st, "from_top", "upgrades.start_from_menu_top"))
        b.add(num_row(st, "max_upgrades_cycle", "upgrades.max_per_cycle", None, None, 1, 100, 1, 90))
        b.add(num_row(st, "up_every", "upgrades.every_cycles", "up_every_sub", "cycles", 1, 50, 1, 90))
        b.add(num_row(st, "open_builders", "upgrades.open_home_builders", "open_builders_sub", None, 0, 6, 1, 80))
        g.addWidget(b, 0, 0)
        pr = GlassCard("priority_order", "list", "priority_sub")
        pr.add(TierEditor(st, "priorities.home_base", "home_base"))
        g.addWidget(pr, 0, 1)
        L["buildings"].addWidget(w)
        L["buildings"].addStretch(1)

        # ---------------- lab
        w, g = grid(2)
        lab = GlassCard("lab", "flask", "lab_sub")
        lab.add(toggle_row(st, "t_home_lab", "tasks.home_lab"))
        lab.add(toggle_row(st, "t_lab_assistant", "tasks.lab_assistant"))
        lab.add(toggle_row(st, "use_priority", "tasks.home_lab_priority", "use_priority_sub"))
        g.addWidget(lab, 0, 0)
        lp = GlassCard("priority_order", "list", "priority_sub")
        lp.add(TierEditor(st, "priorities.home_lab", "home_lab"))
        g.addWidget(lp, 0, 1)
        L["lab"].addWidget(w)
        L["lab"].addStretch(1)

        # ---------------- pets
        w, g = grid(2)
        pets = GlassCard("pets", "paw", "pets_sub")
        pets.add(toggle_row(st, "t_pet_house", "tasks.pet_house"))
        pets.add(toggle_row(st, "use_priority", "tasks.pet_house_priority", "use_priority_sub"))
        g.addWidget(pets, 0, 0)
        pp = GlassCard("priority_order", "list", "priority_sub")
        pp.add(TierEditor(st, "priorities.pet_house", "pet_house"))
        g.addWidget(pp, 0, 1)
        L["pets"].addWidget(w)
        L["pets"].addStretch(1)

        # ---------------- the official Clash of Clans API: the account exactly as Supercell knows it
        w, g = grid(2)
        ca = GlassCard("ca_title", "id", "ca_sub")
        from .bot_settings_screen import secret_field
        em = QLineEdit()
        em.setPlaceholderText("you@gmail.com")
        em.setLayoutDirection(Qt.LeftToRight)
        em.setMinimumWidth(320)
        bind_line(st, em, "clash_dev_email", "app")
        ca.add(form_row("ca_email", "ca_email_sub", em))
        ca.add(form_row("ca_pass", None, secret_field(st, "clash_dev_password", "••••••••")))
        ca.add(form_row("ca_key", "ca_key_sub", secret_field(st, "clash_api_key", "eyJ0eXAiOiJKV1Qi…")))
        tag = QLineEdit()
        tag.setPlaceholderText("#2PP0JCLQ8")
        tag.setLayoutDirection(Qt.LeftToRight)
        tag.setFixedWidth(200)
        bind_line(st, tag, "clash_tag")
        ca.add(form_row("ca_tag", "ca_tag_sub", tag))
        row = QHBoxLayout()
        ipb = IconButton("globe", "ca_myip", size=13)
        ipb.clicked.connect(self.my_ip)
        row.addWidget(ipb)
        ref = IconButton("refresh", "ca_refresh", kind="primary", size=13)
        ref.clicked.connect(lambda: self.load_clash(True))
        row.addWidget(ref)
        row.addStretch(1)
        ca.add(row)
        self.ca_ip = label("", "dim")
        self.ca_ip.setTextInteractionFlags(Qt.TextSelectableByMouse)
        ca.add(self.ca_ip)
        for k in ("ca_h1", "ca_h2", "ca_h3"): ca.add(note(k, "check"))
        g.addWidget(ca, 0, 0)
        res = GlassCard("ca_res", "trophy", "ca_res_sub")
        self.ca_out = QLabel("—")
        self.ca_out.setWordWrap(True)
        self.ca_out.setTextFormat(Qt.RichText)
        res.add(self.ca_out)
        g.addWidget(res, 0, 1)
        L["official"].addWidget(w)
        L["official"].addStretch(1)
        self.tabs.changed.connect(lambda k: self.load_clash() if k == "official" else None)

    def my_ip(self):
        self.ca_ip.setText(tr("ca_ip_wait"))
        self.api.get("/api/clash_ip", lambda r: self.ca_ip.setText(tr("ca_ip").format(ip=(r or {}).get("ip") or "?")))

    def load_clash(self, refresh=False):
        acc = self.store.account or "main"
        self.ca_out.setText(tr("ca_loading"))
        self.api.get(f"/api/clash/{acc}" + ("?refresh=1" if refresh else ""), self.show_clash, timeout=30)

    def show_clash(self, r):
        r = r or {}
        if r.get("error"):
            msg = tr("ca_err_" + r["error"]) if tr("ca_err_" + r["error"]) != "ca_err_" + r["error"] else r.get("message", "")
            if r.get("ip"): msg += "<br>" + tr("ca_ip").format(ip=r["ip"])
            self.ca_out.setText(msg)
            return
        bar = lambda lv, mx: f"{lv}/{mx}" + (" ✅" if lv >= mx else "")
        lines = [f"<b>{r.get('name', '')}</b> {r.get('tag', '')} — {tr('ca_th')} {r.get('th')} · 🏆 {r.get('trophies')} "
                 f"({r.get('league') or ''}) · ⭐ {r.get('war_stars')}" + (f" · {r['clan']}" if r.get("clan") else "")]
        lines.append(f"<b>{tr('ca_heroes')}</b> ({r.get('heroes_pct')}%): " +
                     " · ".join(f"{h['name']} {bar(h['level'], h['max'])}" for h in r.get("heroes", [])))
        if r.get("hero_behind"): lines.append("➡️ " + tr("ca_next_hero").format(n=r["hero_behind"]))
        if r.get("pets"):
            lines.append(f"<b>{tr('ca_pets')}</b>: " + " · ".join(f"{p['name']} {bar(p['level'], p['max'])}" for p in r["pets"]))
        if r.get("equipment"):
            eq = sorted(r["equipment"], key=lambda e: -e["level"])[:8]
            lines.append(f"<b>{tr('ca_equip')}</b>: " + " · ".join(f"{e['name']} {e['level']}" for e in eq))
        lines.append(tr("ca_pct").format(t=r.get("troops_pct"), s=r.get("spells_pct")))
        self.ca_out.setText("<br><br>".join(lines))
