"""
Screenshot canvas for teaching the bot: wheel to zoom, right/middle drag (or Space + drag) to pan,
left drag to draw a selection box, corner handles to resize it, drag inside it to move it.
Emits the cursor position in screenshot pixels and the selection as fractions (x1, y1, x2, y2).
"""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView)

from ..theme import TOKENS, mono_font

HANDLE = 10


class SelectionItem(QGraphicsRectItem):
    def __init__(self, rect, canvas):
        super().__init__(rect)
        self.canvas = canvas
        pen = QPen(QColor(TOKENS["gold"]), 2)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QColor(251, 191, 36, 40))
        self.setZValue(10)

    def handles(self):
        r = self.rect()
        s = HANDLE / self.canvas.transform().m11()
        return {k: QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s) for k, pt in
                (("tl", r.topLeft()), ("tr", r.topRight()), ("bl", r.bottomLeft()), ("br", r.bottomRight()))}

    def paint(self, p, opt, w=None):
        super().paint(p, opt, w)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TOKENS["gold"]))
        for h in self.handles().values(): p.drawRect(h)


class RoiCanvas(QGraphicsView):
    cursor_moved = Signal(int, int)
    selection_changed = Signal(object)   # (x1, y1, x2, y2) fractions or None

    def __init__(self):
        super().__init__()
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#05040A"))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setLayoutDirection(Qt.LeftToRight)   # screenshots are never mirrored
        self.setStyleSheet(f"QGraphicsView {{ border: 1px solid {TOKENS['border']}; border-radius: 12px; }}")
        self.pix = None
        self.sel = None
        self.saved_items = []
        self._mode = None
        self._start = None
        self._pan_from = None
        self._space = False
        self.cross_h = self.cross_v = None
        self.empty = QGraphicsSimpleTextItem("")
        self.empty.setBrush(QColor(TOKENS["muted"]))
        self.scene_.addItem(self.empty)

    # ---------------------------------------------------------------- image
    def set_image(self, data_or_pixmap):
        pm = data_or_pixmap if isinstance(data_or_pixmap, QPixmap) else QPixmap()
        if not isinstance(data_or_pixmap, QPixmap) and data_or_pixmap: pm.loadFromData(data_or_pixmap)
        self.scene_.clear()
        self.sel, self.saved_items, self.cross_h, self.cross_v = None, [], None, None
        self.empty = None
        if pm.isNull():
            self.pix = None
            return False
        self.pix = QGraphicsPixmapItem(pm)
        self.pix.setTransformationMode(Qt.SmoothTransformation)
        self.scene_.addItem(self.pix)
        self.scene_.setSceneRect(QRectF(pm.rect()))
        pen = QPen(QColor(168, 85, 247, 150), 1, Qt.DashLine)
        pen.setCosmetic(True)
        self.cross_h = self.scene_.addLine(0, 0, pm.width(), 0, pen)
        self.cross_v = self.scene_.addLine(0, 0, 0, pm.height(), pen)
        for c in (self.cross_h, self.cross_v): c.setZValue(5)
        self.fit()
        self.selection_changed.emit(None)
        return True

    def show_message(self, text):
        self.scene_.clear()
        self.pix = self.sel = None
        self.cross_h = self.cross_v = None
        t = self.scene_.addSimpleText(text)
        t.setBrush(QColor(TOKENS["muted"]))
        t.setFont(mono_font(11))
        self.scene_.setSceneRect(t.boundingRect().adjusted(-40, -40, 40, 40))
        self.resetTransform()

    def show_saved(self, frac_rect, text=""):
        """Dashed green box of an already-learned item."""
        if not self.pix or not frac_rect: return
        w, h = self.pix.pixmap().width(), self.pix.pixmap().height()
        x1, y1, x2, y2 = frac_rect
        pen = QPen(QColor(TOKENS["ok"]), 2, Qt.DashLine)
        pen.setCosmetic(True)
        it = self.scene_.addRect(QRectF(x1 * w, y1 * h, (x2 - x1) * w, (y2 - y1) * h), pen, QBrush(QColor(16, 185, 129, 30)))
        it.setZValue(8)
        self.saved_items.append(it)

    def fit(self):
        if self.pix:
            self.resetTransform()
            self.fitInView(self.pix, Qt.KeepAspectRatio)

    def zoom(self, f):
        cur = self.transform().m11()
        if 0.05 < cur * f < 12: self.scale(f, f)

    # ---------------------------------------------------------------- selection
    def selection(self):
        if not self.sel or not self.pix: return None
        r = self.sel.rect().normalized()
        w, h = self.pix.pixmap().width(), self.pix.pixmap().height()
        return (max(0.0, r.left() / w), max(0.0, r.top() / h), min(1.0, r.right() / w), min(1.0, r.bottom() / h))

    def clear_selection(self):
        if self.sel:
            self.scene_.removeItem(self.sel)
            self.sel = None
        self.selection_changed.emit(None)

    def _clamp(self, pt):
        r = self.scene_.sceneRect()
        return QPointF(min(max(pt.x(), r.left()), r.right()), min(max(pt.y(), r.top()), r.bottom()))

    # ---------------------------------------------------------------- events
    def wheelEvent(self, e):
        if not self.pix: return
        self.zoom(1.18 if e.angleDelta().y() > 0 else 1 / 1.18)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space: self._space = True
        elif e.key() in (Qt.Key_Delete, Qt.Key_Escape): self.clear_selection()
        elif e.key() == Qt.Key_F: self.fit()
        else: super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space: self._space = False
        else: super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        if not self.pix: return
        if e.button() in (Qt.RightButton, Qt.MiddleButton) or (e.button() == Qt.LeftButton and self._space):
            self._mode, self._pan_from = "pan", e.position()
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton: return
        pt = self._clamp(self.mapToScene(e.position().toPoint()))
        if self.sel:
            for k, h in self.sel.handles().items():
                if h.contains(pt):
                    self._mode, self._start = k, pt
                    return
            if self.sel.rect().contains(pt):
                self._mode, self._start = "move", pt
                self._orig = QRectF(self.sel.rect())
                return
            self.scene_.removeItem(self.sel)
        self.sel = SelectionItem(QRectF(pt, pt), self)
        self.scene_.addItem(self.sel)
        self._mode, self._start = "draw", pt

    def mouseMoveEvent(self, e):
        if self.pix:
            pt = self._clamp(self.mapToScene(e.position().toPoint()))
            self.cursor_moved.emit(int(pt.x()), int(pt.y()))
            if self.cross_h:
                w, h = self.pix.pixmap().width(), self.pix.pixmap().height()
                self.cross_h.setLine(0, pt.y(), w, pt.y())
                self.cross_v.setLine(pt.x(), 0, pt.x(), h)
        else:
            return
        if self._mode == "pan":
            d = e.position() - self._pan_from
            self._pan_from = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
        elif self._mode == "draw":
            self.sel.setRect(QRectF(self._start, pt).normalized())
        elif self._mode == "move":
            d = pt - self._start
            r = self._orig.translated(d)
            sr = self.scene_.sceneRect()
            r.moveLeft(min(max(r.left(), sr.left()), sr.right() - r.width()))
            r.moveTop(min(max(r.top(), sr.top()), sr.bottom() - r.height()))
            self.sel.setRect(r)
        elif self._mode in ("tl", "tr", "bl", "br"):
            r = QRectF(self.sel.rect())
            if "l" in self._mode: r.setLeft(pt.x())
            if "r" in self._mode: r.setRight(pt.x())
            if "t" in self._mode: r.setTop(pt.y())
            if "b" in self._mode: r.setBottom(pt.y())
            self.sel.setRect(r.normalized())
        elif self.sel:
            over = any(h.contains(pt) for h in self.sel.handles().values())
            self.setCursor(Qt.SizeFDiagCursor if over else Qt.SizeAllCursor if self.sel.rect().contains(pt) else Qt.CrossCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def mouseReleaseEvent(self, e):
        if self._mode == "pan": self.setCursor(Qt.CrossCursor)
        if self._mode and self._mode != "pan" and self.sel:
            r = self.sel.rect()
            if r.width() < 4 or r.height() < 4:
                self.scene_.removeItem(self.sel)
                self.sel = None
            self.selection_changed.emit(self.selection())
        self._mode = None
