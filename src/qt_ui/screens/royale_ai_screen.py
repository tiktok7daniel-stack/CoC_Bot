"""
Live AI — the battle as the AI sees and thinks it, on the real game picture (its own screen, the user's request):

  picture   the game as it is now (twice a second), with every unit the eyes read (box, name, life bar: red theirs,
            blue ours), the moves the battle engine thought through (dots: green = better than waiting, red = worse,
            with their value), the AI model's own choices (white rings) and the move made: a gold arrow from the card
            in the hand to the tile it went on
  panel     the AI model: play now or wait (%), each card's chance; the decision and why; both elixirs; our hand,
            their hand and next card as the bot counts them; the last plays of both sides

Reads royale.live_view's files (~/.CoC_Bot/learn/royale_live_<account>.json / .jpg), 4 times a second.
"""
import json, time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS, ui_font
from ..widgets.controls import GlassCard, IconButton, label
from .base import Screen


def _nice(n):
    return " ".join(x.capitalize() for x in str(n or "").replace("-", "_").split("_") if x)[:16]


import os as _os
try:                                   # drawn by the graphics card (OpenGL) — a plain widget where there is no screen
    if _os.environ.get("QT_QPA_PLATFORM") == "offscreen": raise ImportError
    from PySide6.QtOpenGLWidgets import QOpenGLWidget as _Base
except Exception:
    _Base = QWidget


class AiPicture(_Base):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 560)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img, self.img_t, self.d = None, 0.0, {}
        self.live_t, self.seq, self.fps, self._n, self._n_t = 0.0, 0, 0.0, 0, time.monotonic()

    def set_frame(self, img):
        """A full-size picture straight from the bot's video (live_shm), up to 60 a second."""
        self.img, self.live_t = img, time.monotonic()
        self._n += 1
        if time.monotonic() - self._n_t >= 1.0:
            self.fps, self._n, self._n_t = self._n / (time.monotonic() - self._n_t), 0, time.monotonic()
        self.update()

    def set_data(self, d, img_path):
        self.d = d or {}
        ft = float(self.d.get("frame_t") or 0)
        if time.monotonic() - self.live_t > 0.5 and ft and ft != self.img_t:   # no live video: the small picture
            im = QImage(str(img_path))
            if not im.isNull(): self.img, self.img_t = im, ft
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(TOKENS["void"]))
        if self.img is None or self.d.get("phase") != "battle":
            p.setPen(QColor(TOKENS["text"])); p.setFont(ui_font(11))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, tr("ra_none"))
            return
        iw, ih = self.img.width(), self.img.height()
        sc = min(self.width() / iw, self.height() / ih)
        w, h = iw * sc, ih * sc
        ox, oy = (self.width() - w) / 2, (self.height() - h) / 2
        P = lambda x, y: QPointF(ox + x * w, oy + y * h)
        p.drawImage(QRectF(ox, oy, w, h), self.img)
        f = ui_font(8, QFont.Bold)
        p.setFont(f)
        fm = p.fontMetrics()
        # the engine's moves: green better than waiting, red worse
        for x, y, v, _c in self.d.get("cands_at") or []:
            col = QColor(61, 214, 140) if v > 0 else QColor(240, 85, 90)
            col.setAlpha(170)
            p.setPen(Qt.NoPen); p.setBrush(col)
            p.drawEllipse(P(x, y), 6, 6)
            p.setPen(QColor("#ffffff"))
            p.drawText(P(x, y) + QPointF(8, 4), f"{v:+.1f}")
        # the AI model's own tiles: white rings
        for c in ((self.d.get("model") or {}).get("tiles") or []):
            p.setPen(QPen(QColor(255, 255, 255, 200), 2)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(P(*c["at"]), 9, 9)
        # what the eyes see
        for b in self.d.get("boxes") or []:
            x0, y0, x1, y1 = b["b"]
            col = QColor("#3fa9ff") if b.get("m") else QColor("#ff4d4d")
            r = QRectF(P(x0, y0), P(x1, y1))
            p.setPen(QPen(col, 2)); p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            name = _nice(b.get("n"))
            lab = QRectF(r.left(), r.top() - 14, max(fm.horizontalAdvance(name) + 6, r.width()), 14)
            p.fillRect(lab, col)
            p.setPen(QColor("#ffffff"))
            p.drawText(lab, Qt.AlignCenter, name)
            life = float(b.get("l", 1.0))
            if not b.get("m") and life < 0.999:
                bar = QRectF(r.left(), r.bottom() + 1, r.width(), 3)
                p.fillRect(bar, QColor(0, 0, 0, 160))
                p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, life), 3), QColor("#ffd24d"))
        if time.monotonic() - self.live_t < 0.5:
            p.setPen(QColor("#4ade80"))
            tag = f"● LIVE · {self.fps:.0f} fps · {iw}x{ih}"
            r = QRectF(ox + 6, oy + h * 0.78, fm.horizontalAdvance(tag) + 10, 16)
            p.fillRect(r, QColor(0, 0, 0, 170))
            p.drawText(r, Qt.AlignCenter, tag)
        # the move: a gold arrow from the card in the hand to its tile
        t, c0 = self.d.get("target"), self.d.get("card_at")
        if t:
            gold = QColor(TOKENS["gold"])
            p.setPen(QPen(gold, 3)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(P(*t), 13, 13)
            if c0:
                a, bpt = P(*c0), P(*t)
                p.drawLine(a, bpt)
                import math
                ang = math.atan2(bpt.y() - a.y(), bpt.x() - a.x())
                head = QPolygonF([bpt, bpt - QPointF(12 * math.cos(ang - 0.4), 12 * math.sin(ang - 0.4)),
                                  bpt - QPointF(12 * math.cos(ang + 0.4), 12 * math.sin(ang + 0.4))])
                p.setBrush(gold); p.drawPolygon(head)


class RoyaleAiScreen(Screen):
    key, title_key, icon_name = "royale_ai", "ra_title", "bolt"

    def __init__(self, ctx):
        super().__init__(ctx)
        top = QHBoxLayout()
        pop = IconButton("expand", "rl_popout", kind="go", size=14)
        pop.clicked.connect(self.pop_out)
        top.addWidget(pop)
        top.addStretch(1)
        self.root.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.pic = AiPicture()
        card = GlassCard("ra_picture", "eye", "ra_picture_sub")
        card.add(self.pic, 1)
        row.addWidget(card, 3)
        self.panel = label("", wrap=True)
        self.panel.setTextFormat(Qt.RichText)
        self.panel.setAlignment(Qt.AlignTop)
        side = GlassCard("ra_mind", "bolt", glow=True)
        side.add(self.panel, 1)
        side.setMinimumWidth(330)
        row.addWidget(side, 2)
        hold = QWidget(); hold.setLayout(row)
        self.root.addWidget(hold, 1)
        self._mtime = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(100)                        # what it sees / thinks: 10 times a second
        self.ftimer = QTimer(self)
        self.ftimer.setTimerType(Qt.PreciseTimer)
        self.ftimer.timeout.connect(self.frame_tick)
        self.ftimer.start(16)                        # the picture: up to 60 a second, straight from memory
        self._seq, self._touch_t = 0, 0.0

    def frame_tick(self):
        popped = getattr(self, "_pop", None) is not None and self._pop.isVisible()
        if not self.isVisible() and not popped: return
        try:
            import live_shm
        except Exception:
            return
        if time.monotonic() - self._touch_t > 1.0:   # tell the bot someone is watching (it only sends then)
            self._touch_t = time.monotonic()
            live_shm.touch()
        r = live_shm.read(self._seq)
        if not r: return
        self._seq, w, h, data = r
        img = QImage(data, w, h, 3 * w, QImage.Format_RGB888).copy()
        if self.isVisible(): self.pic.set_frame(img)
        if popped: self._pop._pic.set_frame(img)
        on_lang(lambda: self.refresh(force=True))

    def _path(self):
        acc = self.store.account or "main"
        return Path.home() / ".CoC_Bot" / "learn" / \
            f"royale_live_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"

    def pop_out(self):
        """The live AI in its own window, kept on top beside LDPlayer."""
        if getattr(self, "_pop", None) is not None and self._pop.isVisible():
            self._pop.raise_(); self._pop.activateWindow(); return
        w = QWidget(None, Qt.Window | Qt.WindowStaysOnTopHint)
        w.setWindowTitle(tr("ra_title"))
        w.setStyleSheet(f"background: {TOKENS['void']}; color: {TOKENS['text']};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        pic = AiPicture()
        info = QLabel(); info.setWordWrap(True); info.setTextFormat(Qt.RichText); info.setAlignment(Qt.AlignTop)
        info.setFont(ui_font(9.5)); info.setMinimumWidth(260)
        lay.addWidget(pic, 3); lay.addWidget(info, 2)
        w.resize(820, 860)
        w._pic, w._info = pic, info
        self._pop = w
        w.show()
        self.refresh(force=True)

    def on_show(self):
        self.refresh(force=True)

    def refresh(self, force=False):
        popped = getattr(self, "_pop", None) is not None and self._pop.isVisible()
        if not self.isVisible() and not popped and not force: return
        p = self._path()
        try: mt = p.stat().st_mtime
        except OSError:
            self.pic.set_data({"phase": "none"}, p.with_suffix(".jpg")); self.panel.setText(tr("ra_none")); return
        if mt == self._mtime and not force: return
        self._mtime = mt
        try: d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError): return
        if d.get("phase") == "battle" and time.time() - d.get("t", 0) > 8: d["phase"] = "stale"
        txt = self.text(d)
        self.pic.set_data(d, p.with_suffix(".jpg"))
        self.panel.setText(txt)
        if popped:
            self._pop._pic.set_data(d, p.with_suffix(".jpg"))
            self._pop._info.setText(txt)

    def text(self, d):
        if d.get("phase") != "battle": return tr("ra_none")
        g, r, gold = "#4ade80", "#f87171", TOKENS["gold"]
        out = []
        t = d.get("time_s", 0)
        out.append(f"<b>{int(t // 60)}:{int(t % 60):02d}</b>" + (" · ⚡x2" if d.get("double") else "") +
                   f" · {tr('rl_elixir')} <b>{d.get('elixir')}</b> · {tr('rl_their_elixir')} <b>{d.get('their_elixir')}</b>")
        m = d.get("model") or {}
        if m:
            pl = float(m.get("play", 0))
            out.append(f"<br><b style='color:{gold}'>{tr('ra_model')}</b><br>"
                       f"{tr('ra_play_now')}: <b style='color:{g if pl >= 0.5 else r}'>{int(pl * 100)}%</b>"
                       + (f" · {tr('ra_alone')}" if m.get("ai_only") else ""))
            for n, v in (m.get("cards") or {}).items():
                bar = "█" * max(1, int(v * 20))
                out.append(f"<span style='font-family:monospace'>{_nice(n):<14}</span> "
                           f"<span style='color:{gold}'>{bar}</span> {int(v * 100)}%")
        dec = d.get("decision")
        out.append(f"<br><b style='color:{gold}'>{tr('ra_decision')}</b>")
        out.append(f"▶ <b>{_nice(dec['card'])}</b> → {tuple(dec['tile'])}<br><small>{dec.get('why', '')}</small>"
                   if dec else tr("rl_waiting"))
        th = d.get("think") or {}
        if th.get("tried"):
            out.append(f"<small>{tr('rl_thought')}: {th.get('tried')} · {th.get('ms')} ms</small>")
        hand = d.get("hand") or []
        if hand:
            out.append(f"<br><b>{tr('rl_hand')}</b><br>" + " · ".join(
                ("● " if h.get("ready") else "○ ") + _nice(h.get("card")) + (" ⚡" if h.get("evo") else "") +
                (" 👑" if h.get("hero") else "") for h in hand) + (f"<br>{tr('rl_next')}: {_nice(d.get('next'))}"
                                                                    if d.get("next") else ""))
        if d.get("their_hand"):
            out.append(f"<br><b>{tr('rl_their_hand')}</b>: " + ", ".join(_nice(c) for c in d["their_hand"]))
        ev = (d.get("events") or [])[-6:]
        if ev:
            out.append(f"<br><b>{tr('rl_events')}</b>")
            for e in reversed(ev):
                col = "#3fa9ff" if e.get("who") == "us" else r
                out.append(f"<span style='color:{col}'>{tr('rl_us') if e.get('who') == 'us' else tr('rl_them_short')}</span>"
                           f" {_nice(e.get('card'))} {tuple(e['tile']) if e.get('tile') else ''}")
        return "<br>".join(out)
