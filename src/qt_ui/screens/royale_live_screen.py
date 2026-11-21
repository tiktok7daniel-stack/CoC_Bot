"""
Battle view: the battle as the bot sees and thinks it, live (the idea of crforge's debug visualizer, on the real game).

  arena   18 x 32 tiles, ours at the bottom: the river and bridges, the towers with their life, every unit the eyes
          read (blue ours, red theirs, a ring for life), spells landing, the moves the battle engine thought through
          as a heat map (green = better than waiting, red = worse), and the move chosen (gold outline)
  panel   time / double elixir, both elixirs, our hand (evolved / hero marked) and the next card, their hand and next
          card as the bot counts them, their deck seen and guessed, what the bot is doing and why, the engine and the
          trained AI's state, the last plays of both sides

Reads ~/.CoC_Bot/learn/royale_live_<account>.json (royale.live_view), 4 times a second.
"""
import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS, ui_font
from ..widgets.controls import GlassCard, label
from .base import Screen

W, H = 18, 32


def _short(name):
    n = str(name or "").replace("-", "_")
    parts = [p for p in n.split("_") if p and p != "the"]
    return " ".join(p[:5].capitalize() for p in parts[:2])


class Arena(QWidget):
    def __init__(self):
        super().__init__()
        self.data = {}
        self.setMinimumSize(360, 600)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, d):
        self.data = d or {}
        self.update()

    # tile (x, y), ours at the bottom -> widget point
    def _geo(self):
        r = self.rect().adjusted(8, 8, -8, -8)
        s = min(r.width() / W, r.height() / H)
        ox = r.x() + (r.width() - s * W) / 2
        oy = r.y() + (r.height() - s * H) / 2
        return s, ox, oy

    def _pt(self, x, y):
        s, ox, oy = self._geo()
        return QPointF(ox + x * s, oy + (H - y) * s)

    def _tile(self, tx, ty):
        s, ox, oy = self._geo()
        return QRectF(ox + tx * s, oy + (H - 1 - ty) * s, s, s)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s, ox, oy = self._geo()
        d = self.data
        # ground, river, bridges
        p.fillRect(QRectF(ox, oy, s * W, s * H), QColor("#2f5d34"))
        for ty in range(H):
            for tx in range(W):
                if (tx + ty) % 2 == 0: p.fillRect(self._tile(tx, ty), QColor(255, 255, 255, 10))
        for ty in (15, 16):
            for tx in range(W):
                bridge = tx in (2, 3, 14, 15)
                p.fillRect(self._tile(tx, ty), QColor("#8a6a3d") if bridge else QColor("#2b6fa8"))
        # the engine's heat map
        think = d.get("think") or {}
        cands = think.get("cands") or []
        if cands:
            top = max(abs(c["v"]) for c in cands) or 1.0
            for c in cands:
                v = c["v"]
                a = int(40 + 140 * min(1.0, abs(v) / top))
                col = QColor(60, 220, 120, a) if v > 0 else QColor(230, 70, 70, a)
                p.fillRect(self._tile(*c["tile"]), col)
        # towers
        tw = d.get("towers") or {}
        f_small = ui_font(max(6.5, s * 0.32))
        for key, (x, y), mine in (("our_left", (3.5, 5.0), True), ("our_right", (14.5, 5.0), True),
                                  ("their_left", (3.5, 26.0), False), ("their_right", (14.5, 26.0), False)):
            self._tower(p, x, y, 3.0, mine, tw.get(key), s)
        self._tower(p, 9.0, 1.8, 4.0, True, None, s)
        self._tower(p, 9.0, 29.2, 4.0, False, None, s)
        # spells landing
        for dz in d.get("danger") or []:
            p.setPen(QPen(QColor(255, 120, 40, 200), 2, Qt.DashLine))
            p.setBrush(QColor(255, 120, 40, 40))
            c = self._pt(dz["x"] + 0.5, dz["y"] + 0.5)
            p.drawEllipse(c, dz["r"] * s, dz["r"] * s)
        # units
        p.setFont(f_small)
        for u in d.get("allies") or []: self._unit(p, u, True, s, 1.0)
        for u in d.get("enemies") or []: self._unit(p, u, False, s, u.get("life", 1.0))
        # the move chosen
        dec = d.get("decision")
        if dec and dec.get("tile"):
            r = self._tile(*dec["tile"]).adjusted(-2, -2, 2, 2)
            p.setPen(QPen(QColor(TOKENS["gold"]), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setFont(ui_font(max(7.0, s * 0.38), QFont.Bold))
            p.setPen(QColor(TOKENS["gold"]))
            p.drawText(r.adjusted(-s * 2, -s * 1.1, s * 2, 0), Qt.AlignHCenter | Qt.AlignTop, _short(dec.get("card")))
        if d.get("phase") != "battle":
            p.fillRect(QRectF(ox, oy, s * W, s * H), QColor(0, 0, 0, 120))
            p.setPen(QColor(TOKENS["text"]))
            p.setFont(ui_font(13, QFont.Bold))
            p.drawText(QRectF(ox, oy, s * W, s * H), Qt.AlignCenter | Qt.TextWordWrap,
                       tr("rl_phase_" + str(d.get("phase") or "none")))
        p.end()

    def _tower(self, p, x, y, size, mine, life, s):
        c = self._pt(x, y + 0.5)
        r = QRectF(c.x() - size * s / 2, c.y() - size * s / 2, size * s, size * s)
        dead = life is not None and life <= 0.01
        p.setPen(QPen(QColor("#1b2a4a" if mine else "#4a1b1b"), 2))
        p.setBrush(QColor(40, 40, 40) if dead else QColor("#3d6fd6" if mine else "#d64a4a"))
        p.drawRoundedRect(r, 4, 4)
        if life is not None and not dead:
            bar = QRectF(r.x(), r.bottom() + 2, r.width(), max(3.0, s * 0.18))
            p.fillRect(bar, QColor(0, 0, 0, 160))
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * max(0.0, min(1.0, life)), bar.height()),
                       QColor("#4aa3ff" if mine else "#ff5a5a"))

    def _unit(self, p, u, mine, s, life):
        c = self._pt(u["x"] + 0.5, u["y"] + 0.5)
        rad = s * 0.42
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#4aa3ff" if mine else "#ff5a5a"))
        p.drawEllipse(c, rad, rad)
        if life < 0.999:
            p.setPen(QPen(QColor(255, 255, 255, 230), 2))
            p.setBrush(Qt.NoBrush)
            p.drawArc(QRectF(c.x() - rad - 2, c.y() - rad - 2, 2 * rad + 4, 2 * rad + 4), 90 * 16,
                      int(-360 * 16 * max(0.0, min(1.0, life))))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(c.x() - s * 2, c.y() + rad, s * 4, s * 0.8), Qt.AlignHCenter | Qt.AlignTop, _short(u["u"]))


class RoyaleLiveScreen(Screen):
    key, title_key, icon_name = "royale_live", "royale_live_title", "eye"

    def __init__(self, ctx):
        super().__init__(ctx)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.arena = Arena()
        left = GlassCard("rl_arena", "eye", "rl_arena_sub")
        left.add(self.arena)
        row.addWidget(left, 3)
        side = QVBoxLayout()
        side.setSpacing(10)
        self.c_state = GlassCard("rl_state", "clock")
        self.l_state = label("", wrap=True)
        self.c_state.add(self.l_state)
        self.c_think = GlassCard("rl_think", "bolt", glow=True)
        self.l_think = label("", wrap=True)
        self.l_think.setTextFormat(Qt.RichText)
        self.c_think.add(self.l_think)
        self.c_them = GlassCard("rl_them", "swords")
        self.l_them = label("", wrap=True)
        self.c_them.add(self.l_them)
        self.c_ev = GlassCard("rl_events", "scroll")
        self.l_ev = label("", wrap=True)
        self.l_ev.setTextFormat(Qt.RichText)
        self.c_ev.add(self.l_ev)
        for c in (self.c_state, self.c_think, self.c_them, self.c_ev): side.addWidget(c)
        side.addStretch(1)
        sw = QWidget()
        sw.setLayout(side)
        sw.setMinimumWidth(320)
        row.addWidget(sw, 2)
        holder = QWidget()
        holder.setLayout(row)
        self.root.addWidget(holder, 1)
        self._mtime = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)
        on_lang(lambda: self.refresh(force=True))

    def _path(self):
        acc = self.store.account or "main"
        return Path.home() / ".CoC_Bot" / "learn" / \
            f"royale_live_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"

    def on_show(self):
        self.refresh(force=True)

    def refresh(self, force=False):
        if not self.isVisible() and not force: return
        p = self._path()
        try:
            mt = p.stat().st_mtime
        except OSError:
            self.arena.set_data({"phase": "none"})
            self.l_state.setText(tr("rl_no_data"))
            return
        if mt == self._mtime and not force:
            return
        self._mtime = mt
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        import time as _t
        if d.get("phase") == "battle" and _t.time() - d.get("t", 0) > 8: d["phase"] = "stale"
        self.arena.set_data(d)
        self.show_panel(d)

    def show_panel(self, d):
        if d.get("phase") != "battle":
            self.l_state.setText(tr("rl_phase_" + str(d.get("phase") or "none")) + (f"\n{d.get('note')}" if d.get("note") else ""))
            return
        t = d.get("time_s", 0)
        hand = d.get("hand") or []

        def card_txt(h):
            tags = (" ⚡" if h.get("evo") else "") + (" 👑" if h.get("hero") else "")
            return ("● " if h.get("ready") else "○ ") + str(h.get("card")) + tags
        self.l_state.setText(
            f"{tr('rl_time')}: {int(t // 60)}:{int(t % 60):02d}" + (f"  ·  {tr('rl_double')}" if d.get("double") else "") + "\n" +
            f"{tr('rl_elixir')}: {d.get('elixir')}  ·  {tr('rl_their_elixir')}: ~{d.get('their_elixir')}\n" +
            f"{tr('rl_hand')}: " + "   ".join(card_txt(h) for h in hand) + f"\n{tr('rl_next')}: {d.get('next')}")
        dec = d.get("decision")
        th = d.get("think") or {}
        eng = d.get("engine") or {}
        lines = []
        if dec:
            lines.append(f"<b style='color:{TOKENS['gold']}'>▶ {dec['card']} → {tuple(dec['tile'])}</b><br>{dec.get('why', '')}")
        else:
            lines.append(f"<b>{tr('rl_waiting')}</b>")
        if th.get("tried"):
            best = (th.get("cands") or [{}])[0]
            lines.append(f"{tr('rl_thought')}: {th['tried']} · {th.get('ms', 0)} ms" +
                         (f" · {tr('rl_best')}: {best.get('card')} {tuple(best.get('tile', []))} {best.get('v', 0):+.1f}" if best else ""))
        if th.get("ai"): lines.append(th["ai"])
        lines.append((tr("rl_engine_on") if eng.get("on") else tr("rl_engine_off") + (f" ({eng.get('why')})" if eng.get("why") else "")) +
                     (" · " + tr("rl_ai_on") if eng.get("ai") else ""))
        self.l_think.setText("<br>".join(lines))
        them = []
        if d.get("arch"): them.append(f"{tr('rl_arch')}: {d['arch']}")
        if d.get("their_hand"): them.append(f"{tr('rl_their_hand')}: " + ", ".join(d["their_hand"]))
        if d.get("their_next"): them.append(f"{tr('rl_their_next')}: {d['their_next']}")
        if d.get("their_seen"): them.append(f"{tr('rl_seen')}: " + ", ".join(d["their_seen"]))
        if d.get("their_guess"): them.append(f"{tr('rl_guess')}: " + ", ".join(d["their_guess"]))
        self.l_them.setText("\n".join(them) or tr("rl_them_none"))
        ev = []
        for e in reversed(d.get("events") or []):
            col = "#4aa3ff" if e.get("who") == "us" else "#ff5a5a"
            who = tr("rl_us") if e.get("who") == "us" else tr("rl_them_short")
            ev.append(f"<span style='color:{col}'>{who}</span> {e.get('card')} {tuple(e['tile']) if e.get('tile') else ''}")
        self.l_ev.setText("<br>".join(ev[:12]) or tr("rl_no_events"))
