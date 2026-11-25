"""Verify the offline audit uses only previous placements to estimate the hand."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from royale import replay_benchmark as audit
from royale.sim import Arena

DECK = ["skeletons", "ice-spirit", "the-log", "ice-golem", "cannon", "fireball", "musketeer", "hog-rider"]


def sample():
    battle = {s: {"players": [{"deck": [{"card_key": c} for c in DECK]}]}
              for s in ("team", "opponent")}
    events = [dict(kind="play_card", side="opponent", time_seconds=i * 5.0, event_index=i,
                   card_key=key, grid_x=12, grid_y=22) for i, key in enumerate(DECK[:5])]
    return {"battle": battle, "actions": events}


class ReplayTests(unittest.TestCase):
    def test_inferred_hand_and_perspective(self):
        with patch.object(audit._ClockBrain, "decide", return_value=None):
            result = audit.evaluate(sample(), "opponent")
        self.assertEqual(result["summary"]["cycle_unknown"], 4)
        self.assertEqual(result["summary"]["compared"], 1)
        row, = result["decisions"]
        self.assertEqual(row["reference"], {"card": "cannon", "tile": [5, 9]})
        self.assertEqual(set(row["inferred_hand"]), {"cannon", "fireball", "musketeer", "hog_rider"})
        self.assertIsNone(row["proposal"])

    def test_invalid_placements_and_unsupported_cards(self):
        bad = sample()
        bad["actions"][0]["grid_x"] = -1
        self.assertEqual(audit.evaluate(bad, "team")["reason"], "incomplete_or_invalid_placements")
        unknown = sample()
        unknown["battle"]["team"]["players"][0]["deck"][-1]["card_key"] = "minion-giant"
        self.assertEqual(audit.evaluate(unknown, "team")["reason"], "unsupported_cards")

    def test_simulation_clock_stops_at_event(self):
        arena = Arena()
        arena.run_to(0.05, dt=0.4)
        self.assertAlmostEqual(arena.t, 0.05)
        arena.run_to(0.52, dt=0.4)
        self.assertAlmostEqual(arena.t, 0.52)


if __name__ == "__main__":
    unittest.main()
