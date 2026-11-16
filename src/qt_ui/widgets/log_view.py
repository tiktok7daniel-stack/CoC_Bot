"""
Structured log viewer: parses the bot's log lines (time | level | message + traceback lines),
translates messages to Arabic, colors them by level with SVG status badges, filters by text / level,
and can show the raw English text. Used full-size on the Log screen and as a mini feed on the dashboard.
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QTextBrowser

from .. import icons
from ..i18n import translate_log, tr
from ..theme import TOKENS

LINE = re.compile(r"^(?:\d{4}-\d\d-\d\d )?(\d\d:\d\d:\d\d)\s*\|\s*(\w+)\s*\|\s*(.*)$")
LEVEL_STYLE = {
    "INFO": ("info", "#38BDF8", "lv_info"), "SUCCESS": ("ok", "#10B981", "lv_info"),
    "WARNING": ("warn", "#F59E0B", "lv_warn"), "ERROR": ("bad", "#EF4444", "lv_err"),
    "CRITICAL": ("bad", "#EF4444", "lv_err"), "DEBUG": ("dot", "#6F6885", "lv_info"),
}


def parse(lines):
    """-> [{"time", "level", "msg", "trace": [..]}] (traceback lines attach to the entry above them)."""
    out = []
    for ln in lines:
        m = LINE.match(ln.rstrip("\n"))
        if m:
            out.append({"time": m.group(1), "level": m.group(2).upper(), "msg": m.group(3).strip(), "trace": []})
        elif out and ln.strip():
            out[-1]["trace"].append(ln.rstrip())
    return out


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _badge_uri(level):
    name, col, _ = LEVEL_STYLE.get(level, LEVEL_STYLE["INFO"])
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    pm = icons.pixmap(name, 14, col, dpr=1.0)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    return "data:image/png;base64," + bytes(ba.toBase64()).decode()


_BADGES = {}


class LogView(QTextBrowser):
    def __init__(self, mini=False):
        super().__init__()
        self.mini = mini
        self.entries = []
        self.query = ""
        self.level = "all"
        self.raw = False
        self.setOpenLinks(False)
        self.setStyleSheet(f"QTextBrowser {{ background: #050409; border: 1px solid {TOKENS['border']}; border-radius: 12px;"
                           f" padding: 8px; font-family: 'JetBrains Mono', 'IBM Plex Sans Arabic'; font-size: 9pt; }}")
        self._last_sig = None

    def set_lines(self, lines):
        self.entries = parse(lines)
        self.render()

    def set_filter(self, query=None, level=None, raw=None):
        if query is not None: self.query = query.strip().lower()
        if level is not None: self.level = level
        if raw is not None: self.raw = raw
        self.render(force=True)

    def visible_entries(self):
        out = []
        for e in self.entries:
            if self.level == "info" and e["level"] not in ("INFO", "SUCCESS", "DEBUG"): continue
            if self.level == "warn" and e["level"] != "WARNING": continue
            if self.level == "err" and e["level"] not in ("ERROR", "CRITICAL"): continue
            if self.query:
                hay = (e["msg"] + " " + translate_log(e["msg"])).lower()
                if self.query not in hay: continue
            out.append(e)
        return out[-60:] if self.mini else out[-1500:]

    def render(self, force=False):
        vis = self.visible_entries()
        sig = (len(vis), vis[-1]["time"] + vis[-1]["msg"] if vis else "", self.raw, self.query, self.level)
        if sig == self._last_sig and not force: return
        self._last_sig = sig
        sb = self.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 30
        rtl = self.layoutDirection() == Qt.RightToLeft
        rows = []
        for e in vis:
            lvl = e["level"]
            if lvl not in _BADGES: _BADGES[lvl] = _badge_uri(lvl)
            _, col, key = LEVEL_STYLE.get(lvl, LEVEL_STYLE["INFO"])
            text = e["msg"] if self.raw else translate_log(e["msg"])
            orig = "" if (self.raw or text == e["msg"] or self.mini) else \
                f'<div style="color:{TOKENS["dim"]};font-size:8pt" dir="ltr">{_esc(e["msg"])}</div>'
            trace = ""
            if e["trace"] and not self.mini:
                trace = f'<pre style="color:#7C7396;font-size:8pt;margin:2px 0 0 0" dir="ltr">{_esc(chr(10).join(e["trace"][-25:]))}</pre>'
            align = "right" if rtl else "left"
            rows.append(
                f'<tr><td width="18" valign="top"><img src="{_BADGES[lvl]}" width="14" height="14"></td>'
                f'<td width="66" valign="top" style="color:{TOKENS["dim"]}" dir="ltr">{e["time"]}</td>'
                f'<td valign="top" style="color:{col if lvl in ("ERROR", "CRITICAL", "WARNING") else TOKENS["text"]};text-align:{align}">'
                f'{_esc(text)}{orig}{trace}</td></tr>')
        if not rows:
            html = f'<div style="color:{TOKENS["dim"]};padding:20px;text-align:center">{tr("no_log")}</div>'
        else:
            html = f'<table width="100%" cellspacing="0" cellpadding="3" dir="{"rtl" if rtl else "ltr"}">{"".join(rows)}</table>'
        self.setHtml(html)
        if at_bottom or force:
            self.moveCursor(QTextCursor.End)
            sb.setValue(sb.maximum())

    def plain_text(self):
        return "\n".join(f"{e['time']} | {e['level']} | {e['msg'] if self.raw else translate_log(e['msg'])}" for e in self.visible_entries())
