"""
Screen 10 - Statistics: session header (refresh / reset) with KPI pills, three glowing resource cards
(total, per attack, per hour, highest, lowest), loot chart (recent attacks) + loot-per-hour chart +
efficiency ring, learned strategy scores, recent attacks table and recent upgrades table.
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import icons
from ..api import fmt_num
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.charts import NeonBarChart, RingGauge
from ..widgets.controls import Box, GlassCard, IconButton, label
from .base import Screen, grid, page


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([tr(h) for h in headers])
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.setMinimumHeight(300)
    on_lang(lambda: t.setHorizontalHeaderLabels([tr(h) for h in headers]))
    return t


def cell(text, color=None, mono=False):
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(Qt.AlignCenter)
    if color:
        from PySide6.QtGui import QColor
        it.setForeground(QColor(color))
    if mono:
        from ..theme import mono_font
        it.setFont(mono_font(9))
    return it


class ResCard(Box):
    def __init__(self, glyph, key, tint):
        super().__init__(bg="#120F15", border=f"rgba(245, 183, 64,0.25)", radius=16, top=TOKENS[tint])
        self.tint = tint
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(6)
        h = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(glyph, 30))
        h.addWidget(ic)
        h.addWidget(label(key=key, role="h2"), 1)
        v.addLayout(h)
        self.total = QLabel("—")
        self.total.setProperty("role", "kpi")
        self.total.setStyleSheet(f"color: {TOKENS[tint]};")
        v.addWidget(label(key="total", role="dim"))
        v.addWidget(self.total)
        g = QGridLayout()
        g.setSpacing(6)
        self.cells = {}
        for i, k in enumerate(("per_attack", "per_hour", "highest", "lowest")):
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(label(key=k, role="dim"))
            val = QLabel("—")
            val.setProperty("role", "numsm")
            box.addWidget(val)
            self.cells[k] = val
            g.addLayout(box, i // 2, i % 2)
        v.addLayout(g)

    def set(self, total, per_attack, per_hour, hi, lo):
        self.total.setText(fmt_num(total))
        for k, val in (("per_attack", per_attack), ("per_hour", per_hour), ("highest", hi), ("lowest", lo)):
            self.cells[k].setText(fmt_num(val))


class StatisticsScreen(Screen):
    key, title_key, icon_name = "res", "sub_res", "chart"

    def __init__(self, ctx):
        super().__init__(ctx)
        L = self.make_tabs([("history", "sh_tab_history", "calendar"), ("session", "sh_tab_session", "pulse")])
        from .stats_history import HistoryPanel
        self.history = HistoryPanel(self)
        L["history"].addWidget(self.history)
        L["history"].addStretch(1)
        v = L["session"]
        head = GlassCard("session_results", "chart", "session_results_sub", glow=True)
        r = IconButton("refresh", "refresh_now", size=14)
        r.clicked.connect(lambda: self.poller.refresh("stats"))
        head.add_tool(r)
        z = IconButton("trash", "reset", kind="stop", icon_color="#FCA5A5", size=14)
        z.clicked.connect(self.reset)
        head.add_tool(z)
        self.since = label("", "dim")
        head.add(self.since)
        kp = QHBoxLayout()
        kp.setSpacing(10)
        self.kpis = {}
        for k in ("kpi_attacks", "kpi_searches", "kpi_skipped", "kpi_upgrades", "kpi_walls", "kpi_cycles", "kpi_avg"):
            b = Box(bg="#16111A", radius=12)
            bl = QVBoxLayout(b)
            bl.setContentsMargins(10, 8, 10, 8)
            bl.setSpacing(0)
            val = QLabel("0")
            val.setProperty("role", "kpi")
            val.setAlignment(Qt.AlignCenter)
            cap = label(key=k, role="dim")
            cap.setAlignment(Qt.AlignCenter)
            bl.addWidget(val)
            bl.addWidget(cap)
            self.kpis[k] = val
            kp.addWidget(b)
        head.add(kp)
        v.addWidget(head)

        res = QHBoxLayout()
        res.setSpacing(14)
        self.c_gold = ResCard("gold", "gold", "gold")
        self.c_elixir = ResCard("elixir", "elixir", "elixir")
        self.c_dark = ResCard("dark", "dark", "dark")
        for c in (self.c_gold, self.c_elixir, self.c_dark): res.addWidget(c)
        v.addLayout(res)

        w, g = grid(3)
        c1 = GlassCard("loot_gained", "chart")
        self.bars = NeonBarChart(height=240)
        c1.add(self.bars)
        g.addWidget(c1, 0, 0, 1, 2)
        c2 = GlassCard("efficiency", "target", "eff_sub")
        self.ring = RingGauge(170)
        c2.add(self.ring)
        c2.body.setAlignment(self.ring, Qt.AlignHCenter)
        g.addWidget(c2, 0, 2)
        c3 = GlassCard("per_hour_chart", "clock")
        self.hour_bars = NeonBarChart(height=200)
        c3.add(self.hour_bars)
        g.addWidget(c3, 1, 0, 1, 2)
        c4 = GlassCard("strategies", "layers", "strategies_sub")
        self.strat = table(["strategy", "kpi_attacks", "gold", "elixir", "dark"])
        self.strat.setMinimumHeight(200)
        c4.add(self.strat)
        g.addWidget(c4, 1, 2)
        v.addWidget(w)

        w2, g2 = grid(2)
        a = GlassCard("recent_attacks", "swords")
        self.t_att = table(["#", "time", "base", "gold", "elixir", "dark"])
        a.add(self.t_att)
        g2.addWidget(a, 0, 0)
        u = GlassCard("recent_upgrades", "hammer")
        self.t_up = table(["time", "type", "name"])
        u.add(self.t_up)
        g2.addWidget(u, 0, 1)
        v.addWidget(w2)
        v.addStretch(1)
        self.poller.stats.connect(self.render)

    def on_show(self):
        self.poller.refresh("stats")
        self.history.load()

    def reset(self):
        if QMessageBox.question(self, "Clash Farmer", tr("confirm_reset")) != QMessageBox.Yes: return
        self.api.post(f"/api/stats/{self.store.account}/reset", {}, lambda r: self.poller.refresh("stats"))

    def render(self, d):
        if d.get("session_start"):
            self.since.setText(f"{tr('session_since') if tr('session_since') != 'session_since' else ''} "
                               f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(d['session_start']))}")
        vals = {"kpi_attacks": d.get("attacks", 0), "kpi_searches": d.get("searches", 0), "kpi_skipped": d.get("skipped", 0),
                "kpi_upgrades": d.get("upgrades", 0), "kpi_walls": d.get("walls", 0), "kpi_cycles": d.get("cycles", 0)}
        for k, n in vals.items(): self.kpis[k].setText(fmt_num(n))
        avg = d.get("avg_cycle_seconds")
        self.kpis["kpi_avg"].setText(f"{int(avg) // 60}{tr('minutes_short')} {int(avg) % 60}{tr('seconds_short')}" if avg else "—")
        tot, pa, ph, best, worst = (d.get(k, {}) or {} for k in ("totals", "per_attack", "per_hour", "best", "worst"))
        for c, k in ((self.c_gold, "gold"), (self.c_elixir, "elixir"), (self.c_dark, "dark")):
            c.set(tot.get(k), pa.get(k), ph.get(k), best.get(k), worst.get(k))
        recent = d.get("recent_attacks", []) or []
        self.bars.set_data([(time.strftime("%H:%M", time.localtime(a.get("t", 0))), [a.get("gold", 0), a.get("elixir", 0), a.get("dark", 0)])
                            for a in reversed(recent[:12])])
        # loot per hour of the day (sum of the recent attacks per clock hour)
        hours = {}
        for a in recent:
            hkey = time.strftime("%H:00", time.localtime(a.get("t", 0)))
            row = hours.setdefault(hkey, [0, 0, 0])
            for i, k in enumerate(("gold", "elixir", "dark")): row[i] += int(a.get(k) or 0)
        self.hour_bars.set_data(sorted(hours.items())[-10:])
        good = sum(1 for a in recent if (a.get("gold") or 0) + (a.get("elixir") or 0) > 0)
        self.ring.set_value(good / len(recent) if recent else 0, caption=tr("efficiency"))
        self.t_att.setRowCount(0)
        for i, a in enumerate(recent[:60]):
            self.t_att.insertRow(i)
            self.t_att.setItem(i, 0, cell(len(recent) - i, TOKENS["dim"], True))
            self.t_att.setItem(i, 1, cell(time.strftime("%H:%M:%S", time.localtime(a.get("t", 0))), None, True))
            self.t_att.setItem(i, 2, cell(tr("home_v") if a.get("base") == "home" else tr("builder_v")))
            self.t_att.setItem(i, 3, cell(fmt_num(a.get("gold")), TOKENS["gold"], True))
            self.t_att.setItem(i, 4, cell(fmt_num(a.get("elixir")), TOKENS["elixir"], True))
            self.t_att.setItem(i, 5, cell(fmt_num(a.get("dark")), "#B4B8FF", True))
        ups = d.get("recent_upgrades", []) or []
        self.t_up.setRowCount(0)
        for i, u in enumerate(ups[:60]):
            self.t_up.insertRow(i)
            self.t_up.setItem(i, 0, cell(time.strftime("%H:%M:%S", time.localtime(u.get("t", 0))), None, True))
            self.t_up.setItem(i, 1, cell(tr("up_" + u.get("kind", "")) if tr("up_" + u.get("kind", "")) != "up_" + u.get("kind", "") else u.get("kind", "")))
            self.t_up.setItem(i, 2, cell(u.get("name", "")))
        strat = d.get("strategies", {}) or {}
        self.strat.setRowCount(0)
        for i, (name, s) in enumerate(sorted(strat.items(), key=lambda kv: -(kv[1].get("gold", 0) + kv[1].get("elixir", 0)))):
            self.strat.insertRow(i)
            self.strat.setItem(i, 0, cell(tr("st_" + name) if tr("st_" + name) != "st_" + name else name))
            self.strat.setItem(i, 1, cell(s.get("attacks", 0), None, True))
            self.strat.setItem(i, 2, cell(fmt_num(s.get("gold")), TOKENS["gold"], True))
            self.strat.setItem(i, 3, cell(fmt_num(s.get("elixir")), TOKENS["elixir"], True))
            self.strat.setItem(i, 4, cell(fmt_num(s.get("dark")), "#B4B8FF", True))
