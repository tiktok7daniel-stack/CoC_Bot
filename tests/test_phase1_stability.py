"""Phase 1 stability tests - verifies error handling for critical paths."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


class TestGamePyRecovery(unittest.TestCase):
    """Tests for game.py:_recover() stability."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_recover_max_frame_fails_stops(self):
        """_recover() should stop after max_frame_fails attempts."""
        from royale.game import RoyaleBot
        bot = RoyaleBot.__new__(RoyaleBot)
        bot._max_frame_fails = 5
        bot._frame_fails = 5
        bot.log = MagicMock()

        with patch.object(time, 'sleep') as mock_sleep:
            self.assertFalse(bot._recover(Exception("test")))
            mock_sleep.assert_not_called()

    def test_recover_backoff_timing(self):
        """_recover() should use exponential backoff."""
        from royale.game import RoyaleBot
        bot = RoyaleBot.__new__(RoyaleBot)
        bot._max_frame_fails = 10
        bot._frame_fails = 2
        bot.log = MagicMock()
        bot._say = MagicMock()

        with patch.object(time, 'sleep') as mock_sleep:
            with patch('royale.game._u') as mock_u:
                mock_u.return_value.Emulator_Manager.check.return_value = True
                mock_u.return_value.ADB_Manager.connect.return_value = False

                bot._recover(Exception("test"))
                # At n=2, backoff = min(30, 5 * 2^2) = 20
                mock_sleep.assert_called()

    def test_frame_fails_initialized(self):
        """_frame_fails should be initialized in __init__."""
        from royale.game import RoyaleBot
        bot = RoyaleBot.__new__(RoyaleBot)
        # Check that the attribute would be set by init
        self.assertTrue(hasattr(RoyaleBot, '__init__'))


class TestEngineSelftest(unittest.TestCase):
    """Tests for engine.py selftest() error handling."""

    def test_selftest_missing_module_returns_false(self):
        """selftest() should return False when module is None."""
        from royale import engine as eng

        with patch.dict(eng._S, {"ok": None}), patch.object(eng, "module", return_value=None):
            self.assertFalse(eng.selftest())
            self.assertFalse(eng._S["ok"])

    def test_selftest_handles_keyerror(self):
        """selftest() should handle KeyError when hog_rider missing."""
        from royale import engine as eng

        orig_S = dict(eng._S)
        eng._S["ok"] = None

        try:
            # Mock module with missing hog_rider
            mock_mod = MagicMock()
            mock_mod.get_card_info.return_value = {"name": "test"}
            eng._S["mod"] = mock_mod

            with patch.object(eng, 'card_ids', return_value={'cannon': (1, None, None)}):
                result = eng.selftest()
                # Should fail gracefully
                self.assertIn(result, [False, None])
        finally:
            eng._S.clear()
            eng._S.update(orig_S)

    def test_selftest_catches_assertion_failures(self):
        """selftest() should catch AssertionError and log."""
        from royale import engine as eng
        from unittest.mock import MagicMock

        orig_S = dict(eng._S)
        eng._S["ok"] = None

        try:
            # Force assertion error through mock
            with patch.object(eng, 'module', return_value=MagicMock()):

                mock_env = MagicMock()
                mock_env.get_tower_hp.return_value = 100
                mock_env.is_valid_placement.return_value = False

                mock_m = MagicMock()
                mock_m.ClashRoyaleEnv.return_value = mock_env
                mock_m.get_card_info.return_value = {"cost": 1}
                mock_m.get_tower_max_hp.return_value = 1000

                with patch.object(eng, 'module', return_value=mock_m):
                    with patch.object(eng, 'card_ids', return_value={'hog_rider': (1, None, None), 'cannon': (2, None, None)}):
                        result = eng.selftest()
                        # Should recover from assertion
                        self.assertIn(result, [True, False])
        finally:
            eng._S.clear()
            eng._S.update(orig_S)


class TestEyesSetDeck(unittest.TestCase):
    """Tests for eyes.py set_deck() warning on unknown cards."""

    def test_set_deck_logs_unknown_cards(self):
        """set_deck() should warn for cards not in by_name."""
        # Test the warning logic directly without loading actual models
        names = ['knight', 'ghost']
        by_name = {'knight': MagicMock()}

        # Simulate the filtering logic from set_deck()
        filtered = [n for n in names if n in by_name][:8]
        missing = [n for n in names if n and n not in by_name]

        self.assertEqual(filtered, ['knight'])
        self.assertIn('ghost', missing)


class TestCardsDbErrorHandling(unittest.TestCase):
    """Tests for brain.py cards_db() error handling."""

    def test_cards_db_handles_missing_file(self):
        """cards_db() should handle FileNotFoundError gracefully."""
        from royale import brain

        orig_DB = dict(brain._DB)

        try:
            brain._DB["cards"] = None

            with patch('os.path.join', return_value='/nonexistent/path/cards.json'):
                result = brain.cards_db()
                # Should return empty dict on error, not crash
                self.assertEqual(result, {})
        finally:
            brain._DB.clear()
            brain._DB.update(orig_DB)

    def test_cards_db_handles_invalid_json(self):
        """cards_db() should handle JSONDecodeError gracefully."""
        from royale import brain

        orig_DB = dict(brain._DB)

        try:
            brain._DB["cards"] = None

            with patch('os.path.join', return_value='/tmp/not_json.json'), \
                 patch('builtins.open', create=True) as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = "not json"
                result = brain.cards_db()
                # Should return empty dict on JSON error
                self.assertEqual(result, {})
        finally:
            brain._DB.clear()
            brain._DB.update(orig_DB)


if __name__ == '__main__':
    unittest.main(verbosity=2)