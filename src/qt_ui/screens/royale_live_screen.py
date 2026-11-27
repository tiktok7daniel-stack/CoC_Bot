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
from PySide6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..i18n import on_lang, tr
from ..theme import TOKENS, ui_font
from ..widgets.controls import GlassCard, label
from ..widgets import StatusPill, AnimatedToggle, MetricTile, ConsoleLog, FlowLayout
from .. import icons
from .base import Screen
from ..store import Store

W, H = 18, 32


def decision_projection(decision, think):
    best = think.get("best") or {}
    if not decision or (best.get("card"), best.get("tile")) != (decision.get("card"), decision.get("tile")):
        return ""
    row = best.get("comparison")
    if not row:
        return ""
    return (f"{tr('rl_rollout')} · {tr('rl_saved_hp')} {row['our_hp_saved']:+.0f} · "
            f"{tr('rl_extra_damage')} {row['extra_enemy_damage']:+.0f} · "
            f"{tr('rl_spent_elixir')} {row['elixir_spent']:g} · {tr('rl_ally_value')} {row['extra_ally_value']:+.1f}")


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
        # esports tactical arena turf, river, bridges & heatmap visibility
        p.fillRect(QRectF(ox, oy, s * W, s * H), QColor("#1E3D26"))
        for ty in range(H):
            for tx in range(W):
                if (tx + ty) % 2 == 0: p.fillRect(self._tile(tx, ty), QColor(255, 255, 255, 11))
        for ty in (15, 16):
            for tx in range(W):
                bridge = tx in (2, 3, 14, 15)
                p.fillRect(self._tile(tx, ty), QColor("#9A7444") if bridge else QColor("#1F5E94"))
        p.setPen(QPen(QColor(TOKENS["border_solid"]), 1.2))
        p.drawRect(QRectF(ox, oy, s * W, s * H))
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
            p.setPen(QPen(QColor(TOKENS["crimson"]), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setFont(ui_font(max(7.0, s * 0.38), QFont.Bold))
            p.setPen(QColor(TOKENS["crimson"]))
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


class Camera(QWidget):
    """The bot's eyes: the real game picture (royale.live_view saves it twice a second) with a box, name and life bar
    on every unit the eyes read — red theirs, blue ours — and a gold circle where the bot just played."""
    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 340)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img, self.img_t, self.d = None, 0.0, {}

    def set_data(self, d, img_path):
        self.d = d or {}
        ft = float(self.d.get("frame_t") or 0)
        if self.d.get("phase") != "battle" or not ft:
            self.img, self.frame_boxes = None, []
            self._snapshot_key = None
        elif (img_path, ft) != getattr(self, "_snapshot_key", None):
            snapshot = self.d.get("snapshot")
            slot = (snapshot or {}).get("slot")
            path = img_path.with_suffix(f".{slot}.jpg") if slot in (0, 1) else img_path
            im = QImage(str(path))
            if not im.isNull():
                self.img, self.img_t = im, ft
                self._snapshot_key = (img_path, ft)
                self.frame_boxes = (snapshot or {}).get("boxes", [])
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(TOKENS["void"]))
        if self.img is None or self.d.get("phase") != "battle":
            p.setPen(QColor(TOKENS["text"]))
            p.setFont(ui_font(10))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, tr("rl_camera_none"))
            return
        iw, ih = self.img.width(), self.img.height()
        sc = min(self.width() / iw, self.height() / ih)
        w, h = iw * sc, ih * sc
        ox, oy = (self.width() - w) / 2, (self.height() - h) / 2
        p.drawImage(QRectF(ox, oy, w, h), self.img)
        p.setFont(ui_font(7.5, QFont.Bold))
        for b in getattr(self, "frame_boxes", []):
            x0, y0, x1, y1 = b["b"]
            col = QColor("#3fa9ff") if b.get("m") else QColor("#ff4d4d")
            r = QRectF(ox + x0 * w, oy + y0 * h, (x1 - x0) * w, (y1 - y0) * h)
            p.setPen(QPen(col, 2)); p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            name = " ".join(x.capitalize() for x in str(b.get("n") or "").replace("-", "_").split("_") if x)[:16]
            tw = p.fontMetrics().horizontalAdvance(name) + 6
            lab = QRectF(r.left(), r.top() - 13, max(tw, r.width()), 13)
            p.fillRect(lab, col)
            p.setPen(QColor("#ffffff"))
            p.drawText(lab, Qt.AlignCenter, name)
            life = float(b.get("l", 1.0))
            if not b.get("m") and life < 0.999:
                bar = QRectF(r.left(), r.bottom() + 1, r.width(), 3)
                p.fillRect(bar, QColor(0, 0, 0, 160))
                p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * max(0.0, life), 3), QColor("#ffd24d"))
        vision = self.d.get("vision") or {}
        if vision:
            source = {
                "large-current-frame": tr("rl_source_large"),
                "fast-current-frame": tr("rl_source_fast"),
                "combined-current-frame": tr("rl_source_combined"),
                "small-current-frame": tr("rl_source_fallback"),
            }.get(vision.get("source"), tr("rl_source_unknown"))
            details = (f"{tr('rl_units')} {vision.get('units', 0)} · "
                       f"{tr('rl_tracks')} {vision.get('tracks', 0)}")
            if vision.get("ms") is not None:
                details += f" · {vision['ms']} {tr('rl_vision_ms')} ms"
            text = f"{source}  |  {details}"
            p.setFont(ui_font(7.5, QFont.DemiBold))
            fm = p.fontMetrics()
            badge = QRectF(ox + 5, oy + 5, min(w - 10, fm.horizontalAdvance(text) + 16), 23)
            p.setPen(QPen(QColor(255, 255, 255, 45), 1))
            p.setBrush(QColor(10, 16, 24, 210))
            p.drawRoundedRect(badge, 5, 5)
            p.setPen(QColor(TOKENS["text"]))
            p.drawText(badge.adjusted(8, 0, -5, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        t = self.d.get("target")
        if t:
            p.setPen(QPen(QColor(TOKENS["crimson"]), 3)); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(ox + t[0] * w, oy + t[1] * h), 11, 11)


class RoyaleLiveScreen(Screen):
    key, title_key, icon_name = "royale_live", "royale_live_title", "eye"

    def __init__(self, ctx):
        super().__init__(ctx)

        # ── Pre-flight Health Strip (top) ──────────────────────────
        self._preflight_bar = self._build_preflight_bar()
        self.root.addWidget(self._preflight_bar)

        # ── Main content row ──────────────────────────────────────
        top = QHBoxLayout()
        from ..widgets.controls import IconButton
        pop = IconButton("expand", "rl_popout", kind="go", size=14)
        pop.clicked.connect(self.pop_out)
        top.addWidget(pop)
        top.addStretch(1)
        self.root.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.arena = Arena()
        left = GlassCard("rl_arena", "eye", "rl_arena_sub")
        left.add(self.arena)
        row.addWidget(left, 3)
        self.camera = Camera()
        cam = GlassCard("rl_camera", "eye", "rl_camera_sub")
        cam.add(self.camera)
        row.addWidget(cam, 3)

        # ── Side panel with Watch Mode + telemetry ────────────────
        side = QVBoxLayout()
        side.setSpacing(10)

        # Watch Mode toggle
        watch_card = GlassCard("rl_watch_mode", "eye")
        self.watch_toggle = AnimatedToggle()
        self.watch_toggle.setChecked(bool(self.store.get("royale.watch_only", False)))
        self.watch_toggle.toggled.connect(self._on_watch_toggled)
        watch_row = QHBoxLayout()
        watch_row.addWidget(label("rl_watch_mode"))
        watch_row.addStretch(1)
        watch_row.addWidget(self.watch_toggle)
        watch_card.add(watch_row)

        # Telemetry metrics (monospace)
        self.tele_fps = MetricTile("rl_fps", TOKENS["crimson"])
        self.tele_frame_age = MetricTile("rl_frame_age", TOKENS["info"])
        self.tele_vision_src = MetricTile("rl_vision_src", TOKENS["warn"])

        tele_card = GlassCard("rl_telemetry", "chart")
        tele_row = FlowLayout(spacing=8)
        tele_row.addWidget(self.tele_fps)
        tele_row.addWidget(self.tele_frame_age)
        tele_row.addWidget(self.tele_vision_src)
        tele_card.add(tele_row)

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

        for c in (watch_card, tele_card, self.c_state, self.c_think, self.c_them, self.c_ev):
            side.addWidget(c)
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

        # Start pre-flight check off the main thread
        self._run_preflight_async()

    def pop_out(self):
        """The battle view in its own small window, kept on top: put it beside LDPlayer and watch both."""
        from PySide6.QtWidgets import QWidget as _W, QVBoxLayout as _V
        if getattr(self, "_pop", None) is not None and self._pop.isVisible():
            self._pop.raise_(); self._pop.activateWindow(); return
        w = _W(None, Qt.Window | Qt.WindowStaysOnTopHint)
        w.setWindowTitle(tr("nv_royale_live"))
        w.setStyleSheet(f"background: {TOKENS['void']}; color: {TOKENS['text']};")
        lay = _V(w)
        lay.setContentsMargins(6, 6, 6, 6)
        arena = Arena()
        camera = Camera()
        pair = QHBoxLayout()
        pair.addWidget(arena, 1)
        pair.addWidget(camera, 1)
        info = QLabel()
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)
        info.setFont(ui_font(9.5))
        lay.addLayout(pair, 1)
        lay.addWidget(info)
        w.resize(780, 820)
        w._arena, w._info, w._camera = arena, info, camera
        self._pop = w
        w.show()
        self.refresh(force=True)

    def _feed_pop(self, d):
        w = getattr(self, "_pop", None)
        if w is None or not w.isVisible(): return
        w._arena.set_data(d)
        w._camera.set_data(d, self._path().with_suffix(".jpg"))
        if d.get("phase") != "battle":
            w._info.setText(tr("rl_phase_" + str(d.get("phase") or "none"))); return
        dec, th = d.get("decision"), d.get("think") or {}
        t = d.get("time_s", 0)
        head = (f"<b>{int(t // 60)}:{int(t % 60):02d}</b> · {tr('rl_elixir')} {d.get('elixir')} · "
                f"{tr('rl_their_elixir')} {d.get('their_elixir')}")
        arrow_mark = icons.img_tag("chevron_right", 12, TOKENS["crimson"])
        what = (f"{arrow_mark} <b style='color:{TOKENS['crimson']}'>{dec['card']} {tuple(dec['tile'])}</b> — {dec.get('why', '')}"
                if dec else tr("rl_waiting"))
        more = f"{tr('rl_thought')}: {th.get('tried', 0)} · {th.get('ms', 0)} ms" if th.get("tried") else ""
        w._info.setText("<br>".join(x for x in (head, what, decision_projection(dec, th), more) if x))

    # ── Pre-flight Health Strip ──────────────────────────────────
    def _build_preflight_bar(self):
        """Build the top pre-flight health bar with 4 status pills."""
        from ..widgets import FlowLayout
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background: {TOKENS['void2']}; border-bottom: 1px solid {TOKENS['border_solid']};")

        layout = FlowLayout(bar, spacing=12)
        layout.setContentsMargins(16, 4, 16, 4)

        self.pf_assets = StatusPill(key="ok", text="Assets")
        self.pf_adb = StatusPill(key="ok", text="ADB")
        self.pf_ram = StatusPill(key="ok", text="RAM")
        self.pf_disk = StatusPill(key="ok", text="Disk")

        layout.addWidget(self.pf_assets)
        layout.addWidget(self.pf_adb)
        layout.addWidget(self.pf_ram)
        layout.addWidget(self.pf_disk)
        layout.addStretch(1)
        return bar

    def _run_preflight_async(self):
        """Run pre-flight checks in a background thread."""
        from PySide6.QtCore import QThread, Signal, QObject

        class PreflightWorker(QObject):
            finished = Signal(object)

            def run(self):
                import sys
                sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
                from royale.preflight import run_preflight
                result = run_preflight()
                self.finished.emit(result)

        self._pf_thread = QThread(self)
        self._pf_worker = PreflightWorker()
        self._pf_worker.moveToThread(self._pf_thread)
        self._pf_thread.started.connect(self._pf_worker.run)
        self._pf_worker.finished.connect(self._on_preflight_done)
        self._pf_worker.finished.connect(self._pf_thread.quit)
        self._pf_worker.finished.connect(self._pf_worker.deleteLater)
        self._pf_thread.finished.connect(self._pf_thread.deleteLater)
        self._pf_thread.start()

    def _on_preflight_done(self, result):
        """Update pre-flight pills with results."""
        # Assets
        asset_errors = [e for e in result.errors if "asset" in e.lower() or "missing" in e.lower()]
        if asset_errors:
            self.pf_assets.set("bad", "Assets")
        else:
            self.pf_assets.set("ok", "Assets")

        # ADB
        adb_errors = [e for e in result.errors if "adb" in e.lower()]
        adb_warnings = [w for w in result.warnings if "adb" in w.lower() or "device" in w.lower()]
        if adb_errors:
            self.pf_adb.set("bad", "ADB")
        elif adb_warnings:
            self.pf_adb.set("warn", "ADB")
        else:
            self.pf_adb.set("ok", "ADB")

        # RAM
        ram_warnings = [w for w in result.warnings if "ram" in w.lower() or "memory" in w.lower()]
        if ram_warnings:
            self.pf_ram.set("warn", "RAM")
        else:
            self.pf_ram.set("ok", "RAM")

        # Disk
        disk_warnings = [w for w in result.warnings if "disk" in w.lower() or "space" in w.lower()]
        if disk_warnings:
            self.pf_disk.set("warn", "Disk")
        else:
            self.pf_disk.set("ok", "Disk")

    # ── Watch Mode Toggle ────────────────────────────────────────
    def _on_watch_toggled(self, checked: bool):
        """Handle Watch Mode toggle change."""
        self.store.set("royale.watch_only", checked, scope="s")
        if checked:
            self.l_state.setText(tr("rl_phase_watching"))
        else:
            self.refresh(force=True)

    # ── Telemetry Updates ────────────────────────────────────────
    def _update_telemetry(self, d):
        """Update FPS, frame age, vision source metrics."""
        vision = d.get("vision") or {}
        perf = d.get("perf") or {}

        # FPS from video stream
        fps = vision.get("fps", 0)
        if fps > 0:
            self.tele_fps.set(f"{fps:.0f}")

        # Frame age / stale status
        frame_age = vision.get("decision_age_ms", 0)
        if frame_age > 0:
            if frame_age > 500:
                self.tele_frame_age.set(f"{frame_age:.0f}ms")
            else:
                self.tele_frame_age.set(f"{frame_age:.0f}ms")

        # Vision source
        source_map = {
            "large-current-frame": "Large",
            "fast-current-frame": "Fast",
            "combined-current-frame": "Combined",
            "small-current-frame": "Fallback",
        }
        src = source_map.get(vision.get("source"), "Unknown")
        self.tele_vision_src.set(src)

    def _path(self):
        acc = self.store.account or "main"
        return Path.home() / ".CoC_Bot" / "learn" / \
            f"royale_live_{''.join(c for c in str(acc) if c.isalnum() or c in '-_') or 'main'}.json"

    def on_show(self):
        self.refresh(force=True)

    def refresh(self, force=False):
        popped = getattr(self, "_pop", None) is not None and self._pop.isVisible()
        if not self.isVisible() and not popped and not force: return
        p = self._path()
        try:
            mt = p.stat().st_mtime
        except OSError:
            self.arena.set_data({"phase": "none"})
            self.l_state.setText(tr("rl_no_data"))
            self._feed_pop({"phase": "none"})
            return
        stamp = (p, mt)
        if stamp == self._mtime and not force:
            if self.camera.d.get("phase") != "battle" or __import__("time").time() - self.camera.d.get("t", 0) <= 8:
                return
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self._mtime = stamp
        import time as _t
        if d.get("phase") == "battle" and _t.time() - d.get("t", 0) > 8: d["phase"] = "stale"
        self.arena.set_data(d)
        self.camera.set_data(d, p.with_suffix(".jpg"))
        self.show_panel(d)
        self._feed_pop(d)
        self._update_telemetry(d)

    def show_panel(self, d):
        if d.get("phase") != "battle":
            self.l_state.setText(tr("rl_phase_" + str(d.get("phase") or "none")) + (f"\n{d.get('note')}" if d.get("note") else ""))
            return
        t = d.get("time_s", 0)
        hand = d.get("hand") or []
        arrow_mark = icons.img_tag("chevron_right", 12, TOKENS["crimson"])

        def card_txt(h):
            from ..icons import pixmap as icon_pixmap
            check_icon = icons.img_tag("dot", 10, TOKENS["ok"]) if h.get("ready") else icons.img_tag("dot", 10, TOKENS["dim"])
            evo_icon = icons.img_tag("sparkle", 10, TOKENS["crimson"]) if h.get("evo") else ""
            hero_icon = icons.img_tag("crown", 10, TOKENS["crimson"]) if h.get("hero") else ""
            return f"{check_icon} {str(h.get('card'))} {evo_icon} {hero_icon}"
        self.l_state.setText(
            f"{tr('rl_time')}: {int(t // 60)}:{int(t % 60):02d}" + (f"  ·  {tr('rl_double')}" if d.get("double") else "") + "\n" +
            f"{tr('rl_elixir')}: {d.get('elixir')}  ·  {tr('rl_their_elixir')}: ~{d.get('their_elixir')}\n" +
            f"{tr('rl_hand')}: " + "   ".join(card_txt(h) for h in hand) + f"\n{tr('rl_next')}: {d.get('next')}" +
            self._vision_line(d))
        dec = d.get("decision")
        th = d.get("think") or {}
        eng = d.get("engine") or {}
        lines = []
        if dec:
            lines.append(f"{arrow_mark} <b style='color:{TOKENS['crimson']}'>{dec['card']} {tuple(dec['tile'])}</b><br>{dec.get('why', '')}")
        else:
            lines.append(f"<b>{tr('rl_waiting')}</b>")
        projection = decision_projection(dec, th)
        if projection:
            lines.append(projection)
        if th.get("tried"):
            best = (th.get("cands") or [{}])[0]
            lines.append(f"{tr('rl_thought')}: {th['tried']} · {th.get('ms', 0)} ms" +
                         (f" · {tr('rl_best')}: {best.get('card')} {tuple(best.get('tile', []))} {best.get('v', 0):+.1f}" if best else ""))
        if th.get("ai"): lines.append(th["ai"])
        lines.append((tr("rl_engine_on") if eng.get("on") else tr("rl_engine_off") + (f" ({eng.get('why')})" if eng.get("why") else "")) +
                     (" · " + tr("rl_ai_on") if eng.get("ai") else ""))
        pf = d.get("perf") or {}
        if pf.get("loop"):
            lines.append(f"<span style='color:{TOKENS['muted']}'>{tr('rl_perf')}: "
                         f"{tr('rl_p_capture')} {pf.get('capture')} · {tr('rl_p_look')} {pf.get('look')} · "
                         f"{tr('rl_p_think')} {pf.get('decide', 0) + pf.get('engine', 0)} · {tr('rl_p_total')} {pf.get('loop')} ms"
                         f" ({tr('rl_p_worst')} {pf.get('worst_loop')})</span>")
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

    @staticmethod
    def _vision_line(d):
        vision = d.get("vision") or {}
        if not vision: return ""
        source = {
            "large-current-frame": tr("rl_source_large"),
            "fast-current-frame": tr("rl_source_fast"),
            "combined-current-frame": tr("rl_source_combined"),
            "small-current-frame": tr("rl_source_fallback"),
        }.get(vision.get("source"), tr("rl_source_unknown"))
        line = f"\n{tr('rl_vision')}: {source} · {tr('rl_units')} {vision.get('units', 0)} · " \
               f"{tr('rl_tracks')} {vision.get('tracks', 0)}"
        if vision.get("ms") is not None: line += f" · {vision['ms']} {tr('rl_vision_ms')} ms"
        if vision.get("decision_age_ms") is not None:
            line += f" · {tr('rl_decision_age')} {vision['decision_age_ms']} ms"
        return line
