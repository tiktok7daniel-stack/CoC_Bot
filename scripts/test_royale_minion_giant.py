"""Offline checks for the Minion Giant template and approximate battle model."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image
from royale.brain import card, roles, unit_card
from royale.sim import U, level_mult, step
from royale.vision.constants import CARD_CONFIG, SCREENSHOT_HEIGHT, SCREENSHOT_WIDTH
from royale.vision.detectors.card_detector import CardDetector
from royale.vision.namespaces.cards import Cards
from royale.vision.namespaces.units import Target, Transport


class MinionGiantTests(unittest.TestCase):
    def test_reference_is_read_in_a_controlled_hand(self):
        cards = [Cards.MINION_GIANT, Cards.HOG_RIDER, Cards.KNIGHT, Cards.CANNON, Cards.FIREBALL]
        frame = Image.new("RGB", (SCREENSHOT_WIDTH, SCREENSHOT_HEIGHT))
        for c, (x0, y0, x1, y1) in zip(cards, CARD_CONFIG):
            with Image.open(ROOT / "assets" / "royale" / "cards" / f"{c.name}.jpg") as art:
                frame.paste(art.resize((x1 - x0, y1 - y0)), (x0, y0))
        recognized, _ = CardDetector(cards).run(frame)
        self.assertEqual([c.name for c in recognized], [c.name for c in cards])
        self.assertEqual(Cards.MINION_GIANT.id_, 26000107)
        self.assertEqual(Cards.MINION_GIANT.units[0].target, Target.BUILDINGS)
        self.assertEqual(Cards.MINION_GIANT.units[0].transport, Transport.AIR)

    def test_simulated_unit_ignores_troops_and_hits_buildings(self):
        stats = card("minion_giant")
        self.assertEqual(unit_card("minion_giant"), "minion_giant")
        self.assertIn("win", roles("minion_giant"))
        self.assertAlmostEqual(stats["damage"] * level_mult(11), 153)
        giant = U("minion_giant", "us", 8, 14, stats)
        knight = U("knight", "them", 8, 15, card("knight"))
        cannon = U("cannon", "them", 8, 17, card("cannon"))
        self.assertTrue(giant.air and giant.bonly)
        self.assertFalse(knight.can_hit(giant))
        step([giant, knight, cannon])
        self.assertEqual(knight.hp, knight.hp0)
        self.assertLess(cannon.hp, cannon.hp0)
        self.assertAlmostEqual(giant.cd, 1.7)


if __name__ == "__main__":
    unittest.main()
