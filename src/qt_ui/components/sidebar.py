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
    ("dash", "nv_home", "trophy"), ("acc", "nv_acc", "id"), ("atk", "nv_atk", "swords"), ("bb", "nv_bb", "moon"),
    ("res", "nv_stats", "chart"), ("upg", "nv_village", "home"), ("teach", "nv_manager", "hammer"),
    ("log", "nv_log", "scroll"), ("set", "nv_bot", "bot"),
]
SOON = [("nv_capital", "castle"), ("nv_war", "shield"), ("nv_chat", "chat")]


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
        if self.isChecked():
            g = QLinearGradient(r.topLeft(), r.topRight())
            a, b = QColor(TOKENS["nav_from"]), QColor(TOKENS["nav_to"])
            g.setColorAt(0, b if rtl else a)
            g.setColorAt(1, a if rtl else b)
            for k, alpha in ((6, 26), (3, 50)):
                gc = QColor(TOKENS["purple"])
                gc.setAlpha(alpha)
                p.setPen(QPen(gc, k))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        elif self._hover and not self.soon:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(139, 92, 246, 30))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        fg = "#FFFFFF" if self.isChecked() else (TOKENS["dim"] if self.soon else TOKENS["text"])
        ic_color = "#FFFFFF" if self.isChecked() else (TOKENS["dim"] if self.soon else "#C4B5FD")
        isz = 20
        if self.collapsed:
            pm = icons.pixmap(self.icon_name, isz, ic_color)
            p.drawPixmap(int(r.center().x() - isz / 2), int(r.center().y() - isz / 2), pm)
        else:
            pm = icons.pixmap(self.icon_name, isz, ic_color)
            ix = r.right() - 16 - isz if rtl else r.left() + 16
            p.drawPixmap(int(ix), int(r.center().y() - isz / 2), pm)
            p.setPen(QColor(fg))
            p.setFont(ui_font(10.5, 700 if self.isChecked() else 500))
            tr_rect = QRectF(r.left() + 16, r.top(), r.width() - 32 - isz - 10, r.height())
            if not rtl: tr_rect.moveLeft(r.left() + 16 + isz + 10)
            p.drawText(tr_rect, (Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter, tr(self.text_key))
            if self.soon:
                txt = tr("soon")
                p.setFont(ui_font(7.5, 600))
                w = p.fontMetrics().horizontalAdvance(txt) + 14
                br = QRectF(r.left() + 10 if rtl else r.right() - 10 - w, r.center().y() - 9, w, 18)
                p.setPen(QPen(QColor(TOKENS["border_hover"]), 1))
                p.setBrush(QColor(139, 92, 246, 30))
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
        self.crest.setPixmap(icons.pixmap("crest", 46))
        glow = QGraphicsDropShadowEffect(self.crest)
        glow.setBlurRadius(30)
        glow.setOffset(0, 0)
        glow.setColor(color("fuchsia", 0.55))
        self.crest.setGraphicsEffect(glow)
        brand.addWidget(self.crest)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.title = QLabel("CoC Bot")
        self.title.setStyleSheet("font-size: 15pt; font-weight: 800;")
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
        for b in list(self.buttons.values()) + self.soon:
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
        path.addRoundedRect(r, 18, 18)
        p.fillPath(path, QColor(19, 17, 29, 215))
        g = QRadialGradient(r.center().x(), r.top() + 90, 200)
        g.setColorAt(0, QColor(139, 92, 246, 56))
        g.setColorAt(1, QColor(139, 92, 246, 0))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(168, 85, 247, 46), 1))
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
        h.addWidget(self.emu)
        self.ver = QLabel("")
        self.ver.setStyleSheet(f"background: rgba(139,92,246,0.18); border: 1px solid {TOKENS['border']}; border-radius: 8px;"
                               f" padding: 1px 7px; font-family: 'JetBrains Mono'; font-size: 8pt; color: #C4B5FD;")
        h.addWidget(self.ver)
        self.setStyleSheet(f"FooterCapsule {{ background: {TOKENS['glass2']}; border: 1px solid {TOKENS['border']}; border-radius: 16px; }}")

    def set_state(self, key, text, emulator, version):
        self.dot.set_color(TOKENS[{"running": "ok", "idle": "info", "starting": "info", "error": "bad", "stopped": "dim"}.get(key, "warn")],
                           pulse=key in ("running", "starting", "idle"))
        self.state.setText(text)
        self.emu.setText(emulator)
        self.ver.setText(f"v{version}" if version else "")

    def set_collapsed(self, c):
        for w in (self.state, self.emu, self.ver): w.setVisible(not c)


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
