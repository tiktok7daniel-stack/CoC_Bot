"""
Shared screen plumbing: every screen gets the app context (api, store, poller, toast/banner), a
scrollable body, optional underline sub-tabs, and a search index for the Ctrl+K palette built from
the labels it shows.
"""
from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (QFrame, QGraphicsColorizeEffect, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..i18n import tr
from ..theme import TOKENS, color
from ..widgets.controls import SegTabs


class Ctx:
    """What a screen needs from the app."""

    def __init__(self, api, store, poller, window):
        self.api, self.store, self.poller, self.window = api, store, poller, window

    def toast(self, text, kind="info"):
        self.window.toast.show_msg(text, kind)

    def banner(self, text, kind="ok", icon_name="check"):
        self.window.banner.show_msg(text, kind, icon_name)

    @property
    def account(self):
        return self.store.account


def scroll(widget):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sa.setWidget(widget)
    return sa


def page(spacing=14):
    """(scroll area, inner vertical layout) for one page of content."""
    inner = QWidget()
    v = QVBoxLayout(inner)
    v.setContentsMargins(4, 4, 10, 14)
    v.setSpacing(spacing)
    return scroll(inner), v


def grid(cols=2, spacing=14):
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(spacing)
    g.setVerticalSpacing(spacing)
    for c in range(cols): g.setColumnStretch(c, 1)
    return w, g


class Screen(QWidget):
    key = ""
    title_key = ""
    icon_name = "sliders"

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.api, self.store, self.poller = ctx.api, ctx.store, ctx.poller
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(12)
        self.tabs = None
        self.stack = None
        self.sub_pages = {}

    # ---------------------------------------------------------------- sub tabs
    def make_tabs(self, items):
        """items: [(key, text key, icon)] -> returns {key: inner layout} of scrollable pages."""
        self.tabs = SegTabs(items)
        self.stack = QStackedWidget()
        layouts = {}
        for key, _tk, _ic in items:
            sa, v = page()
            sa.setProperty("subkey", key)
            self.sub_pages[key] = sa
            self.stack.addWidget(sa)
            layouts[key] = v
        self.tabs.changed.connect(self._show_sub)
        self.root.addWidget(self.tabs)
        self.root.addWidget(self.stack, 1)
        self.tabs.select(items[0][0])
        return layouts

    def _show_sub(self, key):
        if key in self.sub_pages: self.stack.setCurrentWidget(self.sub_pages[key])
        self.on_sub(key)

    def select_sub(self, key):
        if self.tabs and key in self.sub_pages: self.tabs.select(key)

    def on_sub(self, key):
        pass

    # ---------------------------------------------------------------- lifecycle
    def on_show(self):
        """Called whenever the screen becomes visible."""

    # ---------------------------------------------------------------- search index
    def search_entries(self):
        out = []
        where = tr(self.title_key)
        for lb in self.findChildren(QLabel):
            text = lb.text().strip()
            if not text or len(text) > 90 or "<" in text or lb.property("role") in ("sub", "dim", "num", "numsm", "kpi"): continue
            sub = None
            p = lb.parentWidget()
            while p is not None and p is not self:
                if p.property("subkey"): sub = p.property("subkey"); break
                p = p.parentWidget()
            sub_text = ""
            if sub and self.tabs: sub_text = self.tabs.buttons[sub].text()
            out.append({"text": text, "where": where + (f"  ›  {sub_text}" if sub_text else ""), "screen": self.key,
                        "sub": sub, "widget": lb, "icon": self.icon_name})
        return out

    def flash(self, widget):
        """Briefly highlight a widget the palette jumped to."""
        if widget is None: return
        p = widget.parentWidget()
        while p is not None and not isinstance(p, QScrollArea): p = p.parentWidget()
        if isinstance(p, QScrollArea): p.ensureWidgetVisible(widget, 40, 120)
        eff = QGraphicsColorizeEffect(widget)
        eff.setColor(color("fuchsia"))
        widget.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"strength", widget)
        anim.setDuration(1600)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.finished.connect(lambda: widget.setGraphicsEffect(None))
        anim.start()
        widget._flash_anim = anim
