"""
Obsidian & Neon-Violet design tokens, font loading and the Qt style sheet (QSS) for the whole app.
Every color used anywhere in the UI comes from TOKENS so the look stays consistent.
"""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"

TOKENS = {
    "void": "#08070D",            # window canvas
    "void2": "#0D0B15",           # framed content area
    "glass": "rgba(19, 17, 29, 0.72)",
    "glass_solid": "#13111D",     # glass color for painters (no alpha blending of children)
    "glass2": "#1A1727",          # inputs, inner rows
    "glass3": "#221E33",          # hover / raised rows
    "border": "rgba(168, 85, 247, 0.18)",
    "border_hover": "rgba(168, 85, 247, 0.48)",
    "border_solid": "#2A2340",
    "text": "#EDEAF7",
    "muted": "#A49DBB",
    "dim": "#6F6885",
    "violet": "#8B5CF6",
    "purple": "#A855F7",
    "fuchsia": "#D946EF",
    "nav_from": "#9333EA",
    "nav_to": "#C026D3",
    "ok": "#10B981",
    "bad": "#EF4444",
    "warn": "#F59E0B",
    "gold": "#FBBF24",
    "elixir": "#EC4899",
    "dark": "#6366F1",
    "info": "#38BDF8",
}

FONTS = {"ui": "IBM Plex Sans Arabic", "ui2": "Cairo", "mono": "JetBrains Mono"}


def color(name, alpha=None):
    c = QColor(TOKENS.get(name, name))
    if alpha is not None: c.setAlphaF(alpha)
    return c


def load_fonts():
    """Register the bundled fonts; falls back silently to system fonts when a file is missing."""
    loaded = []
    for f in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) >= 0: loaded.append(f.stem)
    return loaded


def ui_font(size=10, weight=QFont.Normal):
    f = QFont(FONTS["ui"])
    f.setFamilies([FONTS["ui"], FONTS["ui2"], "Segoe UI", "Tahoma"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    return f


def mono_font(size=9.5, weight=QFont.Normal):
    f = QFont(FONTS["mono"])
    f.setFamilies([FONTS["mono"], "Consolas", "DejaVu Sans Mono"])
    f.setPointSizeF(size)
    f.setWeight(weight)
    f.setStyleHint(QFont.Monospace)
    return f


def qss():
    t = TOKENS
    return f"""
* {{ outline: 0; }}
QWidget {{ color: {t['text']}; font-family: "{FONTS['ui']}", "{FONTS['ui2']}", "Segoe UI"; font-size: 10pt; }}
QMainWindow, #Root {{ background: transparent; }}
#Canvas {{ background: {t['void']}; border-radius: 14px; border: 1px solid {t['border_solid']}; }}
#Content {{ background: {t['void2']}; border: 1px solid {t['border']}; border-radius: 14px; }}
QToolTip {{ background: {t['glass2']}; color: {t['text']}; border: 1px solid {t['border_hover']}; border-radius: 6px; padding: 6px 8px; }}

/* ---------- text ---------- */
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 22pt; font-weight: 800; }}
QLabel[role="h2"] {{ font-size: 13pt; font-weight: 700; }}
QLabel[role="h3"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[role="sub"] {{ color: {t['muted']}; font-size: 9pt; }}
QLabel[role="dim"] {{ color: {t['dim']}; font-size: 8.5pt; }}
QLabel[role="num"] {{ font-family: "{FONTS['mono']}"; font-size: 15pt; font-weight: 700; }}
QLabel[role="numsm"] {{ font-family: "{FONTS['mono']}"; font-size: 10pt; font-weight: 700; }}
QLabel[role="kpi"] {{ font-family: "{FONTS['mono']}"; font-size: 19pt; font-weight: 800; }}
QLabel[role="warn"] {{ color: {t['warn']}; }}
QLabel[role="bad"] {{ color: {t['bad']}; }}
QLabel[role="ok"] {{ color: {t['ok']}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit, QPlainTextEdit, QTextEdit {{
  background: {t['glass2']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 6px 10px;
  selection-background-color: {t['violet']}; min-height: 22px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QTimeEdit:hover {{ border-color: {t['border_hover']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QPlainTextEdit:focus {{ border-color: {t['purple']}; }}
QSpinBox, QDoubleSpinBox, QTimeEdit {{ font-family: "{FONTS['mono']}"; padding-right: 6px; padding-left: 6px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: 0; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {t['glass2']}; border: 1px solid {t['border_hover']}; selection-background-color: {t['violet']}; padding: 4px; }}
QLineEdit[role="search"] {{ padding-left: 30px; padding-right: 30px; border-radius: 10px; }}

/* ---------- buttons ---------- */
QPushButton {{ background: {t['glass2']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {t['border_hover']}; background: {t['glass3']}; }}
QPushButton:pressed {{ background: {t['border_solid']}; }}
QPushButton:disabled {{ color: {t['dim']}; border-color: {t['border_solid']}; background: {t['glass_solid']}; }}
QPushButton[kind="primary"] {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {t['violet']}, stop:0.5 {t['purple']}, stop:1 {t['fuchsia']}); border: 0; color: white; }}
QPushButton[kind="primary"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #9B70F8, stop:0.5 #B46BF8, stop:1 #E065F1); }}
QPushButton[kind="go"] {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #19C98E, stop:1 #0E9F6E); border: 1px solid #34D399; color: white; }}
QPushButton[kind="go"]:disabled {{ background: #10392D; border-color: #155E47; color: #6FAF97; }}
QPushButton[kind="stop"] {{ background: rgba(239,68,68,0.12); border: 1px solid rgba(239,68,68,0.55); color: #FCA5A5; }}
QPushButton[kind="stop"]:hover {{ background: rgba(239,68,68,0.22); }}
QPushButton[kind="warn"] {{ background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.55); color: #FCD34D; }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[kind="ghost"]:hover {{ background: {t['glass3']}; border-color: {t['border']}; }}
QPushButton[kind="chip"] {{ border-radius: 14px; padding: 4px 12px; font-weight: 600; }}
QPushButton[kind="chip"]:checked {{ background: {t['violet']}; border-color: {t['violet']}; color: white; }}
QPushButton[kind="win"] {{ background: transparent; border: 0; border-radius: 6px; padding: 4px; }}
QPushButton[kind="win"]:hover {{ background: {t['glass3']}; }}
QPushButton[kind="winclose"] {{ background: transparent; border: 0; border-radius: 6px; padding: 4px; }}
QPushButton[kind="winclose"]:hover {{ background: {t['bad']}; }}

/* ---------- checkboxes ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {t['border_hover']}; background: {t['glass2']}; }}
QCheckBox::indicator:checked {{ background: {t['violet']}; border-color: {t['violet']}; }}

/* ---------- scroll ---------- */
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t['border_solid']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t['violet']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t['border_solid']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; width: 0; height: 0; }}

/* ---------- tables ---------- */
QTableWidget {{ background: transparent; border: 0; gridline-color: {t['border_solid']}; alternate-background-color: rgba(139,92,246,0.04); }}
QTableWidget::item {{ padding: 6px; border-bottom: 1px solid {t['border_solid']}; }}
QTableWidget::item:selected {{ background: rgba(139,92,246,0.22); }}
QHeaderView::section {{ background: transparent; color: {t['muted']}; border: 0; border-bottom: 1px solid {t['border_hover']}; padding: 8px 6px; font-weight: 700; }}

/* ---------- lists ---------- */
QListWidget {{ background: {t['glass2']}; border: 1px solid {t['border']}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: rgba(139,92,246,0.28); }}
QListWidget::item:hover {{ background: {t['glass3']}; }}

/* ---------- menus ---------- */
QMenu {{ background: {t['glass2']}; border: 1px solid {t['border_hover']}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t['violet']}; }}
"""
