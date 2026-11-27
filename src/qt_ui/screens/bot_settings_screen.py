"""
Screens 17-18 - Bot settings, two sub-tabs:
 general : language, emulator + LDPlayer folder, emulator auto-start / freeze while idle, start with
           Windows, auto-updater, Telegram notifications (with a test message), OCR engines
           (Tesseract status / path / install, EasyOCR fallback, Groq key), GitHub error reporting
 sch     : schedule (on/off, from-to, days), cycle interval, session limits, natural breaks,
           keep game open, anti-AFK, apply changes immediately
"""
import json, threading, urllib.request

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import icons
from ..i18n import on_lang, tr, why_ar
from ..theme import TOKENS
from ..widgets import (Chip, Combo, GlassCard, IconButton, NumField, StatusPill, Toggle, bind_combo, bind_line,
                                bind_num, bind_time, bind_toggle, combo_row, form_row, label, note, num_row, time_edit,
                                toggle_row)
from .base import Screen, grid

DAYS_AR = [5, 6, 0, 1, 2, 3, 4]   # Saturday first for Arabic (0 = Monday)
DAYS_EN = [0, 1, 2, 3, 4, 5, 6]


class _Relay(QObject):
    done = Signal(object, object)


def secret_field(store, path, placeholder=""):
    """Masked input with a show / hide eye."""
    box = QWidget()
    h = QHBoxLayout(box)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(4)
    f = QLineEdit()
    f.setEchoMode(QLineEdit.Password)
    f.setPlaceholderText(placeholder)
    f.setLayoutDirection(Qt.LeftToRight)
    f.setMinimumWidth(320)
    bind_line(store, f, path, "app")
    h.addWidget(f, 1)
    eye = IconButton("eye", kind="ghost", size=15)
    eye.setCheckable(True)
    eye.toggled.connect(lambda on: f.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
    h.addWidget(eye)
    box.field = f
    return box


class BotSettingsScreen(Screen):
    key, title_key, icon_name = "set", "sub_set", "bot"

    def __init__(self, ctx):
        super().__init__(ctx)
        st = self.store
        self._relay = _Relay()
        self._relay.done.connect(lambda fn, r: fn(r))
        L = self.make_tabs([("general", "sn_general", "sliders"), ("sch", "tab_sch", "clock")])

        # ======================= general
        w, g = grid(2)
        gen = GlassCard("general", "sliders", "general_sub")
        self.lang = Combo([("ar", "lang_ar"), ("en", "lang_en")], 200)
        bind_combo(st, self.lang, "language", "app")
        self.lang.currentIndexChanged.connect(lambda _i: ctx.window.apply_language(self.lang.value()))
        gen.add(form_row("language", None, self.lang, icon_name="lang"))
        gen.add(combo_row(st, "emulator", "emulator", [("ldplayer", "emu_ld")],
                          "emulator_sub", 220, "app"))
        ld = QLineEdit()
        ld.setPlaceholderText("D:\\LDPlayer\\LDPlayer9")
        ld.setLayoutDirection(Qt.LeftToRight)
        ld.setMinimumWidth(300)
        bind_line(st, ld, "ldplayer_path", "app")
        gen.add(form_row("ld_path", "ld_path_sub", ld))
        gen.add(toggle_row(st, "auto_emulator", "auto_start_emulator", scope="app"))
        gen.add(toggle_row(st, "suspend_emulator", "suspend_emulator_on_idle", "suspend_emulator_sub", "app"))
        gen.add(toggle_row(st, "start_windows", "start_with_windows", scope="app"))
        gen.add(combo_row(st, "ui_kind", "ui", [("qt", "ui_qt"), ("web", "ui_web")], "ui_kind_sub", 260, "app"))
        g.addWidget(gen, 0, 0)

        upd = GlassCard("updates", "cloud", "updates_sub")
        self.v_cur = label("—", "numsm")
        self.v_new = label("—", "numsm")
        upd.add(form_row("current", None, self.v_cur))
        upd.add(form_row("latest", None, self.v_new))
        ub = QHBoxLayout()
        chk = IconButton("refresh", "update_check", size=14)
        chk.clicked.connect(self.check_update)
        ub.addWidget(chk)
        self.upd_btn = IconButton("download", "update_now", kind="primary", size=14)
        self.upd_btn.clicked.connect(self.apply_update)
        ub.addWidget(self.upd_btn)
        ub.addStretch(1)
        upd.add(ub)
        self.upd_note = label("", "sub", wrap=True)
        upd.add(self.upd_note)
        upd.add(toggle_row(st, "up_auto", "auto_update", "up_auto_sub", "app"))
        upd.add(toggle_row(st, "up_ask_plan", "ask_plan", "up_ask_plan_sub", "app"))
        g.addWidget(upd, 0, 1)

        tg = GlassCard("notifications", "bell", "notifications_sub")
        self.tg_token = secret_field(st, "telegram_bot_token", "123456:ABC-DEF…")
        tg.add(form_row("telegram_token", None, self.tg_token))
        tg.add(form_row("roboflow_key", "roboflow_key_sub", secret_field(st, "roboflow_api_key", "rf_…")))
        tb = IconButton("send", "test_ping", size=14)
        tb.clicked.connect(self.test_telegram)
        tg.add(form_row(None, None, tb, text=""))
        self.tg_note = label("", "sub", wrap=True)
        tg.add(self.tg_note)
        tg.add(toggle_row(st, "nf_upgrade_done", "notify.upgrade_done", "nf_upgrade_done_sub"))
        tg.add(toggle_row(st, "nf_auto_upgrade", "notify.auto_upgrade"))
        tg.add(toggle_row(st, "nf_loot", "notify.loot"))
        tg.add(toggle_row(st, "nf_desktop", "desktop_notify", "nf_desktop_sub", scope="app"))
        tg.add(toggle_row(st, "nf_hud", "show_hud", None, scope="app"))
        tg.add(toggle_row(st, "nf_intro", "intro", None, scope="app"))
        g.addWidget(tg, 1, 0)

        ocr = GlassCard("ocr_title", "text", "ocr_sub")
        self.tess = StatusPill("warn", "—")
        tr_row = QHBoxLayout()
        tr_row.addWidget(self.tess)
        tr_row.addStretch(1)
        vb = IconButton("check", "verify", size=13)
        vb.clicked.connect(self.check_tess)
        tr_row.addWidget(vb)
        self.inst_btn = IconButton("download", "install", size=13)
        self.inst_btn.clicked.connect(self.install_tess)
        tr_row.addWidget(self.inst_btn)
        ocr.add(tr_row)
        tp = QLineEdit()
        tp.setPlaceholderText("C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
        tp.setLayoutDirection(Qt.LeftToRight)
        tp.setMinimumWidth(300)
        bind_line(st, tp, "tesseract_path", "app")
        ocr.add(form_row("tess_path", "tess_path_sub", tp))
        om = Combo([("auto", "ocr_m_auto"), ("medium", "ocr_m_medium"), ("small", "ocr_m_small")], 260)
        bind_combo(st, om, "ocr_model", "app")
        ocr.add(form_row("ocr_model", "ocr_model_sub", om))
        ocr.add(note("easyocr_fallback", "info"))
        ocr.add(form_row("groq_key", None, secret_field(st, "groq_api_key", "gsk_…")))
        g.addWidget(ocr, 1, 1)

        # ======================= speed & power: everything that makes the bot fast, working together
        pw = GlassCard("pw_title", "bolt", "pw_sub")
        self.pw_live = StatusPill("warn", "—")
        self.pw_gpu = StatusPill("warn", "—")
        self.pw_brain = StatusPill("warn", "—")
        self.pw_eyes = StatusPill("warn", "—")
        self.pw_ocr = StatusPill("warn", "—")
        for key, pill in (("pw_live", self.pw_live), ("pw_ocr", self.pw_ocr), ("pw_gpu", self.pw_gpu), ("pw_brain", self.pw_brain),
                          ("pw_eyes", self.pw_eyes)):
            pw.add(form_row(key, None, pill))
        pb = QHBoxLayout()
        self.gpu_btn = IconButton("bolt", "pw_gpu_install", kind="primary", size=14)
        self.gpu_btn.clicked.connect(self.install_gpu)
        self.gpu_btn.setVisible(False)
        pb.addWidget(self.gpu_btn)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QProgressBar
        self.gpu_bar = QProgressBar()
        self.gpu_bar.setRange(0, 100)
        self.gpu_bar.setTextVisible(True)
        self.gpu_bar.setFixedHeight(16)
        self.gpu_bar.setMinimumWidth(220)
        self.gpu_bar.setVisible(False)
        pb.addWidget(self.gpu_bar)
        self.gpu_more = QHBoxLayout()
        self.links_btn = IconButton("link", "pw_links", size=13)
        self.links_btn.clicked.connect(self.show_links)
        self.files_btn = IconButton("folder", "pw_have_files", size=13)
        self.files_btn.clicked.connect(self.install_files)
        self.log_btn = IconButton("list", "pw_details", size=13)
        self.log_btn.clicked.connect(lambda: self.gpu_log.setVisible(not self.gpu_log.isVisible()))
        for b in (self.links_btn, self.files_btn, self.log_btn): self.gpu_more.addWidget(b)
        self.gpu_more.addStretch(1)
        self.gpu_links = QLabel("")
        self.gpu_links.setOpenExternalLinks(True)
        self.gpu_links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.gpu_links.setWordWrap(True)
        self.gpu_links.setVisible(False)
        self.gpu_log = QLabel("")
        self.gpu_log.setWordWrap(True)
        self.gpu_log.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.gpu_log.setLayoutDirection(Qt.LeftToRight)
        self.gpu_log.setStyleSheet("font-family: Consolas, monospace; font-size: 8.5pt; color: %s;" % TOKENS["muted"])
        self.gpu_log.setVisible(False)
        self._gpu_timer = QTimer(self)
        self._gpu_timer.timeout.connect(self.check_power)
        self._gpu_mode = "install"
        rb = IconButton("refresh", "verify", size=13)
        rb.clicked.connect(lambda: self.check_power(True))
        pb.addWidget(rb)
        pb.addStretch(1)
        pw.add(pb)
        self.pw_note = label("", "sub", wrap=True)
        pw.add(self.pw_note)
        pw.add(self.gpu_more)
        pw.add(self.gpu_links)
        pw.add(self.gpu_log)
        g.addWidget(pw, 3, 0, 1, 2)

        gh = GlassCard("gh_title", "github", "gh_sub")
        gh.add(form_row("gh_token", "gh_token_sub", secret_field(st, "github_token", "github_pat_…")))
        gh.add(toggle_row(st, "gh_auto", "auto_report", "gh_auto_sub", "app"))
        gh.add(note("gh_warn", "shield", TOKENS["warn"]))
        gh.add(note("privacy", "eye"))
        g.addWidget(gh, 2, 0, 1, 2)
        L["general"].addWidget(w)
        L["general"].addStretch(1)


        # ======================= schedule
        w, g = grid(2)
        sch = GlassCard("sch_title", "calendar", "sch_sub")
        sch.add(toggle_row(st, "sch_enabled", "schedule.enabled"))
        sch.add(form_row("from", None, bind_time(st, time_edit(), "schedule.start")))
        sch.add(form_row("until", "until_sub", bind_time(st, time_edit(), "schedule.end")))
        sch.add(label(key="days", role="h3"))
        self.days_host = QWidget()
        self.days = QHBoxLayout(self.days_host)
        self.days.setContentsMargins(0, 4, 0, 4)
        self.days.setSpacing(6)
        sch.add(self.days_host)
        self.sch_note = label("", "sub", wrap=True)
        sch.add(self.sch_note)
        g.addWidget(sch, 0, 0)
        inter = GlassCard("interval_title", "hourglass", "interval_sub")
        inter.add(num_row(st, "check_interval", "schedule.check_interval", None, "minutes", 0, 1440, 1, 90))
        inter.add(toggle_row(st, "live_stream", "live_stream", "live_stream_sub", scope="app"))
        inter.add(toggle_row(st, "keep_wall_builder", "keep_wall_builder", "keep_wall_builder_sub", scope="app"))
        inter.add(toggle_row(st, "daily_rewards", "daily_rewards", "daily_rewards_sub", scope="app"))
        inter.add(toggle_row(st, "battle_speed", "battle_speed", "battle_speed_sub", scope="app"))
        inter.add(toggle_row(st, "fast_capture", "fast_capture", "fast_capture_sub", scope="app"))
        inter.add(toggle_row(st, "never_close", "game.never_close", "never_close_sub"))
        inter.add(toggle_row(st, "keep_open", "game.keep_open", "keep_open_sub"))
        inter.add(toggle_row(st, "anti_idle", "game.anti_idle", "anti_idle_sub"))
        inter.add(toggle_row(st, "apply_instantly", "game.apply_instantly", "apply_instantly_sub"))
        inter.add(note("interval_note"))
        g.addWidget(inter, 0, 1)
        L["sch"].addWidget(w)
        L["sch"].addStretch(1)

        st.loaded.connect(self.render_days)
        st.on_change(self._sched_note)
        on_lang(self.render_days)

    # ---------------------------------------------------------------- lifecycle
    def on_show(self):
        self.check_tess()
        self.check_update()
        self.check_power()

    def on_sub(self, key):
        if key == "general": self.check_tess()

    # ---------------------------------------------------------------- days
    def render_days(self):
        while self.days.count():
            it = self.days.takeAt(0)
            if it.widget(): it.widget().deleteLater()
        cur = set(self.store.get("schedule.days", []) or [])
        for d in (DAYS_AR if self.layoutDirection() == Qt.RightToLeft else DAYS_EN):
            c = Chip(tr(f"d{d}"))
            c.setChecked(d in cur)
            c.toggled.connect(lambda on, d=d: self._day(d, on))
            self.days.addWidget(c)
        self.days.addStretch(1)
        self._sched_note()

    def _day(self, d, on):
        days = set(self.store.get("schedule.days", []) or [])
        if on: days.add(d)
        else: days.discard(d)
        self.store.set("schedule.days", sorted(days))

    def _sched_note(self):
        s = self.store.get("schedule", {}) or {}
        if not s: return
        if not s.get("enabled"): self.sch_note.setText(tr("sched_off"))
        else: self.sch_note.setText(f"{s.get('start', '')} - {s.get('end', '')}  ·  {len(s.get('days', []))}/7")

    # ---------------------------------------------------------------- updates
    def check_update(self):
        def got(r):
            if not isinstance(r, dict): return
            self.v_cur.setText(str(r.get("current", "—")))
            self.v_new.setText(str(r.get("latest", "—")))
            if not r.get("ok"): self.upd_note.setText(tr("upd_err") + (f"  {r.get('error', '')}" if r.get("error") else ""))
            else: self.upd_note.setText(tr("upd_avail") if r.get("available") else tr("upd_same"))
        self.api.get("/api/update/check", got, timeout=30)

    def apply_update(self):
        self.upd_btn.setEnabled(False)
        self.upd_note.setText(tr("upd_working"))

        def done(r):
            self.upd_btn.setEnabled(True)
            if isinstance(r, dict) and r.get("ok"):
                self.upd_note.setText(tr("up_ready_note"))
                uc = self.ctx.window.update_center
                uc._ready(str(r.get("version") or ""))
                uc.dialog.open_for(self.v_cur.text(), str(r.get("version") or self.v_new.text()), ready=True)
            else:
                self.upd_note.setText(tr("upd_err") + f"  {(r or {}).get('error', '')}")
        self.api.post("/api/update/apply", {}, done, timeout=600)

    # ---------------------------------------------------------------- OCR
    def check_tess(self):
        def got(r):
            if not isinstance(r, dict): return
            if r.get("found"):
                self.tess.set("ok", f"{tr('tess_found')}  {r.get('version') or ''}")
                self.inst_btn.setVisible(False)
            else:
                self.tess.set("warn", tr("tess_missing"))
                self.inst_btn.setVisible(r.get("platform") == "win32")
        self.api.get("/api/tesseract", got, timeout=30)

    # ---------------------------------------------------------------- speed & power
    def check_power(self, refresh=False):
        def got(r):
            if not isinstance(r, dict): return
            self._capture_why = ""
            bots = list((r.get("bots") or {}).values())
            b = max(bots, key=lambda x: x.get("t", 0)) if bots else {}
            src = b.get("source")
            if src:
                self.pw_live.set("ok" if src in ("live", "window") else "warn",
                                 tr("pw_src_" + src).format(ms=b.get("look_ms", "?")))
                why = []
                if src != "live" and b.get("live_why"): why.append(tr("pw_live_why").format(w=why_ar(b["live_why"])))
                if src == "adb" and b.get("window_why"): why.append(tr("pw_window_why").format(w=why_ar(b["window_why"])))
                self.pw_live.setToolTip("\n".join(why))
                self._capture_why = "\n".join(why)
            else:
                self.pw_live.set("warn", tr("pw_src_none"))
            card = r.get("card")
            name = (card or {}).get("name", "")
            self.gpu_bar.setVisible(False)
            self._gpu_mode = "install"
            if not card:
                self.pw_gpu.set("warn", tr("pw_gpu_none"))
                self.gpu_btn.setVisible(False)
            elif r.get("installing"):
                pg = r.get("progress") or {}
                stage = pg.get("stage", "start")
                if stage == "install" and pg.get("of_mb"):
                    self.pw_gpu.set("warn", tr("pw_gpu_unpack").format(pct=pg.get("pct", 0)))
                    self.gpu_bar.setRange(0, 100)
                    self.gpu_bar.setValue(int(pg.get("pct", 0)))
                elif stage == "download":
                    self.pw_gpu.set("warn", tr("pw_gpu_dl").format(pct=pg.get("pct", 0), gb=round(pg.get("mb", 0) / 1024, 2),
                                                                  of=round(pg.get("of_mb", 0) / 1024, 2), speed=pg.get("speed", 0)))
                    self.gpu_bar.setRange(0, 100)
                    self.gpu_bar.setValue(int(pg.get("pct", 0)))
                else:
                    self.pw_gpu.set("warn", tr("pw_stage_" + stage) if tr("pw_stage_" + stage) != "pw_stage_" + stage else tr("pw_stage_start"))
                    self.gpu_bar.setRange(0, 0)                  # moving bar: working, no percentage yet
                self.gpu_bar.setVisible(True)
                self.gpu_btn.setVisible(False)
                self._gpu_timer.start(3000)                      # follow the download
            elif r.get("ready") and r.get("active") and b.get("ocr_gpu") is False:
                # installed and loaded, but the running bot still reads on the processor (started before?)
                self.pw_gpu.set("warn", tr("pw_gpu_bot_cpu").format(name=name))
                self.gpu_btn.setVisible(False)
            elif r.get("ready") and r.get("active"):
                self.pw_gpu.set("ok", tr("pw_gpu_on").format(name=name) if b.get("ocr_gpu") else tr("pw_gpu_armed").format(name=name))
                self.gpu_btn.setVisible(False)
            elif r.get("ready"):
                self.pw_gpu.set("ok", tr("pw_gpu_ready").format(name=name))
                self._gpu_mode = "restart"
                self.gpu_btn.setText(tr("pw_restart"))
                self.gpu_btn.setVisible(True)
            else:
                self.pw_gpu.set("warn", tr("pw_gpu_off").format(name=name))
                self.gpu_btn.setText(tr("pw_gpu_retry") if r.get("result") in ("failed", "no_cuda", "interrupted") else tr("pw_gpu_install"))
                self.gpu_btn.setVisible(True)
            if not r.get("installing"): self._gpu_timer.stop()
            m = b.get("model") or {}
            mem = b.get("memory") or {}
            btxt = tr("pw_brain_txt").format(kinds=m.get("kinds", 0), pics=m.get("screens", 0), mem=mem.get("screens", 0))
            dp = m.get("deep") or {}
            if dp.get("ready") or dp.get("downloaded"): btxt += " · " + tr("pw_brain_deep").format(n=dp.get("examples", 0))
            self.pw_brain.set("ok" if m.get("screens") else "warn", btxt)
            if m.get("now_title"): self.pw_brain.setToolTip(tr("pw_now").format(t=m["now_title"]))
            v = b.get("vision") or {}
            if v.get("model"):
                self.pw_eyes.set("ok", tr("pw_eyes_on").format(n=v.get("classes", 0), acc=int(round((v.get("map50") or 0) * 100))))
                if v.get("last"): self.pw_eyes.setToolTip(tr("pw_eyes_last").format(t=v["last"]))
            else:
                self.pw_eyes.set("warn", tr("pw_eyes_off"))
            o = b.get("ocr") or {}
            if o.get("model"):
                dev = tr("pw_ocr_gpu") if o.get("device") in ("cuda", "dml") else tr("pw_ocr_cpu")
                txt = tr("pw_ocr_on").format(m=tr("pw_ocr_" + o["model"]), dev=dev, ms=o.get("ms") or "—")
                if o.get("downloading"): txt += " · " + tr("pw_ocr_dl")
                self.pw_ocr.set("ok", txt)
            else:
                self.pw_ocr.set("warn", tr("pw_ocr_off"))
            log = [l for l in (r.get("log") or "").strip().splitlines() if l.strip()]
            self.gpu_log.setText("\n".join(log[-14:]) or "—")
            for b in (self.links_btn, self.files_btn, self.log_btn): b.setVisible(bool(card))
            self.files_btn.setEnabled(not r.get("installing"))
            res = r.get("result") or ""
            if getattr(self, "_capture_why", "") and not r.get("installing"):
                self.pw_note.setText(self._capture_why)
            if r.get("installing"): self.pw_note.setText(tr("pw_dl_note"))
            elif res == "interrupted": self.pw_note.setText(tr("pw_gpu_interrupted"))
            elif res in ("failed", "no_cuda") or res.startswith("failed"):
                self.pw_note.setText(tr("pw_gpu_failed") + "\n" + (r.get("error") or (log[-1] if log else "")))
            elif not getattr(self, "_capture_why", ""): self.pw_note.setText("")
        self.api.get("/api/gpu" + ("?refresh=1" if refresh else ""), got, timeout=150)

    def install_gpu(self):
        if getattr(self, "_gpu_mode", "install") == "restart":
            self.ctx.window.restart_app()
            return
        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("pw_installing"), "ok")
                QTimer.singleShot(800, self.check_power)
            else:
                err = (r or {}).get("error", "") if isinstance(r, dict) else ""
                msg = tr("pw_gpu_none") if err == "no_nvidia" else tr("pw_start_fail") + " " + str(err or r)
                self.pw_note.setText(msg)
                self.ctx.toast(msg, "bad")
        self.api.post("/api/gpu/install", {}, done)

    def show_links(self):
        """The exact files for this PC, to download in the browser (then: I have the files)."""
        self.gpu_links.setVisible(True)
        self.gpu_links.setText(tr("checking"))
        def got(r):
            if isinstance(r, dict) and r.get("ok"):
                download_icon = icons.img_tag("download", 10, TOKENS["crimson"])
                rows = "".join(f'<div style="margin:4px 0">{download_icon} <a href="{f["url"]}" style="color:{TOKENS["crimson"]}">{f["name"]}</a></div>'
                               for f in r.get("files", []))
                self.gpu_links.setText(f'<div>{tr("pw_links_help")}</div>{rows}')
            else:
                self.gpu_links.setText(tr("pw_links_fail") + " " + str((r or {}).get("error", "") if isinstance(r, dict) else r))
        self.api.get("/api/gpu/links", got, timeout=90)

    def install_files(self):
        from PySide6.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, tr("pw_have_files"), "", "Python wheel (*.whl)")
        if not paths: return
        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.toast(tr("pw_files_started"), "ok")
                QTimer.singleShot(800, self.check_power)
            else:
                msg = tr("pw_start_fail") + " " + str((r or {}).get("error", "") if isinstance(r, dict) else r)
                self.pw_note.setText(msg)
                self.ctx.toast(msg, "bad")
        self.api.post("/api/gpu/install_files", {"paths": paths}, done)

    def install_tess(self):
        def done(r):
            self.ctx.toast(tr("tess_installing") if isinstance(r, dict) and r.get("ok") else tr("save_err"),
                           "ok" if isinstance(r, dict) and r.get("ok") else "bad")
        self.api.post("/api/tesseract/install", {}, done)

    # ---------------------------------------------------------------- Telegram test
    def test_telegram(self):
        token = self.tg_token.field.text().strip()
        if not token:
            self.tg_note.setText(tr("tg_need_token") if tr("tg_need_token") != "tg_need_token" else tr("telegram_token"))
            return
        self.tg_note.setText(tr("checking"))

        def work():
            try:
                with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=15) as r:
                    data = json.loads(r.read().decode("utf-8"))
                name = (data.get("result") or {}).get("username", "")
                # a real message to the phone (the chat that sent /start to this bot)
                from pathlib import Path
                try: own = json.loads((Path.home() / ".CoC_Bot" / "telegram_chat.json").read_text(encoding="utf-8"))
                except (OSError, ValueError): own = {}
                chat = own.get("chat") if own.get("bot") == token.split(":")[0] else None
                if chat is None:
                    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as r:
                        ups = [u.get("message") for u in json.loads(r.read().decode("utf-8")).get("result", []) if u.get("message")]
                    chat = ups[-1]["chat"]["id"] if ups else None
                if chat is None:
                    check = icons.img_tag("check", 12, TOKENS["ok"])
                    res = (False, f"@{name} {check} — افتح البوت ده في تليجرام وابعتله /start، والبرنامج مفتوح، وبعدين دوس تجربة تاني")
                else:
                    import urllib.parse
                    check = icons.img_tag("check", 12, TOKENS["ok"])
                    body = urllib.parse.urlencode({"chat_id": chat, "text": f"{check} التليجرام شغال — الإشعارات هتوصلك هنا"}).encode()
                    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=15) as r:
                        ok = json.loads(r.read().decode("utf-8")).get("ok")
                    check = icons.img_tag("check", 12, TOKENS["ok"])
                    res = (bool(ok), f"@{name} {check} — بعتّلك رسالة على التليفون" if ok else "ما قدرتش أبعت الرسالة")
            except Exception as e:
                res = (False, str(e))
            self._relay.done.emit(self._tg_result, res)
        threading.Thread(target=work, daemon=True).start()

    def _tg_result(self, res):
        ok, info = res
        self.tg_note.setText(info)
        self.tg_note.setProperty("role", "ok" if ok else "bad")
        self.tg_note.style().unpolish(self.tg_note)
        self.tg_note.style().polish(self.tg_note)
