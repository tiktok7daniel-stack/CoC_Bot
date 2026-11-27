"""UI Phase 1 verification tests.

Tests that all new widgets, SVG icons, and legacy controls.py / theme.py imports
instantiate without errors.
"""
import os
import sys
import unittest

# Set offscreen platform for headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"

# Check if PySide6 is available
try:
    from PySide6.QtWidgets import QApplication
    HAS_PY_SIDE6 = True
except ImportError:
    HAS_PY_SIDE6 = False


def skip_if_no_qt(test_method):
    """Decorator to skip a test if PySide6 is not available."""
    def wrapper(self):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        return test_method(self)
    return wrapper


class TestUiPhase1Widgets(unittest.TestCase):
    """Test that all new widgets can be imported and instantiated."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @skip_if_no_qt
    def test_import_theme_tokens(self):
        """theme.py TOKENS dict should be accessible."""
        from qt_ui.theme import TOKENS, LIGHT, color
        self.assertIsInstance(TOKENS, dict)
        self.assertIn("crimson", TOKENS)
        self.assertIn("glass_solid", TOKENS)
        self.assertIsNotNone(color("text"))

    @skip_if_no_qt
    def test_import_theme_fonts(self):
        """theme.py font functions should be callable."""
        from qt_ui.theme import ui_font, mono_font, display_font, load_fonts, FONTS
        self.assertIsInstance(FONTS, dict)
        self.assertIn("ui", FONTS)
        f = ui_font()
        self.assertIsNotNone(f)
        fm = mono_font()
        self.assertIsNotNone(fm)

    @skip_if_no_qt
    def test_import_tokens_colors(self):
        """color() function should return QColor."""
        from qt_ui.theme import TOKENS, color
        c = color("crimson")
        self.assertEqual(c.name().lower(), "#e11d48")
        c2 = color("ok", alpha=0.5)
        self.assertEqual(c2.alphaF(), 0.5)


class TestUiPhase1Icons(unittest.TestCase):
    """Test that SVG icons work correctly."""

    @skip_if_no_qt
    def test_import_icons_module(self):
        """icons.py should import successfully."""
        from qt_ui import icons
        self.assertTrue(hasattr(icons, 'pixmap'))
        self.assertTrue(hasattr(icons, 'icon'))
        self.assertTrue(hasattr(icons, 'svg_markup'))

    @skip_if_no_qt
    def test_svg_pixmap_renders(self):
        """pixmap() should render SVG icons to QPixmap."""
        from qt_ui import icons
        from PySide6.QtGui import QPixmap
        pm = icons.pixmap("check", 24)
        self.assertIsInstance(pm, QPixmap)
        self.assertTrue(pm.width() > 0)
        self.assertTrue(pm.height() > 0)

    def test_svg_icons_no_emoji(self):
        """Icons should be SVG-based, not Unicode emojis."""
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from qt_ui import icons
        svg = icons.svg_markup("check", "#E11D48")
        self.assertIn("<svg", svg)
        self.assertNotIn("✓", svg)  # No Unicode checkmark
        self.assertNotIn("✗", svg)  # No Unicode X mark

    @skip_if_no_qt
    def test_status_icons_svg(self):
        """Status icons (ok, bad, warn, info) should be SVG-based."""
        from qt_ui import icons
        for name in ["ok", "bad", "warn", "info"]:
            pm = icons.pixmap(name, 16)
            self.assertTrue(pm.width() > 0, f"Icon {name} should render")

    @skip_if_no_qt
    def test_glyphs_render(self):
        """Game glyphs should render correctly."""
        from qt_ui import icons
        for name in ["verified", "gold", "elixir", "dark"]:
            pm = icons.pixmap(name, 20, "#FFFFFF")
            self.assertTrue(pm.width() > 0, f"Glyph {name} should render")


class TestUiPhase1LegacyImports(unittest.TestCase):
    """Test that legacy widget imports from controls.py work."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @skip_if_no_qt
    def test_legacy_glass_card_import(self):
        """GlassCard should be importable from widgets module."""
        from qt_ui.widgets import GlassCard
        card = GlassCard(title_key="test")
        self.assertIsNotNone(card)

    @skip_if_no_qt
    def test_legacy_status_pill_import(self):
        """StatusPill should be importable from widgets module."""
        from qt_ui.widgets import StatusPill
        pill = StatusPill(key="ok", text="Ready")
        self.assertIsNotNone(pill)

    @skip_if_no_qt
    def test_legacy_toggle_import(self):
        """Toggle should be importable from widgets module."""
        from qt_ui.widgets import Toggle
        tgl = Toggle()
        self.assertIsNotNone(tgl)

    @skip_if_no_qt
    def test_legacy_kpi_tile_import(self):
        """KpiTile should be importable from widgets module."""
        from qt_ui.widgets import KpiTile
        tile = KpiTile(key="test_kpi")
        self.assertIsNotNone(tile)
        tile.set("100")

    @skip_if_no_qt
    def test_legacy_icon_button_import(self):
        """IconButton should be importable from widgets module."""
        from qt_ui.widgets import IconButton
        btn = IconButton(icon_name="check", kind="primary")
        self.assertIsNotNone(btn)


class TestUiPhase1NewWidgets(unittest.TestCase):
    """Test that new Phase 1 widgets work correctly."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    @skip_if_no_qt
    def test_glass_panel(self):
        """GlassPanel widget should instantiate."""
        from qt_ui.widgets import GlassPanel
        panel = GlassPanel()
        self.assertIsNotNone(panel)

    @skip_if_no_qt
    def test_elevated_card(self):
        """ElevatedCard widget should instantiate."""
        from qt_ui.widgets import ElevatedCard
        card = ElevatedCard()
        self.assertIsNotNone(card)

    @skip_if_no_qt
    def test_live_dot(self):
        """LiveDot widget should instantiate and change state."""
        from qt_ui.widgets import LiveDot
        dot = LiveDot()
        dot.set_state("live")
        dot.set_state("idle")
        self.assertIsNotNone(dot)

    @skip_if_no_qt
    def test_live_status_badge(self):
        """LiveStatusBadge widget should instantiate."""
        from qt_ui.widgets import LiveStatusBadge
        badge = LiveStatusBadge()
        self.assertIsNotNone(badge)
        badge.set_state("live")

    @skip_if_no_qt
    def test_animated_toggle(self):
        """AnimatedToggle widget should instantiate."""
        from qt_ui.widgets import AnimatedToggle
        tgl = AnimatedToggle()
        self.assertIsNotNone(tgl)

    @skip_if_no_qt
    def test_metric_tile(self):
        """MetricTile widget should instantiate and update value."""
        from qt_ui.widgets import MetricTile
        tile = MetricTile(key="metric", accent="#E11D48")
        self.assertIsNotNone(tile)
        tile.set("42")

    @skip_if_no_qt
    def test_kpi_row(self):
        """KpiRow widget should instantiate with multiple tiles."""
        from qt_ui.widgets import KpiRow
        row = KpiRow([("kills", "#E11D48"), ("deaths", "#EF4444")])
        self.assertIsNotNone(row)

    @skip_if_no_qt
    def test_metric_label(self):
        """MetricLabel widget should instantiate."""
        from qt_ui.widgets import MetricLabel
        lbl = MetricLabel(label_text="Attacks", value=100)
        self.assertIsNotNone(lbl)
        lbl.set_value("200")

    @skip_if_no_qt
    def test_live_counter(self):
        """LiveCounter widget should instantiate with animation."""
        from qt_ui.widgets import LiveCounter
        counter = LiveCounter(value=0)
        self.assertIsNotNone(counter)
        counter.set_target(50)

    @skip_if_no_qt
    def test_console_log(self):
        """ConsoleLog widget should instantiate and accept messages."""
        from qt_ui.widgets import ConsoleLog
        log = ConsoleLog()
        self.assertIsNotNone(log)
        log.append("Test message", level="info")
        log.append("Error message", level="error")

    @skip_if_no_qt
    def test_log_panel(self):
        """LogPanel widget should instantiate with header."""
        from qt_ui.widgets import LogPanel
        panel = LogPanel(title="Activity Log")
        self.assertIsNotNone(panel)
        panel.append("Started", level="ok")


class TestUiPhase1IconsImports(unittest.TestCase):
    """Test that all legacy controls work with icons module."""

    @skip_if_no_qt
    def test_icon_badge_instantiates(self):
        """IconBadge should work with icons.pixmap()."""
        from qt_ui.widgets.controls import IconBadge
        badge = IconBadge("check", 32)
        self.assertIsNotNone(badge)

    @skip_if_no_qt
    def test_icon_button_with_icon(self):
        """IconButton should render icon correctly."""
        from qt_ui.widgets import IconButton
        btn = IconButton(icon_name="save", kind="primary", size=16)
        self.assertIsNotNone(btn)

    @skip_if_no_qt
    def test_form_row_with_icon(self):
        """form_row should work with icon_name parameter."""
        from qt_ui.widgets import form_row
        row = form_row(icon_name="search")
        self.assertIsNotNone(row)

    @skip_if_no_qt
    def test_note_with_icon(self):
        """note() helper should work with icon_name."""
        from qt_ui.widgets import note
        w = note("Test note", icon_name="info")
        self.assertIsNotNone(w)


if __name__ == "__main__":
    unittest.main(verbosity=2)