"""
Building blocks used by every screen: glass cards, animated toggles, number fields, status pills,
icon buttons, underline tabs, a flow layout, toasts / banners, and helpers that bind a control to a
settings path in the Store.
"""
from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QDoubleSpinBox, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLayout, QLineEdit, QPushButton, QSizePolicy, QSpinBox,
                               QTimeEdit, QVBoxLayout, QWidget)

from .. import icons
from ..i18n import on_lang, tr
from ..theme import TOKENS, color


# ====================================================================== text helpers
def label(text="", role=None, wrap=False, key=None):
    """QLabel; with key= the text follows the language."""
    lb = QLabel(tr(key) if key else text)
    if role: lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if key:
        on_lang(lambda: lb.setText(tr(key)))
    return lb


def retext(widget, key, fmt=None):
    """Keep a widget's text in the current language (setText / setPlaceholderText)."""
    def apply():
        text = tr(key) if fmt is None else fmt(tr(key))
        if isinstance(widget, QLineEdit): widget.setPlaceholderText(text)
        else: widget.setText(text)
    apply()
    on_lang(apply)
    return widget


# ====================================================================== glass card
class GlassCard(QFrame):
    """Translucent card: 1px neon border, soft violet glow when hovered (or always with glow=True)."""

    def __init__(self, title_key=None, icon_name=None, sub_key=None, glow=False, parent=None, pad=16):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._hover = False
        self._glow = glow
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(pad, pad - 2, pad, pad)
        self.v.setSpacing(10)
        self.header = None
        self.tools = None
        if title_key or icon_name:
            self.header = QHBoxLayout()
            self.header.setSpacing(10)
            self.header.setAlignment(Qt.AlignTop)
            if icon_name:
                badge = IconBadge(icon_name)
                self.header.addWidget(badge)
            box = QVBoxLayout()
            box.setSpacing(0)
            self.title = label(key=title_key, role="h3") if title_key else label("", "h3")
            box.addWidget(self.title)
            self.header.addLayout(box, 1)
            self.tools = QHBoxLayout()
            self.tools.setSpacing(6)
            self.header.addLayout(self.tools)
            self.v.addLayout(self.header)
            if sub_key: # own full-width line: a wrapped label inside the header row could overlap the title
                self.sub = label(key=sub_key, role="sub", wrap=True)
                self.v.addWidget(self.sub)
        self.body = QVBoxLayout()
        self.body.setSpacing(4)
        self.v.addLayout(self.body)
        self.v.addStretch(1)   # a card taller than its content keeps everything at the top
        from ..theme import LIGHT
        if glow and not LIGHT:
            eff = QGraphicsDropShadowEffect(self)
            eff.setBlurRadius(36)
            eff.setOffset(0, 6)
            eff.setColor(QColor(0, 0, 0, 160))
            self.setGraphicsEffect(eff)

    def add(self, w, stretch=0):
        if isinstance(w, QLayout): self.body.addLayout(w, stretch)
        else: self.body.addWidget(w, stretch)
        if stretch: # this card's content should grow with the card instead of the spacer under it
            self.v.setStretch(self.v.indexOf(self.body), 1)
            self.v.setStretch(self.v.count() - 1, 0)
        return w

    def add_tool(self, w):
        if self.tools is not None: self.tools.addWidget(w)
        return w

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 20, 20)
        # card: solid dark surface, a faint top light, a hairline border; gold edge + glow when hovered
        p.fillPath(path, QColor(14, 14, 19, 236))
        sheen = QLinearGradient(r.topLeft(), r.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 12))
        sheen.setColorAt(0.25, QColor(255, 255, 255, 0))
        p.fillPath(path, QBrush(sheen))
        if self._glow:
            g = QRadialGradient(QPointF(r.center().x(), r.top()), max(r.width(), r.height()) * 0.7)
            g.setColorAt(0, QColor(245, 183, 64, 26))
            g.setColorAt(1, QColor(245, 183, 64, 0))
            p.fillPath(path, QBrush(g))
        if self._hover:
            bg = QLinearGradient(r.topLeft(), r.bottomLeft())
            bg.setColorAt(0, QColor(245, 183, 64, 120))
            bg.setColorAt(1, QColor(245, 183, 64, 20))
            p.setPen(QPen(QBrush(bg), 1.2))
        else:
            p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawPath(path)
        p.end()


class IconBadge(QLabel):
    """Rounded square with a duotone icon inside (card headers)."""

    def __init__(self, name, size=34, tint="#F5B740"):
        super().__init__()
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(icons.pixmap(name, int(size * 0.52), tint))
        self.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(245,183,64,0.16), stop:1 rgba(245,183,64,0.05));"
                           " border: 1px solid rgba(245,183,64,0.22); border-radius: 10px;")


# ====================================================================== toggle switch
class Toggle(QAbstractButton):
    """Animated pill switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, v):
        super().setChecked(bool(v))
        self._pos = 1.0 if v else 0.0
        self.update()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(46, 26)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off = QColor(TOKENS["glass3"])
        if self._pos > 0:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, QColor(TOKENS["violet"]))
            g.setColorAt(1, QColor(TOKENS["fuchsia"]))
            p.setBrush(QBrush(g) if self._pos > 0.5 else off)
        else:
            p.setBrush(off)
        p.setPen(QPen(QColor(245, 183, 64, 90), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        rtl = self.layoutDirection() == Qt.RightToLeft
        start, end = r.left() + 3, r.right() - 3 - d
        if rtl: start, end = end, start
        x = start + (end - start) * self._pos
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF") if self.isEnabled() else QColor(TOKENS["dim"]))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.end()


# ====================================================================== number / text fields
class NumField(QSpinBox):
    """Integer field that ignores the mouse wheel unless focused (no accidental changes while scrolling)."""

    def __init__(self, lo=0, hi=10**9, step=1, width=120):
        super().__init__()
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGroupSeparatorShown(True)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.setLayoutDirection(Qt.LeftToRight)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


class FloatField(QDoubleSpinBox):
    def __init__(self, lo=0.0, hi=10**6, step=0.5, width=100, decimals=1):
        super().__init__()
        self.setRange(lo, hi)
        self.setSingleStep(step)
        self.setDecimals(decimals)
        self.setFixedWidth(width)
        self.setAlignment(Qt.AlignCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setLayoutDirection(Qt.LeftToRight)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


class Combo(QComboBox):
    """Combo with (value, text key) items; text follows the language."""

    def __init__(self, items, width=None):
        super().__init__()
        self._items = list(items)
        for v, k in self._items: self.addItem(tr(k), v)
        if width: self.setFixedWidth(width)
        self.setFocusPolicy(Qt.StrongFocus)
        on_lang(self._relabel)

    def _relabel(self):
        for i, (v, k) in enumerate(self._items): self.setItemText(i, tr(k))

    def value(self):
        return self.currentData()

    def set_value(self, v):
        i = self.findData(v)
        if i >= 0: self.setCurrentIndex(i)

    def wheelEvent(self, e):
        if self.hasFocus(): super().wheelEvent(e)
        else: e.ignore()


# ====================================================================== buttons & pills
class IconButton(QPushButton):
    def __init__(self, icon_name=None, key=None, kind=None, text="", icon_color=None, size=16, tip_key=None):
        super().__init__(text)
        self._icon_name, self._icon_color, self._size = icon_name, icon_color, size
        if kind: self.setProperty("kind", kind)
        self.setCursor(Qt.PointingHandCursor)
        if icon_name: self.set_icon(icon_name, icon_color)
        if key: retext(self, key)
        if tip_key:
            self.setToolTip(tr(tip_key))
            on_lang(lambda: self.setToolTip(tr(tip_key)))

    def set_icon(self, name, col=None):
        kind = self.property("kind")
        default = TOKENS["on_accent"] if kind == "primary" else ("#04170D" if kind == "go" else TOKENS["text"])
        self.setIcon(icons.icon(name, col or default, self._size))
        self.setIconSize(QSize(self._size, self._size))


class StatusPill(QLabel):
    """Rounded pill with a colored dot: running / stopped / paused …"""
    COLORS = {"running": "ok", "ready": "ok", "idle": "info", "starting": "info", "stopped": "dim", "paused": "warn", "scheduled": "warn",
              "break": "warn", "limit": "warn", "error": "bad", "ok": "ok", "bad": "bad", "warn": "warn", "info": "info"}

    def __init__(self, key="stopped", text=None):
        super().__init__()
        self.setTextFormat(Qt.RichText)
        self.set(key, text)

    def set(self, key, text=None):
        c = TOKENS[self.COLORS.get(key, "dim")]
        mark = icons.img_tag("verified", 15) if key in ("ok", "learned") else f'<span style="color:{c};font-size:13pt">&#9679;</span>'
        if key == "learned": mark = icons.img_tag("verified_gold", 15)
        self.setText(f'{mark}&nbsp;{text if text is not None else tr("st_" + key)}')
        self.setStyleSheet(f"QLabel {{ background: rgba(255,255,255,0.03); border: 1px solid {TOKENS['border']};"
                           f" border-radius: 13px; padding: 2px 12px; font-weight: 600; }}")


class Chip(QPushButton):
    def __init__(self, text="", key=None, checkable=True):
        super().__init__(text)
        self.setProperty("kind", "chip")
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        if key: retext(self, key)


# ====================================================================== tabs (underline)
class SegTabs(QWidget):
    changed = Signal(str)

    def __init__(self, items):
        """items: [(key, text key, icon name)]"""
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        self.buttons = {}
        for key, tkey, ic in items:
            b = IconButton(ic, tkey, kind="ghost", icon_color=TOKENS["muted"], size=15)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.select(k))
            b.setMinimumHeight(40)
            self.buttons[key] = b
            h.addWidget(b)
        h.addStretch(1)
        self.current = None
        self.setStyleSheet(f"""
            QPushButton {{ border-radius: 0; padding: 8px 18px; border: 0; border-bottom: 2px solid transparent; color: {TOKENS['muted']}; }}
            QPushButton:hover {{ color: {TOKENS['text']}; background: transparent; }}
            QPushButton:checked {{ color: {TOKENS['text']}; border-bottom: 2px solid {TOKENS['purple']}; }}""")

    def select(self, key, emit=True):
        self.current = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
            b.set_icon(b._icon_name, TOKENS["purple"] if k == key else TOKENS["muted"])
        if emit: self.changed.emit(key)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(QColor(TOKENS["border_solid"]), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


# ====================================================================== form rows
def form_row(key=None, sub_key=None, widget=None, unit_key=None, text=None, icon_name=None, extra=None):
    """[label + sub] .......... [widget] [unit]"""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 7, 0, 7)
    h.setSpacing(10)
    if icon_name:
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 20, TOKENS["muted"]))
        h.addWidget(ic)
    box = QVBoxLayout()
    box.setSpacing(1)
    box.addWidget(label(text or "", key=key) if key else label(text or ""))
    if sub_key: box.addWidget(label(key=sub_key, role="sub", wrap=True))
    h.addLayout(box, 1)
    if extra is not None: h.addWidget(extra)
    if widget is not None:
        if isinstance(widget, QLayout): h.addLayout(widget)
        else: h.addWidget(widget)
    if unit_key: h.addWidget(label(key=unit_key, role="sub"))
    w.setObjectName("FormRow")
    w.setStyleSheet(f"#FormRow {{ border-bottom: 1px dashed {TOKENS['border_solid']}; }}")
    return w


def hline():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {TOKENS['border_solid']};")
    return f


def note(key, icon_name="info", tint=None):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 6, 0, 0)
    h.setSpacing(8)
    ic = QLabel()
    ic.setPixmap(icons.pixmap(icon_name, 16, tint or TOKENS["purple"]))
    ic.setAlignment(Qt.AlignTop)
    h.addWidget(ic)
    h.addWidget(label(key=key, role="sub", wrap=True), 1)
    return w


# ====================================================================== flow layout
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, i):
        return self.items[i] if 0 <= i < len(self.items) else None

    def takeAt(self, i):
        return self.items.pop(i) if 0 <= i < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self.items: s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        rtl = self.parentWidget() is not None and self.parentWidget().layoutDirection() == Qt.RightToLeft
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self.items:
            sz = it.sizeHint()
            if x + sz.width() > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + sp, 0
            if not test:
                gx = rect.right() - (x - rect.x()) - sz.width() + 1 if rtl else x
                it.setGeometry(QRect(QPoint(gx, y), sz))
            x += sz.width() + sp
            line_h = max(line_h, sz.height())
        return y + line_h - rect.y()

    def clear(self):
        while self.items:
            it = self.items.pop()
            if it.widget(): it.widget().deleteLater()


# ====================================================================== toast & banner
class Toast(QLabel):
    """Short message at the bottom of the window (fades away)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_msg(self, text, kind="info"):
        c = {"info": TOKENS["purple"], "ok": TOKENS["ok"], "bad": TOKENS["bad"], "warn": TOKENS["warn"]}[kind]
        self.setText(text)
        self.setStyleSheet(f"QLabel {{ background: #1A1418; border: 1px solid {c}; border-radius: 12px; padding: 12px 22px;"
                           f" font-weight: 700; color: {TOKENS['text']}; }}")
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 60)
        self.raise_()
        self.show()
        self._timer.start(2800)


class Banner(QFrame):
    """Big green notice (walls finished, record now …) with an OK button."""

    def __init__(self, parent):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 8, 12, 8)
        from .seal import AnimatedSeal
        self.seal = AnimatedSeal(28)
        h.addWidget(self.seal)
        self.ic = QLabel()
        h.addWidget(self.ic)
        self.text = QLabel()
        self.text.setStyleSheet("font-size: 13pt; font-weight: 800; color: white;")
        h.addWidget(self.text, 1)
        ok = QPushButton("OK")
        ok.setCursor(Qt.PointingHandCursor)
        ok.clicked.connect(self.hide)
        h.addWidget(ok)
        self.hide()

    def show_msg(self, text, kind="ok", icon_name="check"):
        c1, c2, edge = {"ok": ("#16A36A", "#0B6E47", "#3DD68C"), "bad": ("#C6383D", "#7E1D22", "#F0555A"),
                        "rec": ("#B4232A", "#5E1016", "#F0555A")}.get(kind, ("#2A2214", "#15120C", "#F5B740"))
        self.setStyleSheet(f"Banner {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {c1}, stop:1 {c2});"
                           f" border: 1px solid {edge}; border-radius: 18px; }}"
                           " QPushButton { background: rgba(255,255,255,0.14); border: 0; color: white; border-radius: 10px; padding: 6px 14px; }")
        self.text.setStyleSheet("font-size: 12.5pt; font-weight: 800; color: " + ("#FFE7A8" if kind not in ("ok", "bad", "rec") else "white") + ";")
        self.ic.setPixmap(icons.pixmap(icon_name, 22, "#FFFFFF" if kind in ("ok", "bad", "rec") else "#F5B740"))
        done = kind == "ok"
        self.seal.setVisible(done)
        self.ic.setVisible(not done)
        self.text.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.setFixedWidth(min(640, par.width() - 80))
        self.move((par.width() - self.width()) // 2, 96)
        self.raise_()
        self.show()
        if done: self.seal.play()


# ====================================================================== store bindings
def bind_toggle(store, w, path, scope="s"):
    store.bind(scope, path, lambda v: w.setChecked(bool(v)))
    w.toggled.connect(lambda v: store.set(path, bool(v), scope))
    return w


def bind_num(store, w, path, scope="s"):
    def put(v):
        try: w.setValue(type(w.value())(v if v is not None else 0))
        except (TypeError, ValueError): w.setValue(0)
    store.bind(scope, path, put)
    w.valueChanged.connect(lambda v: store.set(path, v, scope))
    return w


def bind_combo(store, w, path, scope="s"):
    store.bind(scope, path, lambda v: w.set_value(v))
    w.currentIndexChanged.connect(lambda _i: store.set(path, w.value(), scope))
    return w


def bind_line(store, w, path, scope="s"):
    store.bind(scope, path, lambda v: w.setText("" if v is None else str(v)))
    w.textEdited.connect(lambda v: store.set(path, v, scope))
    return w


def bind_time(store, w, path, scope="s"):
    store.bind(scope, path, lambda v: w.set_text_time(v))
    w.time_changed.connect(lambda t: store.set(path, t, scope))
    return w


def toggle_row(store, key, path, sub_key=None, scope="s"):
    return form_row(key, sub_key, bind_toggle(store, Toggle(), path, scope))


def num_row(store, key, path, sub_key=None, unit_key=None, lo=0, hi=10**9, step=1, width=120, scope="s", icon_name=None):
    return form_row(key, sub_key, bind_num(store, NumField(lo, hi, step, width), path, scope), unit_key, icon_name=icon_name)


def float_row(store, key, path, sub_key=None, unit_key=None, lo=0.0, hi=10**4, step=0.5, width=100, scope="s"):
    return form_row(key, sub_key, bind_num(store, FloatField(lo, hi, step, width), path, scope), unit_key)


def combo_row(store, key, path, items, sub_key=None, width=260, scope="s"):
    return form_row(key, sub_key, bind_combo(store, Combo(items, width), path, scope))


class TimeField(QLineEdit):
    """HH:MM field. (QTimeEdit swaps the hour and minute sections in right-to-left layouts.)"""
    time_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setInputMask("99:99")
        self.setFixedWidth(100)
        self.setAlignment(Qt.AlignCenter)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setStyleSheet("font-family: 'JetBrains Mono';")
        self.editingFinished.connect(self._commit)
        self._last = "00:00"

    def set_text_time(self, v):
        self._last = self._norm(v) or "00:00"
        self.setText(self._last)

    @staticmethod
    def _norm(v):
        try:
            h, m = str(v or "").replace(" ", "0").split(":")[:2]
            h, m = int(h or 0), int(m or 0)
        except ValueError:
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59): return None
        return f"{h:02d}:{m:02d}"

    def _commit(self):
        v = self._norm(self.text())
        if v is None:
            self.setText(self._last)
            return
        self.setText(v)
        if v != self._last:
            self._last = v
            self.time_changed.emit(v)


def time_edit():
    return TimeField()



# ====================================================================== painted box (no style-sheet cascade)
class Box(QFrame):
    """Rounded panel painted directly (style sheets on a QFrame would also style the QLabels inside it)."""

    def __init__(self, bg=None, border=None, radius=16, top=None, parent=None):
        super().__init__(parent)
        self.bg = QColor(bg or TOKENS["glass2"])
        self.border = border or TOKENS["border"]
        self.radius = radius
        self.top = top
        self.hover = False

    def set_border(self, c):
        self.border = c
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, self.radius, self.radius)
        p.fillPath(path, self.bg)
        bc = QColor(self.border) if not str(self.border).startswith("rgba") else _rgba(self.border)
        p.setPen(QPen(bc, 1))
        p.drawPath(path)
        if self.top:
            p.save()
            p.setClipPath(path)
            p.fillRect(QRectF(r.left(), r.top(), r.width(), 3), QColor(self.top))
            p.restore()
        p.end()


def _rgba(s):
    nums = s[s.index("(") + 1:s.index(")")].split(",")
    r, g, b = (int(x) for x in nums[:3])
    a = float(nums[3]) if len(nums) > 3 else 1.0
    c = QColor(r, g, b)
    c.setAlphaF(a)
    return c
