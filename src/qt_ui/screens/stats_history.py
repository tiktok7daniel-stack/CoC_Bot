"""
Statistics history (the permanent per-day ledger, /api/stats_daily/<id|all>):
 - range: today / 7 / 30 / 90 days / everything; scope: this account or all accounts together
 - six KPI tiles with animated count-up, change vs the previous period (▲ / ▼ %) and a daily sparkline
 - interactive loot chart per day (hover a day for exact numbers)
 - best farming hours (loot by hour of the day) + smart insights (best day, best attack, success rate …)
 - a day-by-day table and CSV export
"""
import csv, time

from PySide6.QtCore import QEasingCurve, QTimer, QVariantAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import icons
from ..api import fmt_num
from ..i18n import on_lang, tr
from ..theme import TOKENS, mono_font
from ..widgets.charts import AreaChart, NeonBarChart, Sparkline
from ..widgets.controls import Box, Chip, GlassCard, IconButton, label

RANGES = (("today", "sh_today", 1), ("7", "sh_7", 7), ("30", "sh_30", 30), ("90", "sh_90", 90), ("all", "sh_all", 0))


class CountLabel(QLabel):
    """A number that counts up to its new value (450 ms, ease-out)."""

    def __init__(self, role="kpi", fmt=fmt_num):
        super().__init__("—")
        self.setProperty("role", role)
        self.fmt = fmt
        self.value = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(650)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: self.setText(self.fmt(v)))

    def animate_to(self, v):
        v = float(v or 0)
        self.anim.stop()
        self.anim.setStartValue(float(self.value))
        self.anim.setEndValue(v)
        self.value = v
        self.anim.start()


class StatTile(Box):
    def __init__(self, icon_name, key, tint, fmt=fmt_num):
        super().__init__(bg="#101016", border="rgba(255,255,255,0.07)", radius=16)
        self.tint = tint
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 12)
        v.setSpacing(4)
        h = QHBoxLayout()
        h.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 18, TOKENS[tint]))
        h.addWidget(ic)
        h.addWidget(label(key=key, role="sub"), 1)
        self.delta = QLabel("")
        self.delta.setTextFormat(Qt.RichText)
        h.addWidget(self.delta)
        v.addLayout(h)
        self.val = CountLabel("kpi", fmt)
        self.val.setStyleSheet(f"color: {TOKENS['text']};")
        v.addWidget(self.val)
        self.spark = Sparkline(tint, 30, 2)
        v.addWidget(self.spark)

    def set(self, value, series, prev=None):
        self.val.animate_to(value)
        self.spark.keep = max(2, len(series))
        self.spark.values = [float(x or 0) for x in series][-self.spark.keep:]
        self.spark.update()
        if prev is None or (not prev and not value):
            self.delta.setText("")
            return
        if not prev:
            self.delta.setText(f'<span style="color:{TOKENS["ok"]};font-weight:700">▲ {tr("sh_new")}</span>')
            return
        pct = (value - prev) / prev * 100
        up = pct >= 0
        col = TOKENS["ok"] if up else TOKENS["bad"]
        bg = "rgba(61,214,140,0.12)" if up else "rgba(240,85,90,0.12)"
        self.delta.setText(f'<span style="color:{col};font-weight:700;background:{bg}">&nbsp;{"▲" if up else "▼"} {abs(pct):.0f}%&nbsp;</span>')


def _cell(text, color=None, mono=True):
    it = QTableWidgetItem(str(text))
    it.setTextAlignment(Qt.AlignCenter)
    if color: it.setForeground(QColor(color))
    if mono: it.setFont(mono_font(9))
    return it


class HistoryPanel(QWidget):
    def __init__(self, screen):
        super().__init__()
        self.screen = screen
        self.api, self.store = screen.api, screen.store
        self.range, self.scope = "7", "acc"
        self.rows, self.prev = [], []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        # ---------------- controls
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.range_chips = {}
        for key, tk, _d in RANGES:
            c = Chip(key=tk)
            c.clicked.connect(lambda _=False, k=key: self.set_range(k))
            bar.addWidget(c)
            self.range_chips[key] = c
        bar.addSpacing(14)
        self.scope_chips = {}
        for key, tk in (("acc", "sh_this_acc"), ("all", "sh_all_acc")):
            c = Chip(key=tk)
            c.clicked.connect(lambda _=False, k=key: self.set_scope(k))
            bar.addWidget(c)
            self.scope_chips[key] = c
        bar.addStretch(1)
        self.updated = label("", "dim")
        bar.addWidget(self.updated)
        rf = IconButton("refresh", None, "ghost", tip_key="refresh_now")
        rf.clicked.connect(self.load)
        bar.addWidget(rf)
        ex = IconButton("download", "sh_export")
        ex.clicked.connect(self.export)
        bar.addWidget(ex)
        v.addLayout(bar)

        # ---------------- KPI tiles
        tg = QGridLayout()
        tg.setSpacing(12)
        hours_fmt = lambda x: f"{x:.1f}"
        self.tiles = {
            "gold": StatTile("gold", "gold", "gold"), "elixir": StatTile("elixir", "elixir", "elixir"),
            "dark": StatTile("dark", "dark", "dark"), "attacks": StatTile("swords", "kpi_attacks", "accent"),
            "lph": StatTile("bolt", "sh_loot_hour", "accent"), "hours": StatTile("clock", "sh_active_hours", "info", hours_fmt),
        }
        for i, k in enumerate(("gold", "elixir", "dark", "attacks", "lph", "hours")):
            tg.addWidget(self.tiles[k], i // 3, i % 3)
        v.addLayout(tg)

        # ---------------- main chart
        cc = GlassCard("sh_chart", "chart", "sh_chart_sub")
        self.chart = AreaChart(height=280)
        self.chart.empty_text = tr("sh_empty")
        cc.add(self.chart)
        v.addWidget(cc)

        # ---------------- best hours + insights
        row = QHBoxLayout()
        row.setSpacing(14)
        hc = GlassCard("sh_hours", "clock", "sh_hours_sub")
        self.hours = NeonBarChart(("accent",), height=210)
        hc.add(self.hours)
        row.addWidget(hc, 3)
        ic = GlassCard("sh_insights", "lightbulb", "sh_insights_sub")
        self.ins = QGridLayout()
        self.ins.setHorizontalSpacing(12)
        self.ins.setVerticalSpacing(10)
        ic.add(self.ins)
        self.ins_vals = {}
        for i, k in enumerate(("sh_best_day", "sh_best_attack", "sh_success", "sh_avg_attack", "sh_skip_rate",
                               "sh_upgrades", "sh_walls", "sh_errors")):
            name = label(key=k, role="sub")
            val = label("—", "numsm")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter if self.layoutDirection() == Qt.LeftToRight else Qt.AlignLeft | Qt.AlignVCenter)
            self.ins.addWidget(name, i, 0)
            self.ins.addWidget(val, i, 1)
            self.ins_vals[k] = val
        row.addWidget(ic, 2)
        v.addLayout(row)

        # ---------------- day table
        tc = GlassCard("sh_table", "calendar", "sh_table_sub")
        heads = ["sh_date", "kpi_attacks", "gold", "elixir", "dark", "sh_loot_hour", "sh_active_hours", "sh_upgrades", "sh_walls"]
        self.table = QTableWidget(0, len(heads))
        self.table.setHorizontalHeaderLabels([tr(h) for h in heads])
        on_lang(lambda: self.table.setHorizontalHeaderLabels([tr(h) for h in heads]))
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(320)
        tc.add(self.table)
        v.addWidget(tc)

        self.set_range("7", load=False)
        self.set_scope("acc", load=False)
        self.store.account_changed.connect(lambda _a: self.load())
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.isVisible() and self.load())
        self.timer.start(60000)

    # ---------------------------------------------------------------- controls
    def set_range(self, k, load=True):
        self.range = k
        for key, c in self.range_chips.items(): c.setChecked(key == k)
        if load: self.load()

    def set_scope(self, k, load=True):
        self.scope = k
        for key, c in self.scope_chips.items(): c.setChecked(key == k)
        if load: self.load()

    def days(self):
        return dict((k, d) for k, _t, d in RANGES)[self.range]

    def load(self):
        who = "all" if self.scope == "all" else self.store.account
        if not who: return
        n = self.days()
        self.api.get(f"/api/stats_daily/{who}?days={n * 2 if n else 0}", self.got)

    # ---------------------------------------------------------------- render
    def got(self, r):
        if not isinstance(r, dict) or "days" not in r: return
        allrows = r["days"]
        n = self.days()
        if n:
            today = time.time()
            cut = time.strftime("%Y-%m-%d", time.localtime(today - (n - 1) * 86400))
            pcut = time.strftime("%Y-%m-%d", time.localtime(today - (2 * n - 1) * 86400))
            self.rows = [d for d in allrows if d["date"] >= cut]
            self.prev = [d for d in allrows if pcut <= d["date"] < cut]
            # every day of the range on the chart, also the days the bot did not run
            dates = [time.strftime("%Y-%m-%d", time.localtime(today - i * 86400)) for i in range(n - 1, -1, -1)]
        else:
            self.rows, self.prev = allrows, None
            dates = [d["date"] for d in allrows]
        by = {d["date"]: d for d in self.rows}
        self.render(dates, by)
        self.updated.setText(f"{tr('sh_updated')} {time.strftime('%H:%M')}")

    def _sum(self, rows, k):
        return sum(float(d.get(k) or 0) for d in rows or [])

    def render(self, dates, by):
        rows, prev = self.rows, self.prev
        series = lambda k: [float((by.get(dt) or {}).get(k) or 0) for dt in dates]
        hours_now = self._sum(rows, "active_hours")
        loot_now = self._sum(rows, "loot")
        lph = loot_now / hours_now if hours_now > 0.25 else 0
        p = prev if prev is not None else None
        p_hours = self._sum(p, "active_hours") if p is not None else None
        p_lph = (self._sum(p, "loot") / p_hours if p_hours and p_hours > 0.25 else 0) if p is not None else None
        for k in ("gold", "elixir", "dark"):
            self.tiles[k].set(self._sum(rows, k), series(k), self._sum(p, k) if p is not None else None)
        self.tiles["attacks"].set(self._sum(rows, "home_attacks"), series("home_attacks"), self._sum(p, "home_attacks") if p is not None else None)
        self.tiles["lph"].set(lph, series("loot_per_hour"), p_lph)
        self.tiles["hours"].set(hours_now, series("active_hours"), p_hours)
        # chart
        short = [dt[5:].replace("-", "/") for dt in dates]
        self.chart.set_data(short, {k: series(k) for k in ("gold", "elixir", "dark")},
                            {k: tr(k) for k in ("gold", "elixir", "dark")})
        # best hours of the day
        hrs = [0] * 24
        for d in rows:
            for i, x in enumerate(d.get("hours") or []): hrs[i] += x
        self.hours.set_data([(f"{i:02d}", [hrs[i]]) for i in range(24)] if any(hrs) else [], per_series_scale=False)
        self.hours.empty_text = tr("sh_empty")
        # insights
        best = max(rows, key=lambda d: d.get("loot", 0), default=None)
        atk = self._sum(rows, "home_attacks")
        zero = self._sum(rows, "zero_loot")
        srch = self._sum(rows, "searches")
        vals = {
            "sh_best_day": f"{best['date'][5:]}  •  {fmt_num(best.get('loot', 0))}" if best and best.get("loot") else "—",
            "sh_best_attack": fmt_num(max((d.get("best_gold", 0) + d.get("best_elixir", 0) for d in rows), default=0)) if rows else "—",
            "sh_success": f"{(atk - zero) / atk * 100:.0f}%" if atk else "—",
            "sh_avg_attack": fmt_num(loot_now / atk) if atk else "—",
            "sh_skip_rate": f"{self._sum(rows, 'skipped') / srch * 100:.0f}%" if srch else "—",
            "sh_upgrades": fmt_num(self._sum(rows, "buildings") + self._sum(rows, "lab")),
            "sh_walls": fmt_num(self._sum(rows, "walls")),
            "sh_errors": fmt_num(self._sum(rows, "errors")),
        }
        if hrs and any(hrs):
            bh = max(range(24), key=lambda i: hrs[i])
            vals["sh_best_day"] += ""
            self.hours.setToolTip(f"{tr('sh_peak')} {bh:02d}:00")
        for k, v in vals.items(): self.ins_vals[k].setText(v)
        # table (newest first)
        self.table.setRowCount(0)
        for i, d in enumerate(sorted(rows, key=lambda d: d["date"], reverse=True)):
            self.table.insertRow(i)
            items = [(d["date"], TOKENS["accent_hi"]), (fmt_num(d.get("home_attacks", 0)), None),
                     (fmt_num(d.get("gold", 0)), TOKENS["gold"]), (fmt_num(d.get("elixir", 0)), TOKENS["elixir"]),
                     (fmt_num(d.get("dark", 0)), TOKENS["dark"]), (fmt_num(d.get("loot_per_hour", 0)), None),
                     (f"{d.get('active_hours', 0):.1f}", None), (fmt_num(d.get("buildings", 0) + d.get("lab", 0)), None),
                     (fmt_num(d.get("walls", 0)), None)]
            for j, (t, c) in enumerate(items): self.table.setItem(i, j, _cell(t, c))

    # ---------------------------------------------------------------- export
    def export(self):
        if not self.rows:
            self.screen.ctx.toast(tr("sh_empty"), "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("sh_export"), f"clash_farmer_stats_{time.strftime('%Y%m%d')}.csv", "CSV (*.csv)")
        if not path: return
        keys = ["date", "home_attacks", "builder_attacks", "gold", "elixir", "dark", "loot_per_hour", "active_hours",
                "searches", "skipped", "buildings", "lab", "walls", "cycles", "errors", "best_gold", "best_elixir", "best_dark"]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(keys)
                for d in self.rows: w.writerow([d.get(k, "") for k in keys])
            self.screen.ctx.toast(tr("sh_exported"), "ok")
        except OSError as e:
            self.screen.ctx.toast(str(e), "bad")
