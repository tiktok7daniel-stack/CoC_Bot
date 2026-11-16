"""
Charts drawn with QPainter: glowing grouped bar chart (loot per hour / per attack), a segmented ring
gauge (efficiency, CPU, RAM) and a slim sparkline. No chart library needed.
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import TOKENS, mono_font, ui_font


def _short(n):
    n = float(n or 0)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div: return f"{n / div:.1f}{suf}".replace(".0", "")
    return f"{int(n)}"


class NeonBarChart(QWidget):
    """Groups of bars (e.g. per category: gold / elixir / dark) with a soft glow under every bar."""

    def __init__(self, series_colors=("gold", "elixir", "dark"), height=230):
        super().__init__()
        self.colors = [QColor(TOKENS[c]) for c in series_colors]
        self.groups = []          # [(label, [v1, v2, v3])]
        self.series_scale = None  # optional per-series max (dark elixir is ~100x smaller than gold)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.empty_text = "—"

    def set_data(self, groups, per_series_scale=True):
        self.groups = groups or []
        if per_series_scale and self.groups:
            n = len(self.groups[0][1])
            self.series_scale = [max(1.0, max(float(g[1][i] or 0) for g in self.groups)) for i in range(n)]
        else:
            m = max([1.0] + [float(v or 0) for _, vals in self.groups for v in vals])
            self.series_scale = [m] * (len(self.groups[0][1]) if self.groups else 0)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(8, 10, -8, -28)
        # grid
        p.setPen(QPen(QColor(TOKENS["border_solid"]), 1, Qt.DashLine))
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if not self.groups:
            p.setPen(QColor(TOKENS["dim"]))
            p.setFont(ui_font(10))
            p.drawText(r, Qt.AlignCenter, self.empty_text)
            p.end()
            return
        n_groups = len(self.groups)
        n_series = len(self.groups[0][1])
        gw = r.width() / n_groups
        bw = min(26.0, gw * 0.7 / max(1, n_series))
        rtl = self.layoutDirection() == Qt.RightToLeft
        for gi, (lab, vals) in enumerate(self.groups):
            idx = n_groups - 1 - gi if rtl else gi
            gx = r.left() + gw * idx + (gw - bw * n_series - 4 * (n_series - 1)) / 2
            for si, v in enumerate(vals):
                frac = min(1.0, float(v or 0) / (self.series_scale[si] or 1))
                h = max(2.0, r.height() * frac)
                x = gx + si * (bw + 4)
                bar = QRectF(x, r.bottom() - h, bw, h)
                c = self.colors[si % len(self.colors)]
                # glow
                for k, a in ((4, 26),):
                    gc = QColor(c)
                    gc.setAlpha(a)
                    p.setPen(Qt.NoPen)
                    p.setBrush(gc)
                    p.drawRoundedRect(bar.adjusted(-k / 2, -k / 2, k / 2, 0), 6, 6)
                g = QLinearGradient(bar.topLeft(), bar.bottomLeft())
                top = QColor(c).lighter(135)
                g.setColorAt(0, top)
                g.setColorAt(1, c.darker(140))
                p.setBrush(QBrush(g))
                p.drawRoundedRect(bar, 5, 5)
                if h > 22:
                    p.setPen(QColor(255, 255, 255, 210))
                    p.setFont(mono_font(7))
                    p.save()
                    p.translate(bar.center().x(), bar.top() + 6)
                    p.rotate(-90)
                    p.drawText(QRectF(-h + 10, -bw / 2, h - 12, bw), Qt.AlignVCenter | Qt.AlignLeft, _short(v))
                    p.restore()
            p.setPen(QColor(TOKENS["muted"]))
            p.setFont(ui_font(8.5))
            p.drawText(QRectF(r.left() + gw * idx, r.bottom() + 4, gw, 20), Qt.AlignCenter, lab)
        p.end()


class RingGauge(QWidget):
    """Segmented circular gauge with a gradient arc and a centered value."""

    def __init__(self, size=140, segments=36, colors=("violet", "fuchsia"), suffix="%"):
        super().__init__()
        self.setFixedSize(size, size)
        self.value = 0.0
        self.text = ""
        self.caption = ""
        self.segments = segments
        self.c1, self.c2 = QColor(TOKENS[colors[0]]), QColor(TOKENS[colors[1]])
        self.suffix = suffix

    def set_value(self, frac, text=None, caption=None):
        self.value = max(0.0, min(1.0, float(frac or 0)))
        self.text = text if text is not None else f"{int(round(self.value * 100))}{self.suffix}"
        if caption is not None: self.caption = caption
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        r_out, r_in = s / 2 - 6, s / 2 - 18
        lit = int(round(self.segments * self.value))
        gap = 3.0
        for i in range(self.segments):
            a0 = 90 - (360 / self.segments) * i
            span = -(360 / self.segments - gap)
            t = i / max(1, self.segments - 1)
            c = QColor(
                int(self.c1.red() + (self.c2.red() - self.c1.red()) * t),
                int(self.c1.green() + (self.c2.green() - self.c1.green()) * t),
                int(self.c1.blue() + (self.c2.blue() - self.c1.blue()) * t)) if i < lit else QColor(TOKENS["glass3"])
            path = QPainterPath()
            outer = QRectF(cx - r_out, cy - r_out, 2 * r_out, 2 * r_out)
            inner = QRectF(cx - r_in, cy - r_in, 2 * r_in, 2 * r_in)
            path.arcMoveTo(outer, a0)
            path.arcTo(outer, a0, span)
            path.arcTo(inner, a0 + span, -span)
            path.closeSubpath()
            if i < lit:
                glow = QColor(c)
                glow.setAlpha(70)
                p.setPen(QPen(glow, 4))
                p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawPath(path)
        p.setPen(QColor(TOKENS["text"]))
        p.setFont(mono_font(max(10, s / 9), QFont.Bold))
        p.drawText(QRectF(0, cy - s / 7, self.width(), s / 5), Qt.AlignCenter, self.text)
        if self.caption:
            p.setPen(QColor(TOKENS["muted"]))
            p.setFont(ui_font(max(7.5, s / 17)))
            p.drawText(QRectF(0, cy + s / 14, self.width(), s / 6), Qt.AlignCenter, self.caption)
        p.end()


class Sparkline(QWidget):
    """Tiny line of recent values (CPU / RAM history on the telemetry tiles)."""

    def __init__(self, tint="violet", height=26, keep=40):
        super().__init__()
        self.setFixedHeight(height)
        self.values = []
        self.keep = keep
        self.tint = QColor(TOKENS[tint])

    def push(self, v):
        try: v = float(v)
        except (TypeError, ValueError): return
        self.values.append(v)
        self.values = self.values[-self.keep:]
        self.update()

    def paintEvent(self, e):
        if len(self.values) < 2: return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        hi = max(100.0, max(self.values))
        step = w / (self.keep - 1)
        start = w - step * (len(self.values) - 1)
        path = QPainterPath()
        for i, v in enumerate(self.values):
            pt = QPointF(start + i * step, h - 2 - (h - 4) * v / hi)
            if i == 0: path.moveTo(pt)
            else: path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(QPointF(w, h))
        fill.lineTo(QPointF(start, h))
        fill.closeSubpath()
        g = QLinearGradient(0, 0, 0, h)
        c = QColor(self.tint)
        c.setAlpha(90)
        g.setColorAt(0, c)
        c2 = QColor(self.tint)
        c2.setAlpha(0)
        g.setColorAt(1, c2)
        p.fillPath(fill, QBrush(g))
        p.setPen(QPen(self.tint, 1.6))
        p.drawPath(path)
        p.end()


class MeterBar(QWidget):
    """Horizontal glowing meter (0..1) used for storage fill and session progress."""

    def __init__(self, tint="violet", height=8):
        super().__init__()
        self.setFixedHeight(height)
        self.frac = 0.0
        self.tint = QColor(TOKENS[tint])

    def set_value(self, frac):
        self.frac = max(0.0, min(1.0, float(frac or 0)))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TOKENS["glass3"]))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self.frac > 0:
            w = r.width() * self.frac
            fr = QRectF(r.right() - w, r.top(), w, r.height()) if self.layoutDirection() == Qt.RightToLeft else QRectF(r.left(), r.top(), w, r.height())
            g = QLinearGradient(fr.topLeft(), fr.topRight())
            g.setColorAt(0, self.tint.darker(130))
            g.setColorAt(1, self.tint.lighter(130))
            p.setBrush(QBrush(g))
            p.drawRoundedRect(fr, r.height() / 2, r.height() / 2)
        p.end()


class AreaChart(QWidget):
    """Smooth multi-series area chart with axis labels and a hover crosshair + value card.
    set_data(labels, {series_key: [values]}) ; series drawn on their own scale when scales='own'."""

    def __init__(self, series=(("gold", "gold"), ("elixir", "elixir"), ("dark", "dark")), height=260, scales="own"):
        super().__init__()
        self.series = list(series)          # [(key, token color)]
        self.labels, self.data = [], {}
        self.names = {}
        self.scales = scales
        self.hover = None
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.empty_text = "—"
        self.fmt = _short

    def set_data(self, labels, data, names=None):
        self.labels, self.data = list(labels), dict(data)
        if names: self.names = names
        self.update()

    def _area(self):
        return QRectF(self.rect()).adjusted(52, 14, -14, -30)

    def _x(self, r, i, n):
        rtl = self.layoutDirection() == Qt.RightToLeft
        f = 0.5 if n == 1 else i / (n - 1)
        if rtl: f = 1 - f
        return r.left() + r.width() * f

    def mouseMoveEvent(self, e):
        n = len(self.labels)
        if not n: return
        r = self._area()
        best = min(range(n), key=lambda i: abs(self._x(r, i, n) - e.position().x()))
        if best != self.hover:
            self.hover = best
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._area()
        n = len(self.labels)
        p.setFont(mono_font(7.5))
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.setPen(QPen(QColor(255, 255, 255, 14), 1))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        if not n or not any(any(v for v in vals) for vals in self.data.values()):
            p.setPen(QColor(TOKENS["dim"]))
            p.setFont(ui_font(10))
            p.drawText(r, Qt.AlignCenter, self.empty_text)
            p.end()
            return
        first_key = self.series[0][0]
        top_all = max([1.0] + [float(v or 0) for k, _c in self.series for v in self.data.get(k, [])])
        for k, tok in reversed(self.series):
            vals = self.data.get(k, [])
            if not vals: continue
            top = max(1.0, max(float(v or 0) for v in vals)) if self.scales == "own" else top_all
            pts = [QPointF(self._x(r, i, n), r.bottom() - r.height() * float(v or 0) / top * 0.92) for i, v in enumerate(vals)]
            path = QPainterPath(pts[0])
            for a, b in zip(pts, pts[1:]): # smooth curve through the points
                mx = (a.x() + b.x()) / 2
                path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
            c = QColor(TOKENS[tok])
            fill = QPainterPath(path)
            fill.lineTo(QPointF(pts[-1].x(), r.bottom()))
            fill.lineTo(QPointF(pts[0].x(), r.bottom()))
            fill.closeSubpath()
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            c1 = QColor(c); c1.setAlpha(70 if k == first_key else 34)
            c2 = QColor(c); c2.setAlpha(0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(fill, QBrush(g))
            p.setPen(QPen(c, 2.2 if k == first_key else 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if len(pts) <= 31:
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                for pt in pts: p.drawEllipse(pt, 2.2, 2.2)
            if k == first_key: # y labels for the main series
                p.setPen(QColor(TOKENS["dim"]))
                for i in range(5):
                    y = r.top() + r.height() * i / 4
                    val = top / 0.92 * (1 - i / 4)
                    p.drawText(QRectF(0, y - 8, 46, 16), Qt.AlignRight | Qt.AlignVCenter, self.fmt(val))
        # x labels (thinned)
        p.setPen(QColor(TOKENS["dim"]))
        p.setFont(ui_font(8))
        step = max(1, int(n / 10 + 0.999))
        for i, lab in enumerate(self.labels):
            if i % step and i != n - 1: continue
            x = self._x(r, i, n)
            p.drawText(QRectF(x - 40, r.bottom() + 6, 80, 18), Qt.AlignCenter, lab)
        # hover
        if self.hover is not None and self.hover < n:
            i = self.hover
            x = self._x(r, i, n)
            p.setPen(QPen(QColor(245, 183, 64, 120), 1, Qt.DashLine))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            lines = [(self.labels[i], None)] + [(f"{self.names.get(k, k)}:  {fmt_full(self.data.get(k, [0] * n)[i])}", tok)
                                               for k, tok in self.series if self.data.get(k)]
            p.setFont(ui_font(9, 600))
            fm = p.fontMetrics()
            bw = max(fm.horizontalAdvance(t) for t, _ in lines) + 28
            bh = 10 + 20 * len(lines)
            bx = x + 12 if x + 12 + bw < r.right() else x - 12 - bw
            box = QRectF(bx, r.top() + 4, bw, bh)
            p.setPen(QPen(QColor(255, 255, 255, 30), 1))
            p.setBrush(QColor(20, 20, 27, 245))
            p.drawRoundedRect(box, 9, 9)
            for j, (t, tok) in enumerate(lines):
                yy = box.top() + 6 + 20 * j
                if tok:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(TOKENS[tok]))
                    p.drawEllipse(QPointF(box.left() + 12, yy + 10), 4, 4)
                p.setPen(QColor(TOKENS["text"] if tok else TOKENS["accent_hi"]))
                p.drawText(QRectF(box.left() + 22, yy, bw - 26, 20), Qt.AlignVCenter | Qt.AlignLeft, t)
        p.end()


def fmt_full(n):
    try: return f"{int(n or 0):,}"
    except (TypeError, ValueError): return "—"
