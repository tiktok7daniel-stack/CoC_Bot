"""
Capture mode card (top of "Learning with Claude"):
  Start -> the bot only watches while you play and photographs every new screen (no repeats)
  Done  -> "I took N pictures": a gallery of all of them (where you tapped is marked); delete what you don't want
  Send to Claude -> all pictures + their words go to the learning repo in one commit; then tell Claude in the chat
"""
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QMessageBox, QVBoxLayout, QWidget

from .. import icons
from ..i18n import tr
from ..theme import TOKENS
from ..widgets.controls import Box, GlassCard, IconButton, label, note
from ..widgets.seal import AnimatedSeal


class Thumb(QWidget):
    """One captured screen: picture (rounded), its number, a gold ring where you tapped before it, delete."""

    def __init__(self, panel, session, shot):
        super().__init__()
        self.panel, self.session, self.shot = panel, session, shot
        self.pm = None
        self.setFixedSize(240, 150)
        self.setToolTip(" · ".join(shot.get("words", [])[:20]) or "—")
        panel.api.get(f"/api/capture/{panel.store.account}/img/{session}/{shot['file']}", self._got, raw=True)
        self.rm = IconButton("x", None, "stop", tip_key="cp_delete_one", size=12)
        self.rm.setParent(self)
        self.rm.setFixedSize(28, 28)
        self.rm.move(self.width() - 34, 6)
        self.rm.clicked.connect(lambda: panel.delete_one(shot["file"]))

    def _got(self, data):
        if not data: return
        pm = QPixmap()
        if pm.loadFromData(data):
            self.pm = pm
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor("#0B0B10"))
        if self.pm is not None:
            p.save()
            p.setClipPath(path)
            p.drawPixmap(r, self.pm, QRectF(self.pm.rect()))
            tap = self.shot.get("tap")
            if tap:
                c = QPointF(r.left() + r.width() * tap[0], r.top() + r.height() * tap[1])
                p.setPen(QPen(QColor(245, 183, 64), 2.2))
                p.setBrush(QColor(245, 183, 64, 60))
                p.drawEllipse(c, 9, 9)
            p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        badge = QRectF(r.left() + 8, r.bottom() - 30, 46, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(badge, 11, 11)
        p.setPen(QColor("#FFD36E"))
        p.drawText(badge, Qt.AlignCenter, self.shot["file"][:-4])
        p.end()


class CapturePanel(GlassCard):
    def __init__(self, ctx):
        super().__init__("cp_title", "camera", "cp_sub", glow=True)
        self.ctx, self.api, self.store = ctx, ctx.api, ctx.store
        self.session, self.data, self.state = None, None, ""
        row = QHBoxLayout()
        row.setSpacing(8)
        self.start_btn = IconButton("camera", "cp_start", "go", size=16)
        self.start_btn.setMinimumHeight(42)
        self.start_btn.clicked.connect(self.start)
        row.addWidget(self.start_btn)
        self.done_btn = IconButton("verified", "cp_done", "primary", size=18)
        self.done_btn.setMinimumHeight(42)
        self.done_btn.clicked.connect(self.stop)
        self.done_btn.hide()
        row.addWidget(self.done_btn)
        self.rec = QLabel()
        self.rec.setTextFormat(Qt.RichText)
        row.addWidget(self.rec)
        row.addStretch(1)
        self.add(row)
        live = QHBoxLayout()
        self.seal = AnimatedSeal(30)
        self.seal.hide()
        live.addWidget(self.seal)
        self.live = label("", "h3", wrap=True)
        live.addWidget(self.live, 1)
        self.add(live)
        self.add(note("cp_how", "lightbulb"))
        self.grid_w = QWidget()
        self.grid = QGridLayout(self.grid_w)
        self.grid.setContentsMargins(0, 6, 0, 0)
        self.grid.setSpacing(10)
        self.add(self.grid_w)
        act = QHBoxLayout()
        act.setSpacing(8)
        self.send_btn = IconButton("send", None, "primary", size=15)
        self.send_btn.setMinimumHeight(42)
        self.send_btn.clicked.connect(self.send)
        act.addWidget(self.send_btn)
        self.discard_btn = IconButton("trash", "cp_discard", "stop", size=14)
        self.discard_btn.clicked.connect(self.discard)
        act.addWidget(self.discard_btn)
        act.addStretch(1)
        self.actions = QWidget()
        self.actions.setLayout(act)
        self.add(self.actions)
        self.actions.hide()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._blink = False

    # ---------------------------------------------------------------- data
    def load(self):
        self.poll()

    def poll(self):
        acc = self.store.account
        if acc: self.api.get(f"/api/capture/{acc}/status", self.got)

    def got(self, r):
        if not isinstance(r, dict): return
        st = r.get("status") or {}
        t = st.get("text", "")
        prev = self.state
        self.state = t
        busy = t in ("waiting", "starting", "capturing", "reading", "sending")
        if busy and not self.timer.isActive(): self.timer.start(1000)
        if not busy and self.timer.isActive(): self.timer.stop()
        capturing = t in ("waiting", "starting", "capturing")
        self.start_btn.setVisible(not capturing)
        self.start_btn.setEnabled(not busy)
        self.done_btn.setVisible(capturing)
        self._blink = not self._blink
        if t == "capturing":
            dot = f'<span style="color:{TOKENS["bad"]};font-size:15pt">{"●" if self._blink else "○"}</span>'
            fight = f'&nbsp;&nbsp;⚔️ <b style="color:{TOKENS["bad"]}">{tr("cp_in_battle")}</b>' if st.get("in_battle") else ""
            bat = f'&nbsp;&nbsp;⚔️ <b>{st.get("battles", 0)}</b> {tr("cp_battles")}' if st.get("battles") else ""
            self.rec.setText(f'{dot}&nbsp;<b>REC</b>&nbsp;&nbsp;<span style="color:{TOKENS["accent_hi"]};font-size:13pt;font-weight:800">{st.get("shots", 0)}</span> {tr("cp_shots")}{bat}{fight}')
        else:
            self.rec.setText("")
        n = st.get("shots", 0)
        text = {"waiting": tr("cp_st_waiting"), "starting": tr("cp_st_starting"), "capturing": tr("cp_st_capturing"),
                "reading": tr("cp_st_reading").format(n=n), "ready": tr("cp_st_ready").format(n=n),
                "sending": tr("cp_st_sending").format(i=st.get("sent", 0), n=st.get("total", 0) or "…"),
                "sent": tr("cp_st_sent").format(n=n), "send_failed": tr("cp_st_send_failed") + " " + str(st.get("error", "")),
                "failed": tr("cp_st_failed")}.get(t, "")
        self.live.setText(text)
        self.live.setStyleSheet(f"color: {TOKENS['bad'] if t in ('failed', 'send_failed') else (TOKENS['ok'] if t == 'sent' else TOKENS['text'])};")
        done_now = t in ("ready", "sent") and prev not in ("", t)
        self.seal.setVisible(t in ("ready", "sent"))
        self.seal.gold = t == "sent"
        if done_now: self.seal.play()
        elif t in ("ready", "sent") and prev == "": self.seal.finish()
        data = r.get("data")
        if t in ("ready", "sent", "send_failed") and data:
            if (self.session, len(self.data.get("shots", [])) if self.data else -1) != (r.get("session"), len(data.get("shots", []))):
                self.session, self.data = r.get("session"), data
                self.render()
            self.actions.setVisible(bool(data.get("shots")))
            self.send_btn.setText("  " + tr("cp_send").format(n=len(data.get("shots", []))) if not data.get("sent") else "  " + tr("cp_resend"))
        elif capturing:
            self._clear()
            self.actions.hide()

    def _clear(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def render(self):
        self._clear()
        shots = (self.data or {}).get("shots", [])
        cols = 4
        for i, sh in enumerate(shots):
            self.grid.addWidget(Thumb(self, self.session, sh), i // cols, i % cols)
        row = (len(shots) + cols - 1) // cols
        for j, b in enumerate((self.data or {}).get("battles", [])):
            box = Box(radius=14, border="rgba(240,85,90,0.45)")
            h = QHBoxLayout(box)
            h.setContentsMargins(14, 10, 14, 10)
            ic = QLabel()
            ic.setPixmap(icons.pixmap("swords", 22, TOKENS["bad"]))
            h.addWidget(ic)
            h.addWidget(label(tr("cp_battle_row").format(n=b["n"], taps=b.get("taps", 0), frames=b.get("frames", 0),
                                                        rec=b.get("recording") or "—"), wrap=True), 1)
            self.grid.addWidget(box, row + j, 0, 1, cols)

    # ---------------------------------------------------------------- actions
    def start(self):
        if self.state in ("ready",) and self.data and not self.data.get("sent") and self.data.get("shots"):
            if QMessageBox.question(self, "Clash Farmer", tr("cp_confirm_new")) != QMessageBox.Yes: return

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.ctx.banner(tr("cp_banner"), "rec", "camera")
                self.state = ""
                self.data = None
                self.timer.start(1000)
            else:
                self.ctx.toast(tr("dk_failed"), "bad")
        self.api.post(f"/api/capture/{self.store.account}/start", {}, done)

    def stop(self):
        self.done_btn.setEnabled(False)
        self.api.post(f"/api/capture/{self.store.account}/stop", {}, lambda r: (self.done_btn.setEnabled(True), self.poll()))

    def delete_one(self, file):
        self.api.post(f"/api/capture/{self.store.account}/delete", {"session": self.session, "file": file},
                      lambda r: (setattr(self, "data", None), self.poll()))

    def discard(self):
        if QMessageBox.question(self, "Clash Farmer", tr("cp_confirm_discard")) != QMessageBox.Yes: return
        self.api.post(f"/api/capture/{self.store.account}/delete", {"session": self.session},
                      lambda r: (setattr(self, "data", None), self._clear(), self.actions.hide(), self.live.setText(""), self.seal.hide()))

    def send(self):
        if self.store.dirty: self.store.save(silent=True)

        def done(r):
            if isinstance(r, dict) and r.get("ok"):
                self.timer.start(1000)
            else:
                err = (r or {}).get("error", "")
                self.ctx.toast(tr("ln_err_not_configured") if err == "not_configured" else tr("ln_sync_fail") + " " + str(err), "bad")
        QTimer.singleShot(500, lambda: self.api.post(f"/api/capture/{self.store.account}/send", {"session": self.session}, done))
