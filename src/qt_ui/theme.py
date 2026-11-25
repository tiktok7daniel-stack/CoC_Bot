"""
Clash Farmer design tokens (AMOLED black, crimson & gold), font loading and the Qt style sheet (QSS) for the whole app.
Every color used anywhere in the UI comes from TOKENS so the look stays consistent.
"""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"

TOKENS = {
    # obsidian-slate depth ramp: crisp step elevation between canvas, shell, cards, and inputs
    "void": "#06070B",            # outer window canvas
    "void2": "#0B0D14",           # framed content area
    "glass": "rgba(17, 20, 30, 0.88)",
    "glass_solid": "#11141E",     # primary cards
    "glass2": "#171B28",          # inputs, sub-cards, KPI tiles
    "glass3": "#1F2536",          # hover / active rows
    "surface_elevated": "#161A26",
    "card_top": "rgba(255, 255, 255, 0.04)",
    "border": "rgba(255, 255, 255, 0.09)",
    "border_hover": "rgba(245, 183, 64, 0.55)",
    "border_solid": "#252A3A",
    # WCAG AA+ text contrast hierarchy
    "text": "#F5F3EE",
    "muted": "#B4B0BE",
    "dim": "#8B8798",
    # Clash gold accent + legacy aliases preserved for all screens
    "violet": "#F5B740",
    "purple": "#F5B740",
    "fuchsia": "#FFD36E",
    "accent": "#F5B740",
    "accent_hi": "#FFE08A",
    "accent_lo": "#C98A1E",
    "on_accent": "#1A1206",
    "nav_from": "#F5B740",
    "nav_to": "#D9952A",
    # semantic colors + subtle translucent tints for badges & pills
    "ok": "#3DD68C",
    "ok_bg": "rgba(61, 214, 140, 0.12)",
    "bad": "#F0555A",
    "bad_bg": "rgba(240, 85, 90, 0.12)",
    "warn": "#F5A524",
    "warn_bg": "rgba(245, 165, 36, 0.12)",
    "gold": "#F5C542",
    "elixir": "#E36FD3",
    "dark": "#8D8CF7",
    "info": "#5EB1F5",
    "info_bg": "rgba(94, 177, 245, 0.12)",
}

FONTS = {"ui": "IBM Plex Sans Arabic", "ui2": "Cairo", "mono": "JetBrains Mono", "display": "Lilita One"}


def _light():
    """Light UI (default on): no hover glows / ripples / drop shadows / intro animation — a faster, calmer app."""
    try:
        import settings
        return settings.load_app().get("light_ui", True) is not False
    except Exception:
        return True


LIGHT = _light()


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
    f.setWeight(_weight(weight))
    return f


def _weight(w):
    return w if isinstance(w, QFont.Weight) else QFont.Weight(int(w))


def display_font(size=24):
    f = QFont(FONTS["display"])
    f.setFamilies([FONTS["display"], FONTS["ui2"], "Arial Black"])
    f.setPointSizeF(size)
    return f


def mono_font(size=9.5, weight=QFont.Normal):
    f = QFont(FONTS["mono"])
    f.setFamilies([FONTS["mono"], "Consolas", "DejaVu Sans Mono"])
    f.setPointSizeF(size)
    f.setWeight(_weight(weight))
    f.setStyleHint(QFont.Monospace)
    return f


def qss():
    t = TOKENS
    return f"""
* {{ outline: 0; }}
QWidget {{ color: {t['text']}; font-family: "{FONTS['ui']}", "{FONTS['ui2']}", "Segoe UI"; font-size: 10pt; }}
QMainWindow, #Root {{ background: transparent; }}
QToolTip {{ background: {t['surface_elevated']}; color: {t['text']}; border: 1px solid {t['border_hover']}; border-radius: 10px; padding: 8px 12px; }}

/* ---------- type scale: 22 / 13 / 11 / 10 / 9 ---------- */
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 21pt; font-weight: 800; letter-spacing: -0.3px; }}
QLabel[role="h2"] {{ font-size: 13pt; font-weight: 700; }}
QLabel[role="h3"] {{ font-size: 11pt; font-weight: 700; }}
QLabel[role="sub"] {{ color: {t['muted']}; font-size: 9pt; }}
QLabel[role="dim"] {{ color: {t['dim']}; font-size: 8.5pt; }}
QLabel[role="num"] {{ font-family: "{FONTS['mono']}"; font-size: 15pt; font-weight: 700; }}
QLabel[role="numsm"] {{ font-family: "{FONTS['mono']}"; font-size: 10pt; font-weight: 700; }}
QLabel[role="kpi"] {{ font-family: "{FONTS['mono']}"; font-size: 19pt; font-weight: 800; }}
QLabel[role="overline"] {{ color: {t['dim']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLabel[role="warn"] {{ color: {t['warn']}; }}
QLabel[role="bad"] {{ color: {t['bad']}; }}
QLabel[role="ok"] {{ color: {t['ok']}; }}

/* ---------- inputs ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit, QPlainTextEdit, QTextEdit {{
  background: {t['glass2']}; border: 1px solid {t['border_solid']}; border-radius: 12px; padding: 6px 12px;
  selection-background-color: {t['accent']}; selection-color: {t['on_accent']}; min-height: 24px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QTimeEdit:hover {{ border-color: rgba(255,255,255,0.22); background: {t['surface_elevated']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; background: {t['glass3']}; }}
QSpinBox, QDoubleSpinBox, QTimeEdit {{ font-family: "{FONTS['mono']}"; padding-right: 6px; padding-left: 6px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: 0; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {t['surface_elevated']}; border: 1px solid {t['border_hover']}; selection-background-color: rgba(245,183,64,0.18); selection-color: {t['accent_hi']}; padding: 4px; border-radius: 10px; }}
QLineEdit[role="search"] {{ padding-left: 30px; padding-right: 30px; border-radius: 10px; }}

/* ---------- buttons: tactile hierarchy using token ramp ---------- */
QPushButton {{ background: {t['glass2']}; border: 1px solid {t['border_solid']}; border-radius: 12px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ border-color: rgba(255,255,255,0.24); background: {t['glass3']}; color: #FFFFFF; }}
QPushButton:pressed {{ background: {t['glass_solid']}; }}
QPushButton:disabled {{ color: {t['dim']}; border-color: {t['border']}; background: {t['void2']}; }}
QPushButton[kind="primary"] {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['accent_hi']}, stop:0.5 {t['accent']}, stop:1 {t['nav_to']});
  border: 1px solid #FFE29A; color: {t['on_accent']}; font-weight: 700; }}
QPushButton[kind="primary"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FFE8A3, stop:0.5 #FFC552, stop:1 #E7A332); }}
QPushButton[kind="primary"]:pressed {{ background: {t['accent_lo']}; }}
QPushButton[kind="go"] {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #3DD68C, stop:1 #23A866); border: 1px solid #6BE6A9; color: #04170D; font-weight: 700; }}
QPushButton[kind="go"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #55E39D, stop:1 #2CB873); }}
QPushButton[kind="go"]:disabled {{ background: #10261B; border-color: #173826; color: #4F8A6B; }}
QPushButton[kind="stop"] {{ background: {t['bad_bg']}; border: 1px solid rgba(240,85,90,0.48); color: #FFA8AB; }}
QPushButton[kind="stop"]:hover {{ background: rgba(240,85,90,0.22); color: #FFD0D2; }}
QPushButton[kind="warn"] {{ background: {t['warn_bg']}; border: 1px solid rgba(245,183,64,0.45); color: {t['accent_hi']}; }}
QPushButton[kind="warn"]:hover {{ background: rgba(245,183,64,0.20); }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[kind="ghost"]:hover {{ background: rgba(255,255,255,0.06); border-color: {t['border']}; }}
QPushButton[kind="chip"] {{ border-radius: 16px; padding: 5px 14px; font-weight: 600; color: {t['muted']}; }}
QPushButton[kind="chip"]:hover {{ color: {t['text']}; }}
QPushButton[kind="chip"]:checked {{ background: rgba(245,183,64,0.16); border-color: rgba(245,183,64,0.68); color: {t['accent_hi']}; }}
QPushButton[kind="win"] {{ background: transparent; border: 0; border-radius: 8px; padding: 4px; }}
QPushButton[kind="win"]:hover {{ background: rgba(255,255,255,0.08); }}
QPushButton[kind="winclose"] {{ background: transparent; border: 0; border-radius: 8px; padding: 4px; }}
QPushButton[kind="winclose"]:hover {{ background: {t['bad']}; color: #FFFFFF; }}

/* ---------- checkboxes ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {t['border_solid']}; background: {t['glass2']}; }}
QCheckBox::indicator:checked {{ background: {t['accent']}; border-color: {t['accent']}; }}

/* ---------- scroll ---------- */
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(245,183,64,0.60); }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; width: 0; height: 0; }}

/* ---------- tables ---------- */
QTableWidget {{ background: transparent; border: 0; gridline-color: {t['border_solid']}; alternate-background-color: rgba(255,255,255,0.022); }}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {t['border_solid']}; }}
QTableWidget::item:selected {{ background: rgba(245,183,64,0.16); color: {t['accent_hi']}; }}
QHeaderView {{ background: transparent; border: 0; }}
QTableCornerButton::section {{ background: transparent; border: 0; }}
QTableWidget QWidget#qt_scrollarea_viewport, QTableView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t['dim']}; border: 0; border-bottom: 1px solid {t['border_solid']}; padding: 9px 6px; font-weight: 700; font-size: 8.5pt; }}

/* ---------- lists ---------- */
QListWidget {{ background: {t['glass2']}; border: 1px solid {t['border_solid']}; border-radius: 14px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(245,183,64,0.16); color: {t['accent_hi']}; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}

/* ---------- menus ---------- */
QMenu {{ background: {t['surface_elevated']}; border: 1px solid {t['border_solid']}; border-radius: 14px; padding: 5px; }}
QMenu::item {{ padding: 8px 20px; border-radius: 8px; }}
QMenu::item:selected {{ background: rgba(245,183,64,0.16); color: {t['accent_hi']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
"""
