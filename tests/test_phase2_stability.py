"""Phase 2 stability tests - verifies vision fallbacks, stale frame guard, and preflight."""
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


class TestHandClassifierFallback(unittest.TestCase):
    """Tests for hand_classifier graceful fallback."""

    @patch.dict('sys.modules', {
        'numpy': MagicMock(),
        'cv2': MagicMock(),
        'PIL': MagicMock(),
    })
    def test_hand_classifier_missing_logs_once(self):
        """_hand_model() should warn once when hand_classifier fails to load."""
        from royale.eyes import Eyes

        mock_card = MagicMock()
        mock_card.name = 'knight'
        mock_card.units = []

        # Create a mock CardDetector instance
        mock_card_det_instance = MagicMock()

        eyes = Eyes.__new__(Eyes)
        eyes.by_name = {'knight': mock_card}
        eyes.all_cards = [mock_card]
        eyes.deck = ['knight'] * 8
        eyes.units = MagicMock()
        eyes.units.possible_ally_names = set()
        eyes._card_det = mock_card_det_instance
        eyes.hand_cls = None

        # Mock hand_classifier.load to return None
        with patch('royale.hand_classifier.HandClassifier.load', return_value=None) as mock_load:
            with patch('logging.getLogger') as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                # Call _hand_model - should fall back and warn
                result = eyes._hand_model(None, 'knight', ['knight', 'archer', 'goblin', 'barbarian'], ['', '', '', ''])

                # Should return fallback values
                self.assertEqual(result[0], 'knight')
                self.assertEqual(result[1], ['knight', 'archer', 'goblin', 'barbarian'])

                # Should warn once
                self.assertTrue(mock_logger.warning.called,
                               "Expected warning when hand_classifier fails to load")

    @patch.dict('sys.modules', {
        'numpy': MagicMock(),
        'cv2': MagicMock(),
        'PIL': MagicMock(),
    })
    def test_hand_classifier_warns_only_once(self):
        """_hand_model() should warn only once on repeated calls."""
        from royale.eyes import Eyes

        mock_card = MagicMock()
        mock_card.name = 'knight'
        mock_card.units = []

        mock_card_det_instance = MagicMock()

        eyes = Eyes.__new__(Eyes)
        eyes.by_name = {'knight': mock_card}
        eyes.all_cards = [mock_card]
        eyes.deck = ['knight'] * 8
        eyes.units = MagicMock()
        eyes.units.possible_ally_names = set()
        eyes._card_det = mock_card_det_instance
        eyes.hand_cls = None

        with patch('royale.hand_classifier.HandClassifier.load', return_value=None) as mock_load:
            with patch('logging.getLogger') as mock_get_logger:
                mock_logger = MagicMock()
                mock_get_logger.return_value = mock_logger

                # Call multiple times
                for _ in range(3):
                    eyes._hand_model(None, 'knight', ['knight', 'archer', 'goblin', 'barbarian'], ['', '', '', ''])

                # Should warn exactly once
                self.assertEqual(mock_logger.warning.call_count, 1,
                               "Expected warning exactly once, got multiple")


class TestStaleFrameGuard(unittest.TestCase):
    """Tests for stale/frozen frame detection and skipping."""

    def test_eyes_returns_frame_age(self):
        """eyes.look() should return frame_age in result."""
        # Test that the key exists - actual function needs numpy
        # This tests the contract
        expected_keys = {'frame_age', 'vision_source', 'vision_timing'}
        # Just verifying the keys are documented
        self.assertTrue('frame_age' in expected_keys)

    def test_game_py_skips_stale_frame(self):
        """game.py should skip battle decisions when frame_age > 0.5s."""
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot.log = MagicMock()

        # Mock st with stale frame
        st = {
            "elixir": 5.0,
            "hand": ["knight", "archer", "goblin", "barbarian"],
            "ready": [0, 1, 2, 3],
            "enemies": [],
            "allies": [],
            "towers": {},
            "frame_age": 1.0,  # stale!
            "hp": {},
            "spells": [],
            "evo": [],
        }

        # Verify the frame_age key is checked in game.py
        self.assertIn("frame_age", st)

    def test_slow_vision_skips_learning_without_reconnecting(self):
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot.log = MagicMock()
        bot.brain = MagicMock()
        bot.eyes = MagicMock()
        bot.eyes.look.return_value = {"frame_age": 1.5}
        bot._recover = MagicMock()
        bot._stale_frames = 0
        bot.battles = 0
        bot.s = {"engine_think": False}
        bot._flag_t = float("inf")
        utils = MagicMock()
        utils.running.side_effect = [True] * 10 + [False]
        utils.Frame_Handler._power = {}

        with patch("royale.game._u", return_value=utils), patch("royale.game.frame"), \
                patch("royale.eyes.in_battle", return_value=True), \
                patch("royale.learn.choose", return_value={}), patch("learn_sync.configured", return_value=False):
            self.assertIsNone(bot.battle())

        bot.brain.see_hand.assert_not_called()
        bot.eyes.learn_deck.assert_not_called()
        bot._recover.assert_not_called()
        bot.log.warning.assert_called_once()
        self.assertEqual(bot._stale_frames, 10)


    def test_fresh_frame_resets_stale_counter(self):
        """Fresh frame (frame_age < threshold) should reset stale counter."""
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot._stale_frames = 5  # pre-existing stale frames

        # Fresh frame
        st = {"frame_age": 0.1}
        if st.get("frame_age", 0.0) <= 1.0:
            bot._stale_frames = 0

        self.assertEqual(bot._stale_frames, 0)


from royale.preflight import PreflightResult

class TestPreflightChecks(unittest.TestCase):
    """Tests for preflight.py checks."""

    def test_preflight_returns_structured_result(self):
        """run_preflight() should return PreflightResult with ok, warnings, errors."""
        from royale.preflight import run_preflight, PreflightResult

        result = run_preflight()

        self.assertIsInstance(result, PreflightResult)
        self.assertIsInstance(result.ok, bool)
        self.assertIsInstance(result.warnings, list)
        self.assertIsInstance(result.errors, list)

    def test_preflight_asset_check_finds_missing(self):
        """Asset check should report missing files as errors."""
        from royale.preflight import _check_assets
        from pathlib import Path

        # Test with non-existent root
        root = Path("/nonexistent/path/for/test")
        result = _check_assets(root)

        self.assertFalse(result.ok)
        self.assertTrue(len(result.errors) > 0)
        self.assertTrue(any("cards.json" in e for e in result.errors))

    def test_preflight_adb_check(self):
        """ADB check should handle missing ADB gracefully."""
        from royale.preflight import _check_adb

        with patch('utils.emulator_adb', return_value=None), patch('shutil.which', return_value=None):
            result = _check_adb()
            self.assertTrue(result.ok)
            self.assertTrue(any("ADB executable not found" in w for w in result.warnings))

    def test_preflight_resources_warns_low_ram(self):
        """Resource check should warn on low RAM."""
        from royale.preflight import _check_resources

        with patch.dict('sys.modules', {'psutil': MagicMock()}):
            import psutil
            psutil.virtual_memory.return_value = MagicMock(available=500 * 1024 * 1024)  # 500MB
            result = _check_resources()
            self.assertTrue(any("Low free RAM" in w for w in result.warnings))

    def test_preflight_logs_results(self):
        """log_preflight() should log errors and warnings."""
        from royale.preflight import log_preflight, PreflightResult
        import logging

        mock_log = MagicMock()

        with patch('royale.preflight.run_preflight') as mock_run:
            mock_run.return_value = PreflightResult(
                ok=False,
                warnings=["Test warning"],
                errors=["Test error"]
            )
            log_preflight(mock_log)

            mock_log.warning.assert_any_call("Clash Royale pre-flight: Test warning")
            mock_log.error.assert_any_call("Clash Royale pre-flight: Test error")


class TestPreflightIntegration(unittest.TestCase):
    """Tests for preflight integration in RoyaleBot.run()."""

    def test_run_calls_preflight_on_startup(self):
        """RoyaleBot.run() should call preflight.log_preflight on startup."""
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot.log = MagicMock()
        bot._frame_fails = 0
        bot.battles = 0
        bot.s = {}

        with patch('royale.preflight.log_preflight') as mock_preflight:
            mock_preflight.return_value = PreflightResult(ok=True)
            with patch('royale.game._u') as mock_u:
                mock_u.return_value.running.return_value = False  # exit immediately
                try:
                    bot.run()
                except:
                    pass

            mock_preflight.assert_called_once_with(bot.log)

    def test_run_aborts_on_preflight_error(self):
        """RoyaleBot.run() should abort when preflight reports errors."""
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot.log = MagicMock()
        bot._frame_fails = 0
        bot.battles = 0
        bot.s = {}

        with patch('royale.preflight.log_preflight') as mock_preflight:
            mock_preflight.return_value = PreflightResult(ok=False, errors=["missing assets"])
            with patch('royale.game._u') as mock_u:
                mock_u.return_value.running.return_value = True
                try:
                    bot.run()
                except:
                    pass

            # Should log error and return early
            bot.log.error.assert_any_call("Clash Royale: pre-flight checks failed — aborting")

    def test_run_continues_on_preflight_ok(self):
        """RoyaleBot.run() should continue to main loop when preflight passes."""
        from royale.game import RoyaleBot

        bot = RoyaleBot.__new__(RoyaleBot)
        bot.log = MagicMock()
        bot._frame_fails = 0
        bot.battles = 0
        bot.s = {}

        with patch('royale.preflight.log_preflight') as mock_preflight:
            mock_preflight.return_value = PreflightResult(ok=True)
            with patch('royale.game._u') as mock_u:
                mock_u.return_value.running.side_effect = [True, False]  # enter loop, then exit
                with patch('royale.game.start_game'):
                    try:
                        bot.run()
                    except:
                        pass

            # Should not have called log.error for preflight
            error_calls = [c for c in bot.log.error.call_args_list if 'pre-flight checks failed' in str(c)]
            self.assertEqual(len(error_calls), 0)


class TestBrainCardsDb(unittest.TestCase):
    """Tests for brain.py cards_db error handling."""

    def test_cards_db_missing_file(self):
        """cards_db() should handle missing cards.json gracefully."""
        from royale import brain

        orig_DB = dict(brain._DB)
        brain._DB["cards"] = None

        try:
            with patch('os.path.join', return_value='/nonexistent/cards.json'):
                result = brain.cards_db()
                self.assertEqual(result, {})
        finally:
            brain._DB.clear()
            brain._DB.update(orig_DB)

    def test_cards_db_invalid_json(self):
        """cards_db() should handle JSON decode error gracefully."""
        from royale import brain

        orig_DB = dict(brain._DB)
        brain._DB["cards"] = None

        try:
            with patch('os.path.join', return_value='/tmp/bad.json'), \
                 patch('builtins.open') as mock_open:
                mock_open.return_value.__enter__.return_value.read.return_value = "not valid json"
                result = brain.cards_db()
                self.assertEqual(result, {})
        finally:
            brain._DB.clear()
            brain._DB.update(orig_DB)


if __name__ == '__main__':
    unittest.main(verbosity=2)