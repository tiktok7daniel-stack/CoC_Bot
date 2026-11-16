"""
Screen 1 - Dashboard: telemetry strip, quick action cards, my recordings, account cards, session
summary with a loot chart and efficiency ring, live mini log, gameplay mode, live state + quick pause,
and the quick tasks matrix.
"""
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import icons
from ..api import fmt_dur, fmt_num, status_key
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.charts import MeterBar, NeonBarChart, RingGauge, Sparkline
from ..widgets.controls import (Box, Chip, FlowLayout, GlassCard, IconButton, NumField, StatusPill, Toggle, bind_num,
                                bind_toggle, form_row, label, num_row, toggle_row)
from ..widgets.log_view import LogView
from .base import Screen, grid, page

QUICK_TASKS = [("tasks.home_base", "t_home_base"), ("tasks.heroes", "t_heroes"), ("walls.enabled", "wall_enabled"),
               ("tasks.home_lab", "t_home_lab"), ("tasks.pet_house", "t_pet_house"), ("tasks.home_attacks", "t_home_attacks"),
               ("tasks.builder_base", "t_builder_base"), ("tasks.builder_lab", "t_builder_lab"),
               ("tasks.builder_attacks", "t_builder_attacks"), ("game.keep_open", "keep_open"), ("game.never_close", "never_close")]


class Tile(QFrame):
    """Telemetry tile: colored top line, label, big mono value, optional sparkline."""

    def __init__(self, key, tint, icon_name, spark=False):
        super().__init__()
        self.tint = tint
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 10)
        v.setSpacing(4)
        h = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 16, TOKENS[tint]))
        h.addWidget(ic)
        h.addWidget(label(key=key, role="sub"), 1)
        v.addLayout(h)
        self.value = QLabel("—")
        self.value.setProperty("role", "numsm")
        self.value.setStyleSheet("font-size: 13pt;")
        v.addWidget(self.value)
        self.spark = Sparkline(tint) if spark else None
        if self.spark: v.addWidget(self.spark)
        self.setStyleSheet("Tile { background: #101016; border: 1px solid rgba(255,255,255,0.07); border-radius: 14px; }"
                           " Tile:hover { border-color: rgba(245,183,64,0.35); }")

    def set(self, text, spark_value=None):
        arabic = any("\u0600" <= ch <= "\u06FF" for ch in str(text))
        self.value.setProperty("role", "h3" if arabic else "numsm")
        self.value.setStyleSheet("font-size: 12.5pt; font-weight: 700;" if arabic else "font-size: 13pt;")
        self.value.style().unpolish(self.value)
        self.value.style().polish(self.value)
        self.value.setText(text)
        if self.spark is not None and spark_value is not None: self.spark.push(spark_value)


class QuickCard(QPushButton):
    def __init__(self, icon_name, key, sub_key):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(74)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(icons.pixmap(icon_name, 22, "#F7E3BC"))
        ic.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(245, 183, 64,0.55), stop:1 rgba(255,215,0,0.35)); border-radius: 11px;")
        h.addWidget(ic)
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(label(key=key, role="h3"))
        box.addWidget(label(key=sub_key, role="dim"))
        h.addLayout(box, 1)
        self.setStyleSheet(f"QuickCard {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 14px; text-align: right; }}"
                           f" QuickCard:hover {{ border-color: {TOKENS['border_hover']}; background: #1F1820; }}")


class ResourceStat(QFrame):
    def __init__(self, glyph, key, tint):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(glyph, 26))
        h.addWidget(ic)
        box = QVBoxLayout()
        box.setSpacing(0)
        box.addWidget(label(key=key, role="sub"))
        self.value = QLabel("—")
        self.value.setProperty("role", "num")
        self.value.setStyleSheet(f"color: {TOKENS[tint]};")
        box.addWidget(self.value)
        self.sub = label("", "dim")
        box.addWidget(self.sub)
        h.addLayout(box, 1)
        self.setStyleSheet(f"ResourceStat {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 16px; }}")


class DashboardScreen(Screen):
    key, title_key, icon_name = "dash", "sub_dash", "trophy"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page()
        self.root.addWidget(sa)

        # ---------- today's plan bar
        self.plan_bar = Box(radius=18, border="rgba(245,183,64,0.35)")
        pb = QHBoxLayout(self.plan_bar)
        pb.setContentsMargins(16, 10, 12, 10)
        pb.setSpacing(12)
        pic = QLabel()
        pic.setPixmap(icons.pixmap("calendar", 24, TOKENS["accent"]))
        pb.addWidget(pic)
        pcol = QVBoxLayout()
        pcol.setSpacing(0)
        pcol.addWidget(label(key="tp_bar_title", role="h3"))
        self.plan_text = label("—", "sub", wrap=True)
        pcol.addWidget(self.plan_text)
        pb.addLayout(pcol, 1)
        chg = IconButton("edit", "tp_change", "warn", size=14)
        chg.clicked.connect(lambda: self.ctx.window.today.edit())
        pb.addWidget(chg)
        v.addWidget(self.plan_bar)

        # ---------- telemetry strip
        strip = QWidget()
        g = QGridLayout(strip)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        self.t_cpu = Tile("sy_cpu", "info", "cpu", spark=True)
        self.t_ram = Tile("sy_ram", "purple", "memory", spark=True)
        self.t_up = Tile("sy_up", "gold", "clock")
        self.t_adb = Tile("ADB", "ok", "usb")
        self.t_emu = Tile("sy_emu", "warn", "monitor")
        self.t_state = Tile("sy_status", "elixir", "pulse")
        for i, t in enumerate((self.t_cpu, self.t_ram, self.t_up, self.t_adb, self.t_emu, self.t_state)):
            g.addWidget(t, 0, i)
        v.addWidget(strip)

        # ---------- quick actions
        qa = GlassCard("quick_actions", "bolt")
        row = QHBoxLayout()
        row.setSpacing(10)
        for ic, k, sk, target in (("id", "nv_acc", "acc_title", ("acc", None)), ("stethoscope", "sc_title", "sc_sub", ("log", "check")),
                                  ("cloud", "updates", "upd_sub", ("set", "general")), ("scroll", "nv_log", "bot_log", ("log", "log")),
                                  ("clock", "tab_sch", "sch_title", ("set", "sch"))):
            c = QuickCard(ic, k, sk)
            c.clicked.connect(lambda _=False, tg=target: self.ctx.window.show_screen(*tg))
            row.addWidget(c)
        qa.add(row)
        v.addWidget(qa)

        # ---------- recordings + accounts
        w, gl = grid(2)
        self.rec_card = GlassCard("hr_title", "video", "hr_sub")
        new_rec = IconButton("plus", "hr_new", size=14)
        new_rec.clicked.connect(lambda: self.ctx.window.show_screen("atk", "plans"))
        self.rec_card.add_tool(new_rec)
        self.rec_host = QWidget()
        self.rec_flow = FlowLayout(self.rec_host, 10)
        self.rec_card.add(self.rec_host)
        self.rec_card.add(label(key="hd_armies", role="sub"))
        self.army_host = QWidget()
        self.army_flow = FlowLayout(self.army_host, 8)
        self.rec_card.add(self.army_host)
        gl.addWidget(self.rec_card, 0, 0)
        self.acc_card = GlassCard("acc_cards", "users")
        go_acc = IconButton("sliders", "nv_acc", size=14)
        go_acc.clicked.connect(lambda: self.ctx.window.show_screen("acc"))
        self.acc_card.add_tool(go_acc)
        self.acc_host = QWidget()
        self.acc_flow = FlowLayout(self.acc_host, 10)
        self.acc_card.add(self.acc_host)
        gl.addWidget(self.acc_card, 0, 1)
        v.addWidget(w)

        # ---------- session summary (hero) + live mini log
        w2, g2 = grid(2)
        hero = GlassCard("hero_summary", "chart", glow=True)
        res = QHBoxLayout()
        res.setSpacing(10)
        self.r_gold = ResourceStat("gold", "gold", "gold")
        self.r_elixir = ResourceStat("elixir", "elixir", "elixir")
        self.r_dark = ResourceStat("dark", "dark", "dark")
        for r in (self.r_gold, self.r_elixir, self.r_dark): res.addWidget(r)
        hero.add(res)
        kp = QHBoxLayout()
        kp.setSpacing(8)
        self.kpis = {}
        for k in ("kpi_attacks", "kpi_searches", "kpi_skipped", "kpi_walls", "kpi_upgrades", "kpi_cycles", "kpi_avg"):
            box = Box(bg="#16111A")
            bl = QVBoxLayout(box)
            bl.setContentsMargins(8, 6, 8, 6)
            bl.setSpacing(0)
            val = QLabel("0")
            val.setProperty("role", "kpi")
            val.setAlignment(Qt.AlignCenter)
            bl.addWidget(val)
            cap = label(key=k, role="dim")
            cap.setAlignment(Qt.AlignCenter)
            bl.addWidget(cap)
            self.kpis[k] = val
            kp.addWidget(box)
        hero.add(kp)
        chart_row = QHBoxLayout()
        self.chart = NeonBarChart(height=200)
        chart_row.addWidget(self.chart, 1)
        ring_box = QVBoxLayout()
        self.ring = RingGauge(150)
        ring_box.addWidget(self.ring, 0, Qt.AlignHCenter)
        ring_box.addWidget(label(key="eff_sub", role="dim", wrap=True))
        chart_row.addLayout(ring_box)
        hero.add(chart_row)
        g2.addWidget(hero, 0, 0)
        logc = GlassCard("last_logs", "terminal")
        full = IconButton("scroll", "open_full_log", size=14)
        full.clicked.connect(lambda: self.ctx.window.show_screen("log", "log"))
        logc.add_tool(full)
        self.mini_log = LogView(mini=True)
        self.mini_log.setMinimumHeight(330)
        logc.add(self.mini_log, 1)
        g2.addWidget(logc, 0, 1)
        v.addWidget(w2)

        # ---------- gameplay mode + live state/pause + quick tasks
        w3, g3 = grid(3)
        farm = GlassCard("farm_title", "layers", "farm_sub")
        farm.add(toggle_row(self.store, "farm_on", "attack.farm.enabled", "farm_on_sub"))
        farm.add(toggle_row(self.store, "farm_max_walls", "attack.farm.max_walls", "farm_max_walls_sub"))
        farm.add(form_row("farm_gold", "farm_auto_sub", bind_num(self.store, NumField(0, 10**9, 100000, 150), "attack.farm.gold_full"), icon_name=None))
        farm.add(form_row("farm_elixir", "farm_auto_sub", bind_num(self.store, NumField(0, 10**9, 100000, 150), "attack.farm.elixir_full")))
        farm.add(num_row(self.store, "farm_rest", "attack.farm.rest_minutes", "farm_rest_sub", "minutes", 1, 1440, 5, 90))
        g3.addWidget(farm, 0, 0)

        live = GlassCard("live_state", "pulse", "bot_status_sub")
        self.live_rows = {}
        for k in ("account", "state", "last_cycle", "next_cycle", "schedule"):
            val = QLabel("—")
            val.setStyleSheet("font-weight: 700;")
            self.live_rows[k] = val
            live.add(form_row(k, None, val))
        pills = QHBoxLayout()
        for m in (5, 15, 30, 60):
            c = Chip(f"{m} {tr('minutes_short')}", checkable=False)
            c.clicked.connect(lambda _=False, m=m: self.pause(m))
            pills.addWidget(c)
        live.add(pills)
        prow = QHBoxLayout()
        self.custom_pause = NumField(1, 1440, 5, 90)
        self.custom_pause.setValue(120)
        prow.addWidget(label(key="custom_minutes", role="sub"), 1)
        prow.addWidget(self.custom_pause)
        pb = IconButton("pause", "pause", kind="warn", icon_color=TOKENS["warn"], size=14)
        pb.clicked.connect(lambda: self.pause(self.custom_pause.value()))
        prow.addWidget(pb)
        rb = IconButton("play", "resume_now", size=14)
        rb.clicked.connect(lambda: self.pause(0))
        prow.addWidget(rb)
        live.add(prow)
        self.pause_left = label("", "sub")
        live.add(self.pause_left)
        g3.addWidget(live, 0, 1)

        tasks = GlassCard("quick_tasks", "sliders", "quick_tasks_sub")
        for path, k in QUICK_TASKS:
            tasks.add(toggle_row(self.store, k, path))
        g3.addWidget(tasks, 0, 2)
        v.addWidget(w3)
        v.addStretch(1)

        self.poller.state.connect(self.on_state)
        self.poller.system.connect(self.on_system)
        self.poller.stats.connect(self.on_stats)
        self.poller.log.connect(self.mini_log.set_lines)
        self.store.loaded.connect(self.render_recordings)
        self.store.on_change(self.render_recordings)
        self.recordings = []
        from ..widgets.avatar import profiles
        profiles.changed.connect(lambda _a: self.render_accounts())
        self.store.account_changed.connect(lambda _a: self.refresh_plan())
        on_lang(lambda: (self.render_accounts(), self.render_recordings()))
        self.load_recordings()

    # ---------------------------------------------------------------- data
    def refresh_plan(self):
        acc = self.store.account
        if not acc: return

        def got(r):
            p = (r or {}).get("plan") if isinstance(r, dict) else None
            if not p: text = tr("tp_bar_none")
            elif p["mode"] == "usual": text = tr("tp_bar_usual") + (" " + tr("tp_bar_auto") if p.get("auto") else "")
            elif p["mode"] == "nothing": text = tr("tp_bar_nothing")
            elif p["mode"] == "smart": text = tr("tp_smart") + " — " + tr("tp_smart_sub")
            else:
                names = {"attack": "tp_attack", "buildings": "tp_buildings", "walls": "tp_walls", "lab": "tp_lab",
                         "heroes": "tp_heroes", "builder_base": "tp_bb"}
                text = " · ".join(tr(names[k]) for k, on in p.get("do", {}).items() if on and k in names)
            self.plan_text.setText(text)
        self.api.get(f"/api/plan/{acc}", got)

    def on_show(self):
        self.refresh_plan()
        self.load_recordings()
        self.poller.refresh_all()

    def load_recordings(self):
        def got(r):
            if isinstance(r, dict) and "items" in r:
                self.recordings = r["items"]
                self.render_recordings()
        self.api.get("/api/recordings", got)
        self.api.get("/api/armies", self.render_armies)

    def render_armies(self, r):
        if not isinstance(r, dict) or "items" not in r: return
        self.army_flow.clear()
        if not r["items"]:
            self.army_flow.addWidget(label(key="hd_armies_none", role="dim"))
            return
        for a in r["items"]:
            b = IconButton("army", None, size=15, text=a["name"])
            b.setToolTip(tr("hd_army_tip").format(name=a["name"]))
            b.clicked.connect(lambda _=False, n=a["name"]: self.prepare_army(n))
            self.army_flow.addWidget(b)

    def prepare_army(self, name):
        def done(r):
            ok = isinstance(r, dict) and r.get("ok")
            self.ctx.toast(tr("al_prepare_ok" if ok and r.get("running") else ("al_prepare_idle" if ok else "dk_failed")).format(name=name),
                           "ok" if ok else "bad")
        self.api.post(f"/api/village/{self.store.account}/command", {"cmd": "army", "name": name}, done)

    def active_recording(self):
        S = self.store.S
        plan = next((p for p in S.get("plans", []) if p.get("name") == S.get("active_plan")), None)
        return (plan or {}).get("recording", "")

    def render_recordings(self):
        self.rec_flow.clear()
        cur = self.active_recording()
        if not self.recordings:
            self.rec_flow.addWidget(label(key="hr_none", role="sub"))
            return
        for r in self.recordings:
            card = Box(border=TOKENS["purple"] if r["name"] == cur else TOKENS["border"])
            h = QHBoxLayout(card)
            h.setContentsMargins(10, 8, 10, 8)
            h.setSpacing(10)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("film", 22, "#F7E3BC"))
            h.addWidget(ic)
            box = QVBoxLayout()
            box.setSpacing(0)
            box.addWidget(label(r["name"], "h3"))
            box.addWidget(label(f"{r.get('touches', 0)} {tr('rec_taps')} · {int(r.get('duration') or 0)} {tr('seconds')}", "dim"))
            h.addLayout(box)
            if r["name"] == cur:
                h.addWidget(StatusPill("ok", tr("hr_active")))
                off = IconButton("stop", "hr_off", size=13)
                off.clicked.connect(self.recording_off)
                h.addWidget(off)
            else:
                use = IconButton("play", "hr_use", kind="go", size=13)
                use.clicked.connect(lambda _=False, n=r["name"]: self.use_recording(n))
                h.addWidget(use)
            self.rec_flow.addWidget(card)

    def use_recording(self, name):
        S = self.store.S
        plans = S.setdefault("plans", [])
        plan = next((p for p in plans if p.get("recording") == name), None)
        if plan is None:
            base = dict(plans[0]) if plans else {}
            plan = dict(base, name="REC " + name, army="", recording=name)
            plans.append(plan)
        S["active_plan"] = plan["name"]
        S.setdefault("tasks", {})["home_attacks"] = True
        self.store.changed()
        acc = self.store.account

        def after_save(ok):
            st = self.poller.account_state()
            self.ctx.window.account_action(acc, "wake" if st.get("running") else "start")
            self.ctx.toast(tr("hr_started").replace("{n}", name), "ok")
        self.store.save(silent=True, done=after_save)
        self.render_recordings()

    def recording_off(self):
        self.store.S["active_plan"] = ""
        self.store.changed()
        self.store.save(silent=True)
        self.ctx.toast(tr("hr_offed"), "info")
        self.render_recordings()

    def pause(self, minutes):
        self.ctx.window.account_action(self.store.account, "pause", {"minutes": minutes})

    def on_state(self, st):
        self.render_accounts()
        acc = self.poller.account_state()
        k = status_key(acc)
        now = st.get("current_time") or time.time()
        self.live_rows["account"].setText(self.store.account or "—")
        self.live_rows["state"].setText(tr("st_" + k))
        try: last = float(acc.get("status"))
        except (TypeError, ValueError): last = None
        self.live_rows["last_cycle"].setText(time.strftime("%H:%M:%S", time.localtime(last)) if last else "—")
        interval = float(self.store.get("schedule.check_interval", 5) or 0) * 60
        self.live_rows["next_cycle"].setText(fmt_dur(max(0, last + interval - now)) if last else "—")
        sch = self.store.get("schedule", {}) or {}
        self.live_rows["schedule"].setText(f"{sch.get('start', '')} - {sch.get('end', '')}" if sch.get("enabled") else tr("sched_off"))
        end = acc.get("end_time") or 0
        self.pause_left.setText(f"{tr('paused_until')} {fmt_dur(end - now)}" if end > now else "")
        self.t_state.set(tr("st_" + k))

    def on_system(self, s):
        self.t_cpu.set("—" if s.get("cpu") is None else f"{round(s['cpu'])}%", s.get("cpu"))
        ram = s.get("ram")
        self.t_ram.set("—" if ram is None else f"{round(ram)}%" + (f" • {s['ram_mb']} MB" if s.get("ram_mb") else ""), ram)
        self.t_up.set(fmt_dur(s.get("uptime")) if s.get("uptime") else "—")
        self.t_adb.set(s.get("adb") or "—")
        self.t_emu.set({"bluestacks": "BlueStacks", "ldplayer": "LDPlayer", "mumu": "MuMu"}.get(s.get("emulator"), s.get("emulator") or "—"))
        acc = self.poller.account_state()
        k = status_key(acc)
        self.t_state.set(tr("ph_" + s["phase"]) if (k == "running" and s.get("phase")) else tr("st_" + k))

    def on_stats(self, d):
        tot, per_a, per_h = d.get("totals", {}), d.get("per_attack", {}), d.get("per_hour", {})
        for w, k in ((self.r_gold, "gold"), (self.r_elixir, "elixir"), (self.r_dark, "dark")):
            w.value.setText(fmt_num(tot.get(k, 0)))
            w.sub.setText(f"{tr('per_hour')}: {fmt_num(per_h.get(k, 0))}")
        vals = {"kpi_attacks": d.get("attacks", 0), "kpi_searches": d.get("searches", 0), "kpi_skipped": d.get("skipped", 0),
                "kpi_walls": d.get("walls", 0), "kpi_upgrades": d.get("upgrades", 0), "kpi_cycles": d.get("cycles", 0)}
        for k, n in vals.items(): self.kpis[k].setText(fmt_num(n))
        avg = d.get("avg_cycle_seconds")
        self.kpis["kpi_avg"].setText(f"{int(avg) // 60}{tr('minutes_short')} {int(avg) % 60}{tr('seconds_short')}" if avg else "—")
        recent = list(reversed(d.get("recent_attacks", [])[:8]))
        self.chart.empty_text = tr("no_attacks") if tr("no_attacks") != "no_attacks" else "—"
        self.chart.set_data([(time.strftime("%H:%M", time.localtime(a.get("t", 0))), [a.get("gold", 0), a.get("elixir", 0), a.get("dark", 0)]) for a in recent])
        atk = d.get("recent_attacks", [])
        good = sum(1 for a in atk if (a.get("gold") or 0) + (a.get("elixir") or 0) > 0)
        self.ring.set_value(good / len(atk) if atk else 0, caption=tr("efficiency"))

    def render_accounts(self):
        self.acc_flow.clear()
        st = self.poller.last.get("state") or {}
        accounts = self.store.APP.get("accounts", [])
        if not accounts:
            self.acc_flow.addWidget(label(key="no_accounts", role="sub"))
            return
        for n, acc in enumerate(accounts):
            a = next((x for x in st.get("accounts", []) if x.get("id") == acc), {})
            k = status_key(a)
            card = Box(border=TOKENS["purple"] if acc == self.store.account else TOKENS["border"])
            card.setCursor(Qt.PointingHandCursor)
            h = QHBoxLayout(card)
            h.setContentsMargins(10, 8, 10, 8)
            h.setSpacing(10)
            from ..widgets.avatar import Avatar, display_name
            h.addWidget(Avatar(acc, 42))
            box = QVBoxLayout()
            box.setSpacing(2)
            box.addWidget(label(display_name(self.store, acc), "h3"))
            box.addWidget(StatusPill(k))
            h.addLayout(box)
            if a.get("running"):
                b = IconButton("stop", kind="stop", icon_color="#FCA5A5", size=14, tip_key="stop")
                b.clicked.connect(lambda _=False, x=acc: self.ctx.window.account_action(x, "stop"))
            else:
                b = IconButton("play", kind="go", size=14, tip_key="start")
                b.clicked.connect(lambda _=False, x=acc: self.ctx.window.account_action(x, "start"))
            h.addWidget(b)
            card.mousePressEvent = lambda e, x=acc: self.store.switch_account(x)
            self.acc_flow.addWidget(card)
