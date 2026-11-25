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

    def _badge(self, p, ox, oy, w, h, iw, ih):
        if time.monotonic() - self.live_t >= 0.5: return
        p.setFont(ui_font(8, QFont.Bold))
        tag = f"● LIVE · {getattr(self, 'stream_fps', 0) or self.fps:.0f} fps · {iw}x{ih}"
        r = QRectF(ox + 6, oy + h * 0.78, p.fontMetrics().horizontalAdvance(tag) + 10, 16)
        p.fillRect(r, QColor(0, 0, 0, 170))
        p.setPen(QColor("#4ade80"))
        p.drawText(r, Qt.AlignCenter, tag)

    def set_frame(self, img, ts=None):
        """A full-size picture straight from the bot's video; ts = the wall-clock time it arrived (6.9.17: the boxes
        are placed for THAT moment, so they sit on the units in the picture)."""
        self.img, self.live_t = img, time.monotonic()
        self.frame_ts = ts
        self._n += 1
        if time.monotonic() - self._n_t >= 1.0:
            self.fps, self._n, self._n_t = self._n / (time.monotonic() - self._n_t), 0, time.monotonic()
        self.update()

    def _track(self, d):
        """Smooth tracking (5.95): each box is matched with the same unit in the last update (same name, nearest)
        and given a speed; between the bot's updates (10 a second) it keeps moving with its unit on every picture
        (up to 240 a second) instead of jumping."""
        now = time.time()
        old = getattr(self, "_boxes", [])
        new = []
        for b in d.get("boxes") or []:
            x0, y0, x1, y1 = b["b"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            best, bd = None, 0.06
            for o in old:
                if o["n"] != b.get("n") or o["m"] != b.get("m"): continue
                dd = abs(o["cx"] - cx) + abs(o["cy"] - cy)
                if dd < bd: best, bd = o, dd
            vx = vy = 0.0
            if best is not None and now - best["t"] > 0.02:
                dt = now - best["t"]
                vx = 0.6 * (cx - best["cx"]) / dt + 0.4 * best["vx"]       # smoothed speed (screen fractions / s)
                vy = 0.6 * (cy - best["cy"]) / dt + 0.4 * best["vy"]
                if abs(vx) > 0.6 or abs(vy) > 0.6: vx = vy = 0.0             # a jump, not a walk
            new.append({"n": b.get("n"), "m": b.get("m"), "l": b.get("l", 1.0), "cx": cx, "cy": cy,
                        "w": x1 - x0, "h": y1 - y0, "vx": vx, "vy": vy, "t": now})
        self._boxes = new

    def set_data(self, d, img_path):
        if (d or {}).get("t") != self.d.get("t"): self._track(d or {})
        self.d = d or {}
        ft = float(self.d.get("frame_t") or 0)
        if time.monotonic() - self.live_t > 0.5 and ft and ft != self.img_t:   # no live video: the small picture
            im = QImage(str(img_path))
            if not im.isNull(): self.img, self.img_t = im, ft
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)  # the sharpest scaling (done by the graphics card)
        p.fillRect(self.rect(), QColor(TOKENS["void"]))
        if self.img is None:
            p.setPen(QColor(TOKENS["text"])); p.setFont(ui_font(11))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, tr("ra_none"))
            return
        iw, ih = self.img.width(), self.img.height()
        sc = min(self.width() / iw, self.height() / ih)
        w, h = iw * sc, ih * sc
        ox, oy = (self.width() - w) / 2, (self.height() - h) / 2
        P = lambda x, y: QPointF(ox + x * w, oy + y * h)
        p.drawImage(QRectF(ox, oy, w, h), self.img)
        battle = self.d.get("phase") == "battle" and time.time() - float(self.d.get("t", 0)) < 8
        if not battle:                                   # the game as it is (lobby, menus): the picture alone
            self._badge(p, ox, oy, w, h, iw, ih)
            return
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
        now = time.time()
        fts = getattr(self, "frame_ts", None)
        if fts and now - fts < 1.0: now = fts            # 6.9.17: the moment of the picture shown (synced)
        tr = getattr(self, "tracker", None)
        if tr is not None and tr.active():               # every unit placed for the picture's own moment + preserve HP
            raw_boxes = self.d.get("boxes") or []
            shown = tr.visible_rich(now) if hasattr(tr, "visible_rich") else [
                {"n": n, "m": m, "l": 1.0, "cx": x, "cy": y, "w": bw, "h": bh, "vx": 0.0, "vy": 0.0, "t": now}
                for n, m, x, y, bw, bh in tr.visible(now)
            ]
            for b in shown:
                best_l, best_d = 1.0, 0.07
                for rb in raw_boxes:
                    if bool(rb.get("m")) != bool(b.get("m")): continue
                    rx0, ry0, rx1, ry1 = rb["b"]
                    dd = abs((rx0 + rx1) / 2 - b["cx"]) + abs((ry0 + ry1) / 2 - b["cy"])
                    if rb.get("n") == b.get("n") and dd < best_d:
                        best_d, best_l = dd, float(rb.get("l", 1.0))
                b["l"] = best_l
        else:
            shown = getattr(self, "_boxes", [])
        for b in shown:
            k = min(0.25, now - b["t"])                  # where the unit is now (its speed since the update)
            cx, cy = b["cx"] + b["vx"] * k, b["cy"] + b["vy"] * k
            x0, y0, x1, y1 = cx - b["w"] / 2, cy - b["h"] / 2, cx + b["w"] / 2, cy + b["h"] / 2
            col = QColor("#3fa9ff") if b.get("m") else QColor("#ff4d4d")
            r = QRectF(P(x0, y0), P(x1, y1))
            fill = QColor(col); fill.setAlpha(45)
            p.setPen(QPen(col, 3)); p.setBrush(fill)  # 6.9.24: visible fill + thicker border
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
        # 6.6: every tracked unit — its id, an arrow for where it walks (1 s ahead), and the spell's predicted impact
        import math
        for t in self.d.get("tracks") or []:
            col = QColor("#3fa9ff") if t.get("m") else QColor("#ff4d4d")
            a = P(t["x"], t["y"])
            p.setPen(QColor("#ffffff"))
            p.drawText(a + QPointF(-6, 14), f"#{t['id']}" + ("🔒" if t.get("lock") else ""))
            vx, vy = float(t.get("vx") or 0), float(t.get("vy") or 0)
            if abs(vx) + abs(vy) > 0.004:
                bpt = P(t["x"] + vx, t["y"] + vy)
                p.setPen(QPen(col, 2)); p.drawLine(a, bpt)
                ang = math.atan2(bpt.y() - a.y(), bpt.x() - a.x())
                p.setBrush(col)
                p.drawPolygon(QPolygonF([bpt, bpt - QPointF(7 * math.cos(ang - 0.5), 7 * math.sin(ang - 0.5)),
                                         bpt - QPointF(7 * math.cos(ang + 0.5), 7 * math.sin(ang + 0.5))]))
            if t.get("eta") is not None and not t.get("m") and t["eta"] < 6:
                p.setPen(QColor("#ffd24d")); p.drawText(a + QPointF(10, 2), f"{t['eta']:.1f}s")
        ld = self.d.get("lead")
        if ld:
            a, bpt = P(*ld["from"]), P(*ld["to"])
            pen = QPen(QColor("#ffd24d"), 2, Qt.DashLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawLine(a, bpt)
            p.drawEllipse(bpt, 10, 10)
            p.drawLine(bpt + QPointF(-14, 0), bpt + QPointF(14, 0)); p.drawLine(bpt + QPointF(0, -14), bpt + QPointF(0, 14))
        self._badge(p, ox, oy, w, h, iw, ih)
        # the move: a gold arrow from the card in the hand to its tile
        t, c0 = self.d.get("target"), self.d.get("card_at")
        if t:
            gold = QColor(TOKENS["gold"])
            p.setPen(QPen(gold, 3)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(P(*t), 13, 13)
            dec = self.d.get("decision") or {}
            if dec.get("card"):                          # 6.8: what it played, where, and why in one line
                import re
                m = re.search(r"([+-]\d+(?:\.\d+)?) (?:elixir )?vs waiting", dec.get("why", ""))
                txt = f"AI PLAYED: {_nice(dec['card']).upper()} {list(dec.get('tile') or [])}" + (f"  {m.group(1)}" if m else "")
                fb = ui_font(9, QFont.Bold); p.setFont(fb)
                tw = p.fontMetrics().horizontalAdvance(txt) + 16
                at = P(*t)
                box = QRectF(max(ox + 4, min(ox + w - tw - 4, at.x() - tw / 2)), at.y() - 44, tw, 24)
                p.setPen(QPen(QColor("#3fe0b0"), 2)); p.setBrush(QColor(10, 20, 30, 215))
                p.drawRoundedRect(box, 5, 5)
                p.setPen(QColor("#ffffff")); p.drawText(box, Qt.AlignCenter, txt)
                p.setFont(f)
                p.setPen(QPen(gold, 3)); p.setBrush(Qt.NoBrush)
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
        self.timer.start(40)                         # every look of the bot (its tracker data)
        from ..live_video import LiveVideo
        from ..live_tracker import LiveTracker
        self.video = LiveVideo()                    # the app's own copy of the game screen (5.91)
        self.tracker = LiveTracker(self.video)      # its own eyes + tracker on the pictures it shows (5.96)
        self.pic.tracker = self.tracker
        self._txt = ""
        self.ftimer = QTimer(self)
        self.ftimer.setTimerType(Qt.PreciseTimer)
        self.ftimer.timeout.connect(self.frame_tick)
        self.ftimer.start(4)                         # up to 240 pictures a second
        self._seq = 0

    def frame_tick(self):
        popped = getattr(self, "_pop", None) is not None and self._pop.isVisible()
        if not self.isVisible() and not popped:
            self.video.stop(); self.tracker.stop()
            return
        self.video.start(); self.tracker.start()
        ts = None
        delay = self.tracker.sync_delay()
        if delay and self.video.buf:
            # 6.9.17: the picture of the moment the bot's eyes looked at (the screen runs `delay` behind, the boxes sit
            # on their units instead of chasing them)
            r = self.video.take_at(time.time() - delay, getattr(self, "_skey", None))
            if not r: return
            self._skey, img, ts = r
        else:
            r = self.video.take(self._seq)
            if not r: return
            self._seq, img = r
        self.pic.stream_fps = self.video.fps
        if self.isVisible(): self.pic.set_frame(img, ts)
        if popped:
            self._pop._pic.stream_fps = self.video.fps
            self._pop._pic.set_frame(img, ts)

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
        w.setStyleSheet(f"background: {TOKENS['void']};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        pic = AiPicture()                            # only the game, live (the user's wish: no map, no panel)
        pic.tracker = self.tracker
        lay.addWidget(pic, 1)
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen().availableGeometry()
        hh = int(scr.height() * 0.92)
        w.resize(int(hh * 9 / 16), hh)                # the whole game, tall, no black bars

        def _resized(e, w=w):                        # keeps the game's shape when resized
            if w.isFullScreen() or getattr(w, "_fixing", False): return
            want = int(w.width() * 16 / 9)
            if abs(want - w.height()) > 2:
                w._fixing = True; w.resize(w.width(), want); w._fixing = False
        w.resizeEvent = _resized

        def _dbl(e, w=w):                            # double-click: full screen / back
            w.showNormal() if w.isFullScreen() else w.showFullScreen()
        pic.mouseDoubleClickEvent = _dbl
        w._pic, w._info = pic, None
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
        self.tracker.feed(d.get("dets"), d.get("seen_t"))   # every unit the bot's eyes found, timed (5.97)
        self.pic.set_data(d, p.with_suffix(".jpg"))
        if self.isVisible() and time.monotonic() - getattr(self, "_txt_t", 0) > 0.25:
            self._txt_t = time.monotonic()
            txt = self.text(d)
            if txt != self._txt:                      # re-laying out the text held the picture up a moment
                self._txt = txt
                self.panel.setText(txt)
        if popped:
            self._pop._pic.set_data(d, p.with_suffix(".jpg"))

    def text(self, d):
        if d.get("phase") != "battle": return tr("ra_none")
        g, r, gold = TOKENS["ok"], TOKENS["bad"], TOKENS["gold"]
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
