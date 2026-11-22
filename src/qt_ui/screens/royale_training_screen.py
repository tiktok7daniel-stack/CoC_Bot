"""
Training — every learning part of the Clash Royale AI in one place (6.02, the user's request: "what is trained,
what is being done, I want to see it"):

  eyes          the arena detector (YOLO): what data it downloaded, its stage, its accuracy before -> after
  self-play     the AI plays itself in the battle engine (Expert Iteration): rounds, versions that passed its test
  play brains   the networks that choose the moves (learned from 252k pro games): their accuracy
  own pictures  pictures of this PC's battles kept for the next training

Each part says in one line what it is for, whether it is trained / training now, and has its buttons: start it, and
"show the window" (a console that follows its log live).
"""
import json, os, subprocess, sys, time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS
from ..widgets.controls import GlassCard, IconButton, label
from .base import Screen, page

HOME = Path.home() / ".CoC_Bot"


def _read(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _ago(t):
    if not t: return "—"
    d = time.time() - float(t)
    if d < 3600: return f"{int(d // 60)} min"
    if d < 86400: return f"{int(d // 3600)} h"
    return f"{int(d // 86400)} d"


def _bring(part):
    """6.9.4: the training's OWN console (its title contains `part`) brought to the front — the real window with every
    line and every progress bar, not a copy of the log. -> True when found."""
    if sys.platform != "win32": return False
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _l):
        n = u.GetWindowTextLengthW(hwnd)
        if n:
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if part in buf.value: found.append(hwnd)
        return True
    u.EnumWindows(each, 0)
    for h in found:
        u.ShowWindow(h, 9)                      # restore if minimised
        u.SetForegroundWindow(h)
    return bool(found)


def _watch(log_path, title, own=None):
    """The training's own console in front when it runs; else a console that follows its log live."""
    if own and _bring(own): return True
    if sys.platform != "win32" or not Path(log_path).exists(): return False
    cmd = (f"$Host.UI.RawUI.WindowTitle='{title}'; Get-Content -Path '{log_path}' -Wait -Tail 60 -Encoding UTF8")
    subprocess.Popen(["powershell", "-NoExit", "-NoProfile", "-Command", cmd], creationflags=0x00000010)
    return True


class RoyaleTrainingScreen(Screen):
    key, title_key, icon_name = "royale_training", "rtr_title", "school"

    def __init__(self, ctx):
        super().__init__(ctx)
        sa, v = page(14)
        from PySide6.QtWidgets import QLayout
        v.setSizeConstraint(QLayout.SetMinimumSize)      # the page grows with its text (and scrolls)
        self.root.addWidget(sa)
        intro = label(key="rtr_intro", wrap=True)
        intro.setProperty("role", "sub")
        v.addWidget(intro)

        def card(title, icon, sub, buttons):
            c = GlassCard(title, icon, sub, pad=16)
            txt = label("", wrap=True)
            txt.setTextFormat(Qt.RichText)
            c.add(txt)
            row = QHBoxLayout()
            for key, ic, kind, fn in buttons:
                b = IconButton(ic, key, kind=kind, size=14)
                b.setMinimumHeight(38); b.setMinimumWidth(170)
                b.clicked.connect(fn)
                row.addWidget(b)
            row.addStretch(1)
            hold = QWidget(); hold.setLayout(row)
            c.add(hold)
            v.addWidget(c)
            return txt

        self.t_eyes = card("rtr_eyes", "eye", "rtr_eyes_sub", [
            ("rtr_train_eyes", "play", "go", self.train_eyes),
            ("rtr_stop", "stop", None, self.stop_eyes),
            ("rtr_watch", "terminal", None, lambda: self.watch(HOME / "royale_train" / "train.log", "eyes"))])
        self.t_self = card("rtr_self", "bolt", "rtr_self_sub", [
            ("rtr_train_self", "play", "go", self.train_self),
            ("rtr_stop", "stop", None, self.stop_self),
            ("rtr_watch", "terminal", None, lambda: self.watch(HOME / "royale_ai" / "exit" / "train.log", "self"))])
        self.t_brain = card("rtr_brain", "school", "rtr_brain_sub", [])
        v.addStretch(1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        on_lang(self.refresh)

    # ------------------------------------------------------------------ buttons
    def watch(self, path, what):
        own = "تدريب عيون كلاش رويال" if what == "eyes" else "الذكاء الاصطناعي بيلعب ضد نفسه"
        if not _watch(path, tr("rtr_eyes") if what == "eyes" else tr("rtr_self"), own):
            self.ctx.banner(tr("rtr_no_log"), "bad", "x")

    def train_eyes(self):
        try:
            from royale import trainer
            if trainer.running():                       # 6.9.5: really running (its process), not an old status
                _bring("تدريب عيون كلاش رويال")
                self.ctx.banner(tr("rtr_already"), "ok", "school"); return
            trainer.start(self.store.account or "main")
            self.ctx.banner(tr("rtr_started_eyes"), "ok", "school")
            QTimer.singleShot(2500, lambda: _bring("تدريب عيون كلاش رويال"))   # its window in front of you
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")

    def stop_eyes(self):
        try:
            from royale import trainer
            trainer.stop()
            self.ctx.banner(tr("rtr_stopped_eyes"), "ok", "stop")
            self.refresh()
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")

    def train_self(self):
        try:
            from royale import exit_train
            miss = exit_train.missing()
            if miss:
                self.ctx.banner(tr("royale_ai_missing") + ", ".join(miss), "bad", "x"); return
            deck = list(self.store.get("royale.deck", []) or [])
            if len(deck) != 8:
                self.ctx.banner(tr("rh_need_deck"), "bad", "x"); return
            ok, msg = exit_train.start(deck, self.store.account or "main")
            self.ctx.banner(tr("rh_train_started") if ok else msg, "ok" if ok else "bad", "bolt")
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")

    def stop_self(self):
        try:
            from royale import exit_train
            exit_train.stop()
            self.ctx.banner(tr("rh_train_stopping"), "ok", "stop")
        except Exception as e:
            self.ctx.banner(str(e), "bad", "x")

    def on_show(self):
        self.refresh()

    # ------------------------------------------------------------------ what each part shows
    def refresh(self):
        if not self.isVisible(): return
        g, r, y = "#4ade80", "#f87171", TOKENS.get("gold", "#f5b740")
        # the eyes
        st = _read(HOME / "royale_train" / "status.json")
        stage = st.get("stage") or "none"
        try:
            from royale import trainer as _tr
            running = _tr.running()                     # 6.9.5: its process is alive (not an old status)
        except Exception:
            running = False
        if not running and stage not in ("none", "done", "error", "no_gpu", "stopped"):
            stage = "stopped"                           # it was closed: what is done is kept
        lines = [f"<b>{tr('rtr_state')}:</b> " + (f"<span style='color:{y}'>● {tr('rtr_running')}</span> — "
                                                  if running else "") + (tr("rt_" + stage) if tr("rt_" + stage) != "rt_" + stage else stage)
                 + (f" — {st['note']}" if st.get("note") else "")]
        if running and st.get("alive"):                  # 6.9.3: a sign of life every 20 s (the window's heartbeat)
            ago = int(time.time() - float(st["alive"]))
            col = g if ago < 60 else (y if ago < 180 else r)
            lines.append(f"<span style='color:{col}'>💓 {tr('rtr_alive')}: {ago} s</span>"
                         + (f" · {st['card_line']}" if st.get("card_line") else ""))
        if st.get("base_map50") is not None and st.get("new_map50") is not None:
            used = st.get("used")
            lines.append(f"<b>{tr('rtr_accuracy')}:</b> {100 * st['base_map50']:.1f}% → {100 * st['new_map50']:.1f}% "
                         + (f"<span style='color:{g}'>✅ {tr('rt_used')}</span>" if used else f"({tr('rtr_kept_old')})"))
        hd = st.get("hand") or {}
        if hd.get("score") is not None:                  # the hand-card model (6.6)
            lines.append(f"<b>{tr('rtr_hand')}:</b> {100 * float(hd['score']):.1f}% "
                         + (f"<span style='color:{g}'>✅ {tr('rt_used')}</span>" if hd.get("used") else f"({tr('rtr_kept_old')})"))
        if st.get("finished"): lines.append(f"<b>{tr('rtr_last')}:</b> {_ago(st['finished'])}")
        pg = st.get("prog") or {}
        if pg and stage != "done":                      # what the next start does not do again
            done = (["🃏"] if pg.get("hand") else []) + (["📦"] if pg.get("data") else []) + \
                (["1/3"] if pg.get("base") else []) + [f"✔ {k}" for k in (pg.get("done") or {})]
            if done: lines.append(f"<b>{tr('rtr_kept')}:</b> " + " · ".join(done))
        data = st.get("data") or {}
        if data:
            tot = sum(int(d.get("n", 0)) for d in data.values())
            lines.append(f"<br><b>📦 {tr('rt_data_list')} — {tot:,}</b>")
            for name, d in data.items():
                n = int(d.get("n", 0))
                lines.append(f"{'✅' if n else '⚠'} {name}: <b>{n:,}</b>" + (f" <small>({d['note']})</small>" if d.get("note") else ""))
        if st.get("pictures"): lines.append(f"🖼 {tr('rt_pictures')}: <b>{int(st['pictures']):,}</b>")
        if st.get("error"): lines.append(f"<span style='color:{r}'>⚠ {st['error']}</span>")
        self._set(self.t_eyes, lines)
        # self-play
        pr = _read(HOME / "royale_ai" / "exit" / "progress.json")
        try:
            from royale import exit_train
            on = exit_train.running()
        except Exception:
            on = False
        sl = [f"<b>{tr('rtr_state')}:</b> " + (f"<span style='color:{y}'>● {tr('rtr_running')}</span>" if on else tr("rh_train_off"))]
        if pr:
            sl.append(f"<b>{tr('rh_round')}:</b> {pr.get('iteration', 0)} · <b>{tr('rtr_answers')}:</b> {int(pr.get('answers', 0)):,}"
                      f" · <b>{tr('rh_versions')}:</b> {pr.get('accepted', 0)}"
                      + (f" · <b>{tr('rh_last')}:</b> {int(100 * float(pr.get('last_score', 0)))}%" if pr.get('last_score') is not None else ""))
            sl.append(f"<b>{tr('rtr_last')}:</b> {_ago(pr.get('t'))}")
        else:
            sl.append(tr("rh_train_never"))
        self._set(self.t_self, sl)
        # the play brains + own pictures
        bl = []
        try:
            from royale import policy, board as _bb, frames
            ti, bi = policy.info(), _bb.info()
            if ti: bl.append(f"🧠 {tr('rt_policy')}: <b>{100 * ti.get('card_in_hand', 0):.0f}% / {100 * ti.get('play', 0):.0f}%</b>")
            if bi: bl.append(f"🧩 {tr('rt_board')}: <b>{100 * bi.get('card_in_hand', 0):.0f}% / {100 * bi.get('tile_within1', 0):.0f}%</b>")
            bl.append(f"📷 {tr('rt_frames')}: <b>{frames.count():,}</b>")
            # the eyes' runtime (6.6): TensorRT FP16 / CUDA / DirectML, with its measured ms
            import trt_engine
            ti = trt_engine.info()
            if ti.get("mode"):
                ms = ", ".join(f"{k.replace('.onnx', '')} {v.get('trt_ms', v.get('cuda_ms'))} ms"
                               for k, v in (ti.get("bench") or {}).items())
                bl.append(f"⚡ {tr('rtr_runtime')}: <b>{'TensorRT FP16' if ti['mode'] == 'trt' else 'CUDA'}</b>"
                          + (f" <small>({ms})</small>" if ms else ""))
            elif trt_engine.LOG.exists() and time.time() - trt_engine.LOG.stat().st_mtime < 900:   # the bot sets it up
                bl.append(f"⚡ {tr('rtr_runtime')}: <span style='color:{y}'>{tr('rtr_trt_setup')}</span>")
        except Exception:
            pass
        self._set(self.t_brain, bl or ["—"])

    @staticmethod
    def _set(lab, lines):
        lab.setText("<br>".join(lines))
        lab.setMinimumHeight(24 * sum(1 + l.count("<br>") for l in lines) + 6)   # every line shows
