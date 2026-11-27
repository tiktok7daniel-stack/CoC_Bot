"""
Clash Farmer design tokens — Luxury Dark Obsidian & Crimson Glassmorphism.
Every color used anywhere in the UI comes from TOKENS so the look stays consistent.
Backward compatible: legacy gold/amber keys map to new crimson/obsidian palette.
"""
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# ── Luxury Dark Obsidian & Crimson Palette ──
TOKENS = {
    # ── Obsidian depth ramp ──
    "void":         "#0A0A0C",        # outer window canvas
    "void2":        "#0D0E14",        # framed content area
    "glass":        "rgba(18, 22, 34, 0.88)",   # primary glass
    "glass_solid":  "#121216",        # primary cards
    "glass2":       "#1A1A22",        # inputs, sub-cards, KPI tiles
    "glass3":       "#242430",        # hover / active rows
    "surface_elevated": "#181820",    # elevated panels
    "card_top":     "rgba(255, 255, 255, 0.04)", # top sheen
    "border":       "rgba(255, 255, 255, 0.07)", # subtle glass border
    "border_hover": "rgba(225, 29, 72, 0.55)",   # crimson hover border
    "border_solid": "#2A2A3A",        # solid borders

    # ── Text hierarchy (WCAG AA+) ──
    "text":         "#F4F4F5",        # primary
    "muted":        "#A1A1AA",        # secondary
    "dim":          "#71717A",        # tertiary / disabled

    # ── Crimson accent system ──
    "crimson":      "#E11D48",        # primary accent
    "crimson_hi":   "#F43F5E",        # hover
    "crimson_lo":   "#BE123C",        # pressed
    "crimson_bg":   "rgba(225, 29, 72, 0.12)",
    "crimson_glow": "rgba(225, 29, 72, 0.30)",

    # ── Legacy gold/amber aliases (BACKWARD COMPATIBLE) ──
    # Map to crimson so unmigrated screens don't crash
    "violet":       "#E11D48",
    "purple":       "#E11D48",
    "fuchsia":      "#F43F5E",
    "accent":       "#E11D48",
    "accent_hi":    "#F43F5E",
    "accent_lo":    "#BE123C",
    "on_accent":    "#FFFFFF",
    "nav_from":     "#E11D48",
    "nav_to":       "#BE123C",
    "gold":         "#E11D48",

    # ── Semantic status ──
    "ok":           "#10B981",        # emerald
    "ok_bg":        "rgba(16, 185, 129, 0.12)",
    "bad":          "#EF4444",        # red
    "bad_bg":       "rgba(239, 68, 68, 0.12)",
    "warn":         "#F59E0B",        # amber
    "warn_bg":      "rgba(245, 158, 11, 0.12)",
    "info":         "#38BDF8",        # sky
    "info_bg":      "rgba(56, 189, 248, 0.12)",

    # ── Elixir / special ──
    "elixir":       "#E36FD3",
    "dark":         "#8D8CF7",

    # ── Layout constants ──
    "radius_card":  12,
    "radius_button": 8,
    "radius_pill":  999,
}

FONTS = {
    "ui":       "IBM Plex Sans Arabic",
    "ui2":      "Cairo",
    "mono":     "JetBrains Mono",
    "display":  "Lilita One",
}


def _light():
    """Light UI (default on): no hover glows / ripples / drop shadows / intro animation."""
    try:
        import settings
        return settings.load_app().get("light_ui", True) is not False
    except Exception:
        return True


LIGHT = _light()


def color(name, alpha=None):
    c = QColor(TOKENS.get(name, name))
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def load_fonts():
    """Register the bundled fonts; falls back silently to system fonts when a file is missing."""
    loaded = []
    for f in sorted(FONT_DIR.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) >= 0:
            loaded.append(f.stem)
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

/* ---------- type scale ---------- */
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
  selection-background-color: {t['crimson']}; selection-color: {t['text']}; min-height: 24px; }}
QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover, QTimeEdit:hover {{
  border-color: rgba(255,255,255,0.22); background: {t['surface_elevated']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTimeEdit:focus, QPlainTextEdit:focus {{
  border-color: {t['crimson']}; background: {t['glass3']}; }}
QSpinBox, QDoubleSpinBox, QTimeEdit {{
  font-family: "{FONTS['mono']}"; padding-right: 6px; padding-left: 6px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: 0; }}
QComboBox::drop-down {{ border: 0; width: 24px; }}
QComboBox::down-arrow {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {t['surface_elevated']}; border: 1px solid {t['border_hover']};
  selection-background-color: rgba(225,29,72,0.18); selection-color: {t['crimson_hi']}; padding: 4px; border-radius: 10px; }}
QLineEdit[role="search"] {{ padding-left: 30px; padding-right: 30px; border-radius: 10px; }}

/* ---------- buttons: tactile hierarchy ---------- */
QPushButton {{ background: {t['glass2']}; border: 1px solid {t['border_solid']}; border-radius: 12px; padding: 8px 16px; font-weight: 600; }}
QPushButton:hover {{ border-color: rgba(255,255,255,0.24); background: {t['glass3']}; color: #FFFFFF; }}
QPushButton:pressed {{ background: {t['glass_solid']}; }}
QPushButton:disabled {{ color: {t['dim']}; border-color: {t['border']}; background: {t['void2']}; }}
QPushButton[kind="primary"] {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['crimson_hi']}, stop:0.5 {t['crimson']}, stop:1 {t['crimson_lo']});
  border: 1px solid rgba(225,29,72,0.6); color: {t['on_accent']}; font-weight: 700; }}
QPushButton[kind="primary"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FF6B8A, stop:0.5 #E11D48, stop:1 #A81236); }}
QPushButton[kind="primary"]:pressed {{ background: {t['crimson_lo']}; }}
QPushButton[kind="go"] {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {t['ok']}, stop:1 #0D9B66); border: 1px solid #2FE08A; color: #04170D; font-weight: 700; }}
QPushButton[kind="go"]:hover {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2FE08A, stop:1 #14B876); }}
QPushButton[kind="go"]:disabled {{ background: #10261B; border-color: #173826; color: #4F8A6B; }}
QPushButton[kind="stop"] {{ background: {t['bad_bg']}; border: 1px solid rgba(239,68,68,0.48); color: #FFA8AB; }}
QPushButton[kind="stop"]:hover {{ background: rgba(239,68,68,0.22); color: #FFD0D2; }}
QPushButton[kind="warn"] {{ background: {t['warn_bg']}; border: 1px solid rgba(245,158,11,0.45); color: {t['warn']}; }}
QPushButton[kind="warn"]:hover {{ background: rgba(245,158,11,0.20); }}
QPushButton[kind="ghost"] {{ background: transparent; border: 1px solid transparent; }}
QPushButton[kind="ghost"]:hover {{ background: rgba(255,255,255,0.06); border-color: {t['border']}; }}
QPushButton[kind="chip"] {{ border-radius: 16px; padding: 5px 14px; font-weight: 600; color: {t['muted']}; }}
QPushButton[kind="chip"]:hover {{ color: {t['text']}; }}
QPushButton[kind="chip"]:checked {{ background: rgba(225,29,72,0.16); border-color: rgba(225,29,72,0.68); color: {t['crimson_hi']}; }}
QPushButton[kind="win"] {{ background: transparent; border: 0; border-radius: 8px; padding: 4px; }}
QPushButton[kind="win"]:hover {{ background: rgba(255,255,255,0.08); }}
QPushButton[kind="winclose"] {{ background: transparent; border: 0; border-radius: 8px; padding: 4px; }}
QPushButton[kind="winclose"]:hover {{ background: {t['bad']}; color: #FFFFFF; }}

/* ---------- checkboxes ---------- */
QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 6px; border: 1px solid {t['border_solid']}; background: {t['glass2']}; }}
QCheckBox::indicator:checked {{ background: {t['crimson']}; border-color: {t['crimson']}; }}

/* ---------- scroll ---------- */
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(225,29,72,0.60); }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: 0; width: 0; height: 0; }}

/* ---------- tables ---------- */
QTableWidget {{ background: transparent; border: 0; gridline-color: {t['border_solid']}; alternate-background-color: rgba(255,255,255,0.022); }}
QTableWidget::item {{ padding: 8px; border-bottom: 1px solid {t['border_solid']}; }}
QTableWidget::item:selected {{ background: rgba(225,29,72,0.16); color: {t['crimson_hi']}; }}
QHeaderView {{ background: transparent; border: 0; }}
QTableCornerButton::section {{ background: transparent; border: 0; }}
QTableWidget QWidget#qt_scrollarea_viewport, QTableView {{ background: transparent; }}
QHeaderView::section {{ background: transparent; color: {t['dim']}; border: 0; border-bottom: 1px solid {t['border_solid']}; padding: 9px 6px; font-weight: 700; font-size: 8.5pt; }}

/* ---------- lists ---------- */
QListWidget {{ background: {t['glass2']}; border: 1px solid {t['border_solid']}; border-radius: 14px; padding: 4px; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(225,29,72,0.16); color: {t['crimson_hi']}; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}

/* ---------- menus ---------- */
QMenu {{ background: {t['surface_elevated']}; border: 1px solid {t['border_solid']}; border-radius: 14px; padding: 5px; }}
QMenu::item {{ padding: 8px 20px; border-radius: 8px; }}
QMenu::item:selected {{ background: rgba(225,29,72,0.16); color: {t['crimson_hi']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
"""