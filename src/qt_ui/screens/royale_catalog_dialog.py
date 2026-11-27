"""Search the catalogue and save a verified-copy request for one account."""
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

from ..i18n import tr
from ..theme import TOKENS, ui_font
from ..widgets.controls import GlassCard, IconButton, label

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
PAGE_SIZE = 24


def _slug(name):
    return "".join(c for c in name.casefold() if c.isalnum())


class RoyaleCatalogDialog(QDialog):
    def __init__(self, parent, api, account):
        super().__init__(parent)
        self.setObjectName("RoyaleCatalogDialog")
        self.setStyleSheet(f"QDialog#RoyaleCatalogDialog {{ background: {TOKENS['void']}; }}")
        self.setWindowTitle(tr("rc_title"))
        self.setMinimumSize(570, 490)
        self.resize(850, 590)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.api = api
        self.selection_path = "/api/royale/deck-selection/" + quote(account, safe="")
        self.offset, self.total, self.sequence = 0, 0, 0
        self.rows, self.chosen, self.saved = [], None, {}
        self.saving = False
        self.copy_message = ""
        self.images = QNetworkAccessManager(self)
        self.downloaded = {}
        self.art = {_slug(p.stem): p for p in (ROOT / "assets" / "royale" / "cards").glob("*.jpg")}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)
        header = QLabel(tr("rc_title"))
        header.setFont(ui_font(18, QFont.Bold))
        outer.addWidget(header)
        self.status = label(role="sub", wrap=True)
        self.status.setAccessibleName(tr("rc_state"))
        outer.addWidget(self.status)

        body = QHBoxLayout()
        body.setSpacing(12)
        catalog = GlassCard(None, None, None, pad=12)
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("rc_search"))
        self.query.setAccessibleName(tr("rc_search"))
        catalog.add(self.query)
        self.list = QListWidget()
        self.list.setAccessibleName(tr("rc_title"))
        self.list.setMinimumHeight(205)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        catalog.add(self.list, 1)
        pages = QHBoxLayout()
        self.prev = IconButton("chevron_left", "rc_prev")
        self.next = IconButton("chevron_right", "rc_next")
        self.count = label(role="sub")
        pages.addWidget(self.prev)
        pages.addWidget(self.count, 1, Qt.AlignCenter)
        pages.addWidget(self.next)
        catalog.add(pages)
        body.addWidget(catalog, 5)

        detail = GlassCard(None, None, None, pad=12)
        self.name = label(role="title", wrap=True)
        self.name.setFont(ui_font(13, QFont.Bold))
        self.metrics = label(role="sub", wrap=True)
        self.note = label(role="dim", wrap=True)
        for widget in (self.name, self.metrics):
            detail.add(widget)
        card_strip = QWidget()
        cards = QGridLayout(card_strip)
        cards.setContentsMargins(0, 2, 0, 2)
        cards.setSpacing(5)
        self.pictures = []
        for i in range(8):
            tile = QWidget()
            col = QVBoxLayout(tile)
            col.setContentsMargins(1, 1, 1, 1)
            col.setSpacing(3)
            art = QLabel("—")
            art.setAlignment(Qt.AlignCenter)
            art.setFixedSize(43, 52)
            art.setStyleSheet(f"background: {TOKENS['void2']}; border-radius: 6px;")
            caption = label(role="dim", wrap=True)
            caption.setAlignment(Qt.AlignCenter)
            col.addWidget(art, 0, Qt.AlignHCenter)
            col.addWidget(caption)
            cards.addWidget(tile, i // 4, i % 4)
            self.pictures.append((art, caption))
        detail.add(card_strip)
        detail.add(self.note)
        slot_row = QHBoxLayout()
        slot_row.addWidget(label(key="rc_slot", role="sub"))
        self.slot = QComboBox()
        self.slot.setAccessibleName(tr("rc_slot"))
        self.slot.addItem(tr("rc_slot_current"), 0)
        for i in range(1, 11):
            self.slot.addItem(str(i), i)
        slot_row.addWidget(self.slot, 1)
        detail.add(slot_row)
        self.save = IconButton("check", "rc_select", kind="go")
        self.clear = IconButton("close", "rc_clear")
        detail.add(self.save)
        detail.add(self.clear)
        body.addWidget(detail, 6)
        outer.addLayout(body, 1)

        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(250)
        self.delay.timeout.connect(lambda: self.load(0))
        self.query.textChanged.connect(lambda: self.delay.start())
        self.prev.clicked.connect(lambda: self.load(max(0, self.offset - PAGE_SIZE)))
        self.next.clicked.connect(lambda: self.load(self.offset + PAGE_SIZE))
        self.list.currentRowChanged.connect(self.render)
        self.save.clicked.connect(self.select_deck)
        self.clear.clicked.connect(lambda: self.persist(""))
        self.render(-1)
        self.load(0)
        self.refresh_selection(initial=True)
        self.poll = QTimer(self)
        self.poll.timeout.connect(self.refresh_selection)
        self.poll.start(2500)

    def load(self, offset):
        self.sequence += 1
        sequence = self.sequence
        self.count.setText(tr("rc_loading"))
        self.prev.setEnabled(False)
        self.next.setEnabled(False)
        path = "/api/royale/deck-catalog?" + urlencode({"q": self.query.text(), "offset": offset, "limit": PAGE_SIZE})

        def done(result):
            if sequence != self.sequence:
                return
            self.list.clear()
            if not isinstance(result, dict) or "items" not in result:
                self.rows = []
                self.render(-1)
                self.count.setText(tr("rc_unavailable"))
                return
            self.rows = result["items"]
            self.offset, self.total = result["offset"], result["total"]
            for entry in self.rows:
                item = QListWidgetItem(entry["name"])
                item.setToolTip(entry["name"])
                self.list.addItem(item)
            self.prev.setEnabled(self.offset > 0)
            self.next.setEnabled(self.offset + len(self.rows) < self.total)
            self.count.setText(f"{self.offset + 1}–{self.offset + len(self.rows)} / {self.total:,}"
                               if self.rows else tr("rc_empty"))
            loc = next((i for i, d in enumerate(self.rows) if d["id"] == self.saved.get("id")), 0)
            self.list.setCurrentRow(loc if self.rows else -1)
        self.api.get(path, done)

    def render(self, row):
        self.chosen = self.rows[row] if 0 <= row < len(self.rows) else None
        entry = self.chosen or {}
        self.name.setText(entry.get("name") or tr("rc_choose"))
        names = entry.get("cards") or []
        images = entry.get("image_urls") or {}
        win, games = entry.get("win_rate"), entry.get("games")
        source = f"RoyaleAPI · {entry['captured_on']}" if entry.get("captured_on") else "IL_Replay"
        self.metrics.setText(f"{win:.1%} · {games:,} {tr('rc_games')} · {source}"
                             if win is not None and games is not None else "")
        note = ("rc_unsupported_cards" if entry.get("unsupported_cards")
                else "rc_arena_vision_unverified" if entry.get("unverified_arena_cards")
                else "rc_forms_known" if entry.get("forms_known") else "rc_forms_unknown")
        self.note.setText(tr(note) if entry else "")
        if entry.get("unsupported_cards"):
            self.note.setText(self.note.text() + " " + ", ".join(entry["unsupported_cards"]))
        elif entry.get("unverified_arena_cards"):
            self.note.setText(self.note.text() + " " + ", ".join(entry["unverified_arena_cards"]))
        for i, (picture, caption) in enumerate(self.pictures):
            key = names[i] if i < len(names) else ""
            caption.setText(key.replace("-", " ").title())
            picture.setToolTip(caption.text())
            picture.setText("—")
            image = self.art.get(_slug(key))
            for suffix in ("-ev1", "-ev2", "-hero"):
                if not image and key.endswith(suffix):
                    image = self.art.get(_slug(key[:-len(suffix)]))
            if image:
                self.set_image(picture, QPixmap(str(image)))
            url = QUrl(images.get(key, ""))
            picture.setProperty("image_url", url.toString())
            if url.toString() in self.downloaded:
                self.set_image(picture, self.downloaded[url.toString()])
            elif url.scheme() == "https" and url.host() == "api-assets.clashroyale.com":
                reply = self.images.get(QNetworkRequest(url))
                reply.finished.connect(lambda r=reply, p=picture, u=url: self.receive_image(r, p, u))
        self.update_buttons()

    @staticmethod
    def set_image(label_widget, pixmap):
        if not pixmap.isNull():
            label_widget.setPixmap(pixmap.scaled(label_widget.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def receive_image(self, reply, picture, url):
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self.downloaded[url.toString()] = pixmap
                if picture.property("image_url") == url.toString():
                    self.set_image(picture, pixmap)
        reply.deleteLater()

    def update_buttons(self):
        self.save.setEnabled(bool(not self.saving and self.chosen and self.chosen.get("copy_url")))
        self.clear.setEnabled(bool(not self.saving and self.saved.get("id")))

    def refresh_selection(self, initial=False):
        def done(result):
            if self.saving or not isinstance(result, dict) or "selection" not in result:
                return
            self.saved = result["selection"] or {}
            if initial:
                self.slot.setCurrentIndex(self.slot.findData(self.saved.get("slot", 0)))
                idx = next((i for i, deck in enumerate(self.rows) if deck["id"] == self.saved.get("id")), -1)
                if idx >= 0:
                    self.list.setCurrentRow(idx)
            state = result.get("status") or {}
            value = state.get("state", "none")
            key = f"rc_{state.get('reason')}" if value == "blocked" else f"rc_{value}"
            message = tr(key)
            message = message if message != key else tr("rc_copy_failed")
            if value == "pending" and self.copy_message:
                message = self.copy_message
            self.status.setText(f"{result['deck_name']}\n{message}" if result.get("deck_name") else message)
            self.update_buttons()
        self.api.get(self.selection_path, done)

    def select_deck(self):
        if self.chosen:
            self.persist(self.chosen["id"])

    def persist(self, deck_id):
        self.saving = True
        self.copy_message = ""
        self.update_buttons()
        def done(result):
            self.saving = False
            if isinstance(result, dict) and result.get("ok"):
                self.saved = result["selection"]
                if deck_id:
                    self.copy_message = tr("rc_opened_copy" if result.get("copy_opened") else "rc_failed_open")
                self.refresh_selection()
            else:
                key = "rc_" + str((result or {}).get("error", "unavailable"))
                message = tr(key)
                self.status.setText(message if message != key else tr("rc_unavailable"))
            self.update_buttons()
        self.api.post(self.selection_path, {"id": deck_id, "slot": self.slot.currentData() or 0, "open_copy": bool(deck_id)}, done, timeout=45)
