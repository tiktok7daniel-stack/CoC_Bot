"""
Collapsible navigation rail (right side in Arabic, left in English): crest + title, nav items with a
glowing gradient pill for the active page, "soon" items, and a footer capsule with the emulator,
the version and a pulsing state dot.
"""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS, color, ui_font

NAV = [
    ("dash", "nv_home", "trophy"), ("deck", "nv_deck", "bolt"), ("acc", "nv_acc", "id"), ("atk", "nv_atk", "swords"), ("bb", "nv_bb", "moon"),
    ("res", "nv_stats", "chart"), ("upg", "nv_village", "home"), ("teach", "nv_manager", "hammer"), ("learn", "nv_learn", "school"),
    ("log", "nv_log", "scroll"), ("set", "nv_bot", "bot"), ("royale", "nv_royale", "swords"), ("royale_live", "nv_royale_live", "eye"),
]
# Clash Royale mode: only its own screen (+ the general ones: accounts, the bot's settings / Telegram)
ROYALE_KEYS = {"royale", "royale_live", "acc", "set"}
SOON = []   # clan capital / clan war / chat removed: not part of the farming bot


class NavButton(QAbstractButton):
    def __init__(self, key, text_key, icon_name, soon=False):
        super().__init__()
        self.key, self.text_key, self.icon_name, self.soon = key, text_key, icon_name, soon
        self.setCheckable(not soon)
        self.setCursor(Qt.PointingHandCursor if not soon else Qt.ArrowCursor)
        self.setFixedHeight(44)
        self.collapsed = False
        self.badge = 0
        self._hover = False
        on_lang(self.update)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(200, 44)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        rtl = self.layoutDirection() == Qt.RightToLeft
        on = self.isChecked()
        hov = self._hover and not self.soon
        if on:
            # tinted pill + gold indicator bar on the leading edge
            p.setPen(Qt.NoPen)
            g = QLinearGradient(r.topRight() if rtl else r.topLeft(), r.topLeft() if rtl else r.topRight())
            g.setColorAt(0, QColor(245, 183, 64, 46))
            g.setColorAt(1, QColor(245, 183, 64, 8))
            p.setBrush(g)
            p.drawRoundedRect(r, 14, 14)
            p.setPen(QPen(QColor(245, 183, 64, 70), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 14, 14)
            bar = QRectF(r.right() - 3, r.top() + 10, 3, r.height() - 20) if rtl else QRectF(r.left(), r.top() + 10, 3, r.height() - 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TOKENS["accent"]))
            p.drawRoundedRect(bar, 1.5, 1.5)
        elif hov:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 12))
            p.drawRoundedRect(r, 14, 14)
        fg = TOKENS["accent_hi"] if on else (TOKENS["dim"] if self.soon else ("#FFFFFF" if hov else TOKENS["muted"]))
        ic_color = TOKENS["accent"] if on else (TOKENS["dim"] if self.soon else ("#FFFFFF" if hov else TOKENS["muted"]))
        isz = 20
        if self.collapsed:
            pm = icons.pixmap(self.icon_name, isz, ic_color)
            p.drawPixmap(int(r.center().x() - isz / 2), int(r.center().y() - isz / 2), pm)
        else:
            pm = icons.pixmap(self.icon_name, isz, ic_color)
            ix = r.right() - 16 - isz if rtl else r.left() + 16
            p.drawPixmap(int(ix), int(r.center().y() - isz / 2), pm)
            p.setPen(QColor(fg))
            p.setFont(ui_font(10.5, 700 if on else 500))
            reserve = 64 if self.soon else 0   # room for the "soon" badge
            tr_rect = QRectF(r.left() + 16 + reserve, r.top(), r.width() - 32 - isz - 10 - reserve, r.height())
            if not rtl: tr_rect.moveLeft(r.left() + 16 + isz + 10)
            align = (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter
            if on or hov:
                halo = QColor(245, 183, 64, 60) if on else QColor(255, 255, 255, 26)
                p.setPen(halo)
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1.5, -1), (1.5, 1), (1.5, -1), (-1.5, 1)):
                    p.drawText(tr_rect.translated(dx, dy), align, tr(self.text_key))
                p.setPen(QColor(fg))
            p.drawText(tr_rect, align, tr(self.text_key))
            if self.soon:
                txt = tr("soon")
                p.setFont(ui_font(7.5, 600))
                w = p.fontMetrics().horizontalAdvance(txt) + 14
                br = QRectF(r.left() + 10 if rtl else r.right() - 10 - w, r.center().y() - 9, w, 18)
                p.setPen(QPen(QColor(TOKENS["border_hover"]), 1))
                p.setBrush(QColor(255, 255, 255, 8))
                p.drawRoundedRect(br, 9, 9)
                p.setPen(QColor(TOKENS["muted"]))
                p.drawText(br, Qt.AlignCenter, txt)
        if self.badge:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TOKENS["bad"]))
            bx = r.left() + 14 if (rtl and not self.collapsed) else r.right() - 18
            p.drawEllipse(QRectF(bx - 4, r.top() + 8, 18, 16))
            p.setPen(QColor("#FFFFFF"))
            p.setFont(ui_font(7.5, 700))
            p.drawText(QRectF(bx - 4, r.top() + 8, 18, 16), Qt.AlignCenter, str(min(99, self.badge)))
        p.end()


class Sidebar(QFrame):
    navigate = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("Sidebar")
        self.expanded_w, self.collapsed_w = 248, 76
        self.setFixedWidth(self.expanded_w)
        self.collapsed = False
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(4)
        top = QHBoxLayout()
        self.toggle = QToolButton()
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setFixedSize(34, 34)
        self.toggle.setStyleSheet(f"QToolButton {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 9px; }}"
                                  f" QToolButton:hover {{ border-color: {TOKENS['border_hover']}; }}")
        self.toggle.clicked.connect(self.toggle_collapse)
        top.addStretch(1)
        top.addWidget(self.toggle)
        v.addLayout(top)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        self.crest = QLabel()
        self.crest.setPixmap(icons.pixmap("crest", 48))
        glow = QGraphicsDropShadowEffect(self.crest)
        glow.setBlurRadius(26)
        glow.setOffset(0, 2)
        glow.setColor(QColor(245, 183, 64, 70))
        self.crest.setGraphicsEffect(glow)
        brand.addWidget(self.crest)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.title = QLabel()
        from ..logo import wordmark_pixmap
        self.title.setPixmap(wordmark_pixmap(118, glow=0.0))
        self.title.setToolTip("Clash Farmer")
        self.subtitle = QLabel(tr("app_sub"))
        self.subtitle.setProperty("role", "sub")
        on_lang(lambda: self.subtitle.setText(tr("app_sub")))
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        self.names = QWidget()
        self.names.setLayout(names)
        brand.addWidget(self.names, 1)
        v.addLayout(brand)
        v.addSpacing(14)
        self.buttons = {}
        for key, tk, ic in NAV:
            b = NavButton(key, tk, ic)
            b.clicked.connect(lambda _=False, k=key: self.navigate.emit(k))
            self.buttons[key] = b
            v.addWidget(b)
        v.addSpacing(6)
        self.soon = []
        for tk, ic in SOON:
            b = NavButton(None, tk, ic, soon=True)
            self.soon.append(b)
            v.addWidget(b)
        v.addStretch(1)
        self.switch_game = NavButton("switch_game", "nv_switch_game", "refresh")    # back to the game chooser
        self.switch_game.setCheckable(False)
        self.switch_game.clicked.connect(lambda: self.navigate.emit("switch_game"))
        v.addWidget(self.switch_game)
        self.capsule = FooterCapsule()
        v.addWidget(self.capsule)
        self._anim = QPropertyAnimation(self, b"minimumWidth", self)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth", self)
        for a in (self._anim, self._anim2):
            a.setDuration(180)
            a.setEasingCurve(QEasingCurve.OutCubic)
        self._apply_toggle_icon()
        on_lang(self._apply_toggle_icon)

    def _apply_toggle_icon(self):
        rtl = self.layoutDirection() == Qt.RightToLeft
        name = ("chevron_left" if not self.collapsed else "chevron_right") if not rtl else ("chevron_right" if not self.collapsed else "chevron_left")
        self.toggle.setIcon(icons.icon(name, TOKENS["text"], 16))

    def set_mode(self, royale):
        """Clash Royale: its screen only (+ accounts, settings); Clash of Clans: everything but the Royale screen."""
        for k, b in self.buttons.items():
            b.setVisible((k in ROYALE_KEYS) if royale else (k not in ("royale", "royale_live")))

    def set_active(self, key):
        for k, b in self.buttons.items(): b.setChecked(k == key)

    def set_badge(self, key, n):
        if key in self.buttons:
            self.buttons[key].badge = n
            self.buttons[key].update()

    def toggle_collapse(self):
        self.collapsed = not self.collapsed
        w = self.collapsed_w if self.collapsed else self.expanded_w
        for a in (self._anim, self._anim2):
            a.stop()
            a.setStartValue(self.width())
            a.setEndValue(w)
            a.start()
        for b in list(self.buttons.values()) + self.soon + [self.switch_game]:
            b.collapsed = self.collapsed
            b.setToolTip(tr(b.text_key) if self.collapsed else "")
            b.update()
        self.names.setVisible(not self.collapsed)
        self.capsule.set_collapsed(self.collapsed)
        self._apply_toggle_icon()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 24, 24)
        p.fillPath(path, QColor(12, 12, 16, 235))
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor(245, 183, 64, 22))
        g.setColorAt(0.35, QColor(245, 183, 64, 0))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawPath(path)
        p.end()


class FooterCapsule(QFrame):
    """Emulator name, version badge and a pulsing dot showing the bot state."""

    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)
        self.dot = PulseDot()
        h.addWidget(self.dot)
        self.state = QLabel("—")
        self.state.setStyleSheet("font-weight: 700;")
        h.addWidget(self.state, 1)
        self.emu = QLabel("—")
        self.emu.setProperty("role", "dim")
        self.emu.hide()
        self.ver = QLabel("")
        self.ver.setStyleSheet(f"background: rgba(245, 183, 64,0.18); border: 1px solid {TOKENS['border']}; border-radius: 8px;"
                               f" padding: 1px 7px; font-family: 'JetBrains Mono'; font-size: 8pt; color: #E9D3A6;")
        h.addWidget(self.ver)
        self.setStyleSheet(f"FooterCapsule {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 16px; }}")

    def set_state(self, key, text, emulator, version):
        self.dot.set_color(TOKENS[{"running": "ok", "ready": "ok", "idle": "info", "starting": "info", "error": "bad", "stopped": "dim"}.get(key, "warn")],
                           pulse=key in ("running", "starting", "idle"))
        self.state.setText(text)
        self.emu.setText(emulator)
        self.ver.setText(f"v{version}" if version else "")

    def set_collapsed(self, c):
        for w in (self.state, self.ver): w.setVisible(not c)


class PulseDot(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self.c = QColor(TOKENS["dim"])
        self.pulse = False
        self.phase = 0.0
        self.t = QTimer(self)
        self.t.timeout.connect(self._tick)
        self.t.start(60)

    def set_color(self, c, pulse=False):
        self.c = QColor(c)
        self.pulse = pulse
        self.update()

    def _tick(self):
        if self.pulse:
            self.phase = (self.phase + 0.06) % 1.0
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.pulse:
            halo = QColor(self.c)
            halo.setAlphaF(0.45 * (1 - self.phase))
            rr = 3 + 4 * self.phase
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QRectF(7 - rr, 7 - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.NoPen)
        p.setBrush(self.c)
        p.drawEllipse(QRectF(3.5, 3.5, 7, 7))
        p.end()
