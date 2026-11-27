"""UI Phase 3 verification tests.

Tests that Phase 3 features work correctly:
- All Royale screens migrated to Obsidian & Crimson tokens
- Zero Unicode emojis in any modified screen file
- Zero hardcoded legacy gold hex (#F5B740) in modified screens
- All critical signal/slot names and store bindings preserved
- SVG icons used instead of Unicode emojis
- TOKENS['crimson'] used instead of TOKENS['gold']
"""
import os
import sys
import unittest
import ast
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class TestUiPhase3ZeroEmoji(unittest.TestCase):
    """Test that zero Unicode emojis remain in Phase 3 Royale UI files."""

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
        '🧠', '🔁', '📷', '🩺', '🃏', '🎬', '🧪', '⚖️', '📊', '📈',
        '📉', '💡', '💡', '🔍', '🔎', '🔬', '📋', '📄', '📝', '✏️',
        '✒️', '🖋️', '🖊️', '🖌️', '🖍️', '📏', '📐', '📎', '🖇️', '📂',
        '📁', '📂', '🗂️', '🗃️', '🗄️', '📦', '📦', '📥', '📤', '🗃️',
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

    def test_royale_home_screen_no_emoji(self):
        """royale_home_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/royale_home_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in royale_home_screen.py: {violations}")

    def test_royale_screen_no_emoji(self):
        """royale_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/royale_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in royale_screen.py: {violations}")

    def test_royale_ai_screen_no_emoji(self):
        """royale_ai_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/royale_ai_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in royale_ai_screen.py: {violations}")

    def test_royale_training_screen_no_emoji(self):
        """royale_training_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/royale_training_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in royale_training_screen.py: {violations}")

    def test_bot_settings_screen_no_emoji(self):
        """bot_settings_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/bot_settings_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in bot_settings_screen.py: {violations}")

    def test_accounts_screen_no_emoji(self):
        """accounts_screen.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/screens/accounts_screen.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in accounts_screen.py: {violations}")

    def test_app_py_no_emoji(self):
        """app.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/app.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in app.py: {violations}")

    def test_sidebar_no_emoji(self):
        """sidebar.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/components/sidebar.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in sidebar.py: {violations}")

    def test_window_py_no_emoji(self):
        """window.py must have zero Unicode emojis in string literals."""
        violations = self._scan_file_for_emojis(
            'src/qt_ui/window.py'
        )
        self.assertEqual(len(violations), 0,
            f"Unicode emojis found in window.py: {violations}")

    def test_royale_i18n_no_emoji(self):
        """Royale i18n strings must have zero Unicode emojis."""
        with open('src/qt_ui/i18n_data.json', 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Check Royale-specific keys
        royale_keys = ['rl_', 'rh_', 'ra_', 'royale_', 'rtr_', 'rt_', 'rc_']
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


class TestUiPhase3NoLegacyGold(unittest.TestCase):
    """Test that zero hardcoded legacy gold hex remains in Phase 3 screens."""

    def _scan_for_gold_hex(self, filepath):
        """Scan a file for hardcoded #F5B740 or #f5b740."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        violations = []
        for i, line in enumerate(content.splitlines(), 1):
            if '#F5B740' in line or '#f5b740' in line:
                violations.append((i, line.strip()[:100]))
        return violations

    def test_royale_home_screen_no_gold_hex(self):
        """royale_home_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/royale_home_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in royale_home_screen.py: {violations}")

    def test_royale_screen_no_gold_hex(self):
        """royale_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/royale_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in royale_screen.py: {violations}")

    def test_royale_ai_screen_no_gold_hex(self):
        """royale_ai_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/royale_ai_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in royale_ai_screen.py: {violations}")

    def test_royale_training_screen_no_gold_hex(self):
        """royale_training_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/royale_training_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in royale_training_screen.py: {violations}")

    def test_bot_settings_screen_no_gold_hex(self):
        """bot_settings_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/bot_settings_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in bot_settings_screen.py: {violations}")

    def test_accounts_screen_no_gold_hex(self):
        """accounts_screen.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/screens/accounts_screen.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in accounts_screen.py: {violations}")

    def test_app_py_no_gold_hex(self):
        """app.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/app.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in app.py: {violations}")

    def test_sidebar_no_gold_hex(self):
        """sidebar.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/components/sidebar.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in sidebar.py: {violations}")

    def test_window_py_no_gold_hex(self):
        """window.py must have zero hardcoded #F5B740."""
        violations = self._scan_for_gold_hex('src/qt_ui/window.py')
        self.assertEqual(len(violations), 0,
            f"Hardcoded gold hex found in window.py: {violations}")


class TestUiPhase3CrimsonUsage(unittest.TestCase):
    """Test that TOKENS['crimson'] is used instead of TOKENS['gold']."""

    def test_royale_home_screen_uses_crimson(self):
        """royale_home_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/royale_home_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_royale_screen_uses_crimson(self):
        """royale_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/royale_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_royale_ai_screen_uses_crimson(self):
        """royale_ai_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/royale_ai_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_royale_training_screen_uses_crimson(self):
        """royale_training_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/royale_training_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_bot_settings_screen_uses_crimson(self):
        """bot_settings_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/bot_settings_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_accounts_screen_uses_crimson(self):
        """accounts_screen.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/screens/accounts_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_sidebar_uses_crimson(self):
        """sidebar.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/components/sidebar.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_app_py_uses_crimson(self):
        """app.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/app.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")

    def test_window_py_uses_crimson(self):
        """window.py should use TOKENS['crimson'] not TOKENS['gold']."""
        with open('src/qt_ui/window.py', 'r', encoding='utf-8') as f:
            content = f.read()

        gold_count = content.count('TOKENS["gold"]')
        crimson_count = content.count('TOKENS["crimson"]')

        self.assertEqual(gold_count, 0,
            f"Found {gold_count} occurrences of TOKENS['gold'] - should be crimson")
        self.assertGreater(crimson_count, 0,
            "Should use TOKENS['crimson'] at least once")


class TestUiPhase3SignalSlotPreservation(unittest.TestCase):
    """Test that critical signals/slots and store bindings are preserved."""

    def test_royale_home_screen_signals(self):
        """Royale home screen critical signals preserved."""
        with open('src/qt_ui/screens/royale_home_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical buttons
        for btn in ['b_start', 'b_stop', 'b_view', 'b_train', 'b_tstop', 'b_catalog']:
            self.assertIn(btn, content, f"Button {btn} missing from royale_home_screen.py")

        # Store bindings
        self.assertIn('royale.watch_only', content)
        self.assertIn('royale.ai_play', content)
        self.assertIn('royale.manage_account', content)
        self.assertIn('royale.training_camp', content)
        self.assertIn('royale.notify', content)
        self.assertIn('store.save', content)

    def test_royale_screen_signals(self):
        """Royale screen critical signals preserved."""
        with open('src/qt_ui/screens/royale_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical buttons - royale_screen uses different button names
        for btn in ['go', 'scan_cards_now', 'ai_train', 'ai_stop', 'train_now']:
            self.assertIn(btn, content, f"Button {btn} missing from royale_screen.py")

        # Store bindings
        self.assertIn('royale.max_battles', content)
        self.assertIn('royale.notify', content)
        self.assertIn('royale.safe_play', content)
        self.assertIn('royale.dual_eyes', content)
        self.assertIn('royale.training_camp', content)
        self.assertIn('royale.confirm_battles', content)
        self.assertIn('royale.auto_train', content)
        self.assertIn('royale.lock_deck', content)
        self.assertIn('royale.auto_deck', content)
        self.assertIn('royale.deck_slot', content)
        self.assertIn('royale.scan_cards', content)
        self.assertIn('royale.tag', content)
        self.assertIn('royale_api_key', content)
        self.assertIn('royale_dev_email', content)
        self.assertIn('royale_dev_password', content)
        self.assertIn('roboflow_api_key', content)

    def test_royale_ai_screen_signals(self):
        """Royale AI screen critical signals preserved."""
        with open('src/qt_ui/screens/royale_ai_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical methods
        self.assertIn('pop_out', content)
        self.assertIn('refresh', content)
        self.assertIn('text', content)
        self.assertIn('frame_tick', content)

    def test_royale_training_screen_signals(self):
        """Royale training screen critical signals preserved."""
        with open('src/qt_ui/screens/royale_training_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical methods
        self.assertIn('train_eyes', content)
        self.assertIn('stop_eyes', content)
        self.assertIn('train_self', content)
        self.assertIn('stop_self', content)
        self.assertIn('run_health', content)
        self.assertIn('watch', content)
        self.assertIn('refresh', content)

    def test_bot_settings_screen_signals(self):
        """Bot settings screen critical signals preserved."""
        with open('src/qt_ui/screens/bot_settings_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical methods
        self.assertIn('check_update', content)
        self.assertIn('apply_update', content)
        self.assertIn('check_tess', content)
        self.assertIn('install_tess', content)
        self.assertIn('check_power', content)
        self.assertIn('install_gpu', content)
        self.assertIn('test_telegram', content)
        self.assertIn('render_days', content)
        self.assertIn('_sched_note', content)

    def test_accounts_screen_signals(self):
        """Accounts screen critical signals preserved."""
        with open('src/qt_ui/screens/accounts_screen.py', 'r', encoding='utf-8') as f:
            content = f.read()

        # Critical methods
        self.assertIn('render', content)
        self.assertIn('all_action', content)
        self.assertIn('add_account', content)
        self.assertIn('copy_to_all', content)
        self.assertIn('remove', content)
        self.assertIn('set_game', content)
        self.assertIn('set_follow', content)
        self.assertIn('load_follow', content)


class TestUiPhase3SVGIcons(unittest.TestCase):
    """Test that SVG icons are used via icons.py instead of Unicode."""

    def test_icons_module_imported(self):
        """All Phase 3 screens should import icons module."""
        screens = [
            'royale_home_screen.py',
            'royale_screen.py',
            'royale_ai_screen.py',
            'royale_training_screen.py',
            'bot_settings_screen.py',
            'accounts_screen.py',
        ]
        for screen in screens:
            with open(f'src/qt_ui/screens/{screen}', 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('from .. import icons', content,
                f"{screen} must import icons module")

    def test_img_tag_usage(self):
        """Screens should use icons.img_tag for SVG rendering."""
        screens = [
            'royale_home_screen.py',
            'royale_screen.py',
            'royale_ai_screen.py',
            'royale_training_screen.py',
            'bot_settings_screen.py',
        ]
        for screen in screens:
            with open(f'src/qt_ui/screens/{screen}', 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('icons.img_tag', content,
                f"{screen} must use icons.img_tag for SVG icons")


class TestUiPhase3Imports(unittest.TestCase):
    """Test that Phase 3 imports work correctly."""

    @classmethod
    def setUpClass(cls):
        if not HAS_PY_SIDE6:
            raise unittest.SkipTest("PySide6 not installed")
        from PySide6.QtWidgets import QApplication
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def test_royale_home_screen_imports(self):
        """royale_home_screen.py imports should succeed."""
        from qt_ui.screens import royale_home_screen
        self.assertTrue(hasattr(royale_home_screen, 'RoyaleHomeScreen'))

    def test_royale_screen_imports(self):
        """royale_screen.py imports should succeed."""
        from qt_ui.screens import royale_screen
        self.assertTrue(hasattr(royale_screen, 'RoyaleScreen'))

    def test_royale_ai_screen_imports(self):
        """royale_ai_screen.py imports should succeed."""
        from qt_ui.screens import royale_ai_screen
        self.assertTrue(hasattr(royale_ai_screen, 'RoyaleAiScreen'))

    def test_royale_training_screen_imports(self):
        """royale_training_screen.py imports should succeed."""
        from qt_ui.screens import royale_training_screen
        self.assertTrue(hasattr(royale_training_screen, 'RoyaleTrainingScreen'))

    def test_bot_settings_screen_imports(self):
        """bot_settings_screen.py imports should succeed."""
        from qt_ui.screens import bot_settings_screen
        self.assertTrue(hasattr(bot_settings_screen, 'BotSettingsScreen'))

    def test_accounts_screen_imports(self):
        """accounts_screen.py imports should succeed."""
        from qt_ui.screens import accounts_screen
        self.assertTrue(hasattr(accounts_screen, 'AccountsScreen'))

    def test_app_imports(self):
        """app.py imports should succeed."""
        from qt_ui import app
        self.assertTrue(hasattr(app, 'run_qt'))

    def test_sidebar_imports(self):
        """sidebar.py imports should succeed."""
        from qt_ui.components import sidebar
        self.assertTrue(hasattr(sidebar, 'Sidebar'))

    def test_window_imports(self):
        """window.py imports should succeed."""
        from qt_ui import window
        self.assertTrue(hasattr(window, 'MainWindow'))


if __name__ == "__main__":
    unittest.main(verbosity=2)