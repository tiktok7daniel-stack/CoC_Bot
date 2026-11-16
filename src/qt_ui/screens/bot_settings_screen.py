"""
Screens 17-18 - Bot settings, two sub-tabs:
 general : language, emulator + LDPlayer folder, emulator auto-start / freeze while idle, start with
           Windows, auto-updater, Telegram notifications (with a test message), OCR engines
           (Tesseract status / path / install, EasyOCR fallback, Groq key), GitHub error reporting
 sch     : schedule (on/off, from-to, days), cycle interval, session limits, natural breaks,
           keep game open, anti-AFK, apply changes immediately
"""
import json, threading, urllib.request

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import (Chip, Combo, GlassCard, IconButton, NumField, StatusPill, Toggle, bind_combo, bind_line,
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
        gen.add(combo_row(st, "emulator", "emulator", [("ldplayer", "emu_ld"), ("bluestacks", "emu_bs"), ("mumu", "emu_mumu")],
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
        ocr.add(note("easyocr_fallback", "info"))
        ocr.add(form_row("groq_key", None, secret_field(st, "groq_api_key", "gsk_…")))
        g.addWidget(ocr, 1, 1)

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
                res = (True, (data.get("result") or {}).get("username", ""))
            except Exception as e:
                res = (False, str(e))
            self._relay.done.emit(self._tg_result, res)
        threading.Thread(target=work, daemon=True).start()

    def _tg_result(self, res):
        ok, info = res
        self.tg_note.setText(f"@{info}" if ok else info)
        self.tg_note.setProperty("role", "ok" if ok else "bad")
        self.tg_note.style().unpolish(self.tg_note)
        self.tg_note.style().polish(self.tg_note)
