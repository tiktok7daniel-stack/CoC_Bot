"""Offline checks for the catalogue, copy payload and replay evidence."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gui_server.gui_server import app
from royale import catalog_selection, deck_catalog as catalog, replay_evidence as evidence


class DeckCatalogTests(unittest.TestCase):
    def test_featured_forms_copy_and_ownership(self):
        deck = catalog.lookup(catalog.FEATURED_ID)
        self.assertEqual(len(set(deck["card_ids"])), 8)
        self.assertEqual(set(deck["image_urls"]), set(deck["cards"]))
        self.assertIn("26000107", deck["copy_url"])
        self.assertEqual(catalog.prepare_copy(deck["id"], [])["error"], "cards_not_owned")
        self.assertEqual(catalog.prepare_copy(deck["id"], deck["card_ids"])["required_forms"],
                         ["cannon-ev1", "ice-wizard-hero", "bats-ev1"])

    def test_catalog_api_filters_and_pages(self):
        with app.test_client() as client:
            data = client.get("/api/royale/deck-catalog?limit=1").get_json()
            self.assertGreater(data["total"], 2000)
            self.assertEqual([entry["id"] for entry in data["items"]], [catalog.FEATURED_ID])
            self.assertEqual(client.get("/api/royale/deck-catalog?q=not-a-real-deck").get_json()["total"], 0)
            self.assertEqual(client.get("/api/royale/deck-catalog/no-such-id").status_code, 404)
            archived = client.get("/api/royale/deck-catalog?offset=1&limit=1").get_json()["items"][0]
            self.assertLessEqual(archived["win_rate"], 1.0)
            self.assertFalse(archived["forms_known"])


class ReplayEvidenceTests(unittest.TestCase):
    def test_positions_and_first_candidate(self):
        def play(i, t, side, card, x, y):
            return dict(kind="play_card", event_index=i, time_seconds=t, side=side, card_key=card,
                        grid_x=x, grid_y=y)

        rows = [play(1, 0, "team", "hog-rider", 14, 13),
                play(2, 1.5, "opponent", "cannon", 9, 22),
                play(3, 2.1, "opponent", "knight", 14, 25),
                play(4, 3.0, "team", "invalid", 18, 20)]
        candidate, = evidence.responses(reversed(rows), "opponent")
        self.assertEqual(candidate["attack_tile"], [3, 18])
        self.assertEqual(candidate["reply_tile"], [8, 9])
        self.assertEqual(candidate["delay_s"], 1.5)
        self.assertEqual(candidate["geometry"], "center")

    def test_reverse_perspectives_count_once(self):
        featured = {"tag": "#A", "crowns": 2, "cards": [
            {"name": c.removesuffix("-ev1").removesuffix("-hero"),
             "evolutionLevel": 1 if c.endswith("-ev1") else 2 if c.endswith("-hero") else 0}
            for c, _ in catalog.FEATURED_CARDS
        ]}
        opponent = {"tag": "#B", "crowns": 1, "cards": [{"name": f"card{i}"} for i in range(8)]}
        rows = [dict(battleTime="20261125", type="pathOfLegend", team=[a], opponent=[b])
                for a, b in [(featured, opponent), (opponent, featured)]]
        result, = evidence.official_matchups(rows, [c for c, _ in catalog.FEATURED_CARDS])
        self.assertEqual((result["games"], result["wins"]), (1, 1))


class SelectionTests(unittest.TestCase):
    def test_per_account_selection_and_status(self):
        with TemporaryDirectory() as tmp, patch.object(catalog_selection, "DIR", Path(tmp)), \
                patch("gui_server.gui_server.valid_id", return_value=True), app.test_client() as client:
            path = "/api/royale/deck-selection/test-a"
            response = client.post(path, json={"id": catalog.FEATURED_ID, "slot": 2})
            self.assertEqual(response.status_code, 200)
            selected = response.json["selection"]
            self.assertEqual(client.get(path).json["status"]["state"], "pending")
            self.assertFalse(client.get("/api/royale/deck-selection/test-b").json["selection"])
            catalog_selection.report("test-a", selected, "blocked", "unsupported_cards")
            self.assertEqual(client.get(path).json["status"]["reason"], "unsupported_cards")
            self.assertEqual(client.post(path, json={"id": "", "slot": 11}).status_code, 400)
            self.assertEqual(client.post(path, json={"id": "", "slot": 0}).status_code, 200)
            self.assertEqual(client.get(path).json["status"]["state"], "none")

    def test_copy_only_unblocks_after_api_verification(self):
        from royale.brain import cards_db
        from royale import cr_api, deck_pick

        entry = next(d for d in catalog.page("hogrider", limit=100)["items"]
                     if set(d["cards"]) == {"cannon", "fireball", "hogrider", "icegolem", "icespirit",
                                            "musketeer", "skeletons", "thelog"})
        eyes = SimpleNamespace(by_name={name: SimpleNamespace(id=c["id"]) for name, c in cards_db().items()
                                       if c.get("id") in entry["card_ids"]})
        cards = [{"id": ident} for ident in entry["card_ids"]]
        before, after = {"cards": cards}, {"cards": cards, "currentDeck": cards}
        picked = {"id": entry["id"], "slot": 3, "revision": "rev"}
        with patch.object(catalog_selection, "selection", return_value=picked), \
                patch.object(cr_api, "tag", return_value="#TEST"), \
                patch.object(cr_api, "fetch", side_effect=[before, after]), \
                patch.object(deck_pick, "apply", return_value=True) as copy:
            names, error = catalog_selection.activate("test", picked, eyes, None)
            self.assertEqual((len(names), error), (8, ""))
            copy.assert_called_once_with("test", {"ids": entry["card_ids"]}, None, 3, strict_slot=True)
        with patch.object(deck_pick, "apply") as copy:
            self.assertEqual(catalog_selection.activate("test", dict(picked, id=catalog.FEATURED_ID), eyes, None),
                             ([], "unsupported_cards"))
            copy.assert_not_called()

    def test_featured_requires_equipped_forms(self):
        deck = catalog.lookup(catalog.FEATURED_ID)
        cards = [{"id": ident, "name": key.split("-ev1")[0].removesuffix("-hero"),
                  "evolutionLevel": 1 if key.endswith("-ev1") else 2 if key.endswith("-hero") else 0}
                 for key, ident in catalog.FEATURED_CARDS]
        self.assertTrue(catalog_selection.verified({"currentDeck": cards}, deck))
        cards[1]["evolutionLevel"] = 0
        self.assertFalse(catalog_selection.verified({"currentDeck": cards}, deck))


if __name__ == "__main__":
    unittest.main()
