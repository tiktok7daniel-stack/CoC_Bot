"""UI Phase 2 verification tests.

Tests that Phase 2 features work correctly:
- Obsidian & Crimson theme applied to royale_live_screen.py
- Zero Unicode emojis in Royale UI files and i18n strings
- Pre-flight health strip wired to preflight.py (off main thread)
- Watch Mode toggle bound to store
- Telemetry metrics (FPS, frame age, vision source)
"""
import os
import sys
import unittest
import ast

# Add project root and src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

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


class TestUiPhase2ZeroEmoji(unittest.TestCase):
    """Test that zero Unicode emojis remain in Royale UI files."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    # Common Unicode emoji ranges and specific characters to ban
    BANNED_CHARS = set([
        '▶', '●', '○', '⚡', '👑', '✅', '❌', '⚠️', '🔴', '📸', '🧠', '👁️',
        '🎮', '🏗️', '🧱', '🎁', '⏩', '🤔', '🪄', '📡', '⏱️', '⚔️',
        '✅', '⚠️', '✗', '✓', '✔️', '✕', '🟢', '🔴', '🟡', '🟠',
        '🔵', '🟣', '⚫', '⚪', '💚', '❤️', '💛', '💙', '💜', '🖤', '🤍',
        '⚡', '⚙️', '🔧', '🔨', '🛠️', '⛏️', '⚒️', '🔩', '⚓', '⛵',
        '🚀', '🛸', '💫', '✨', '💥', '💢', '💦', '💨', '💤', '🕳️',
        '💣', '💬', '👁️', '👁', '🗨️', '🗯️', '💭', '💬', '💭',
    ])

    def _scan_file_for_emojis(self, filepath, skip_lines=None):
        """Scan a Python file for banned Unicode characters in string literals."""
        skip_lines = skip_lines or []
        violations = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            return violations

        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                lineno = getattr(node, 'lineno', 0)
                if lineno in skip_lines:
                    continue
                for char in node.value:
                    if char in self.BANNED_CHARS:
                        violations.append((lineno, char, node.value[:80]))
        return violations

    def test_royale_live_screen_no_emoji(self):
        """royale_live_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/royale_live_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in royale_live_screen.py: {violations}")

    def test_royale_i18n_no_emoji(self):
        """Royale i18n strings must have zero Unicode emojis."""
        import json
        with open('src/qt_ui/i18n_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check Royale-specific keys
        royale_keys = ['rl_', 'rh_', 'ra_', 'royale_']
        violations = []

        for lang in ['ar', 'en']:
            lang_data = data.get(lang, {})
            for key, value in lang_data.items():
                if any(key.startswith(prefix) for prefix in royale_keys):
                    for char in value:
                        if char in self.BANNED_CHARS:
                            violations.append((lang, key, char, value[:80]))

        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in Royale i18n strings: {violations}")

    def test_royale_live_screen_uses_crimson_not_gold(self):
        """royale_live_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/royale_live_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        # Should have zero TOKENS["gold"] and at least one TOKENS["crimson"]
        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")


class TestUiPhase2Imports(unittest.TestCase):
    """Test that Phase 2 imports work correctly."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_royale_live_screen_imports(self):
        """royale_live_screen.py imports should succeed."""
        from qt_ui.screens import royale_live_screen
        self.assertTrue(hasattr(royale_live_screen, 'RoyaleLiveScreen'))

    def test_preflight_module_imports(self):
        """preflight.py should import and have run_preflight."""
        from royale.preflight import run_preflight, PreflightResult
        self.assertTrue(callable(run_preflight))
        self.assertTrue(hasattr(PreflightResult, 'ok'))

    def test_widgets_available(self):
        """Required widgets should be importable."""
        from qt_ui.widgets import (
            StatusPill, AnimatedToggle, MetricTile, ConsoleLog, FlowLayout
        )
        self.assertIsNotNone(StatusPill)
        self.assertIsNotNone(AnimatedToggle)
        self.assertIsNotNone(MetricTile)
        self.assertIsNotNone(ConsoleLog)
        self.assertIsNotNone(FlowLayout)


class TestUiPhase2Preflight(unittest.TestCase):
    """Test pre-flight health strip wiring."""

    def test_preflight_checks_structure(self):
        """Preflight checks should return structured results."""
        from royale.preflight import run_preflight
        result = run_preflight()

        # Result should have ok, warnings, errors
        self.assertIsInstance(result.ok, bool)
        self.assertIsInstance(result.warnings, list)
        self.assertIsInstance(result.errors, list)

    def test_preflight_assets_check(self):
        """Assets check should verify required files."""
        from royale.preflight import _check_assets
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        result = _check_assets(root)
        self.assertIsInstance(result.ok, bool)

    def test_preflight_adb_check(self):
        """ADB check should handle missing ADB gracefully."""
        from royale.preflight import _check_adb
        result = _check_adb()
        self.assertIsInstance(result.ok, bool)

    def test_preflight_resources_check(self):
        """Resources check should verify RAM/disk."""
        from royale.preflight import _check_resources
        result = _check_resources()
        self.assertIsInstance(result.ok, bool)


class TestUiPhase2WatchMode(unittest.TestCase):
    """Test Watch Mode toggle binding."""

    def test_watch_mode_store_key(self):
        """Watch mode should bind to royale.watch_only store key."""
        # Verify the key is used in the screen
        with open('src/qt_ui/screens/royale_live_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('royale.watch_only', content,
            "Watch mode should bind to royale.watch_only store key")


class TestUiPhase2Telemetry(unittest.TestCase):
    """Test telemetry metrics."""

    def test_telemetry_metric_names(self):
        """Telemetry should use FPS, frame age, vision source."""
        with open('src/qt_ui/screens/royale_live_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for telemetry metric updates
        self.assertIn('tele_fps', content)
        self.assertIn('tele_frame_age', content)
        self.assertIn('tele_vision_src', content)


if __name__ == "__main__":
    unittest.main(verbosity=2)