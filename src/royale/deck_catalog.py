"""Deck identities, copy links and statistics used by the desktop deck catalogue."""
from functools import lru_cache

from royale import cr_api, deck_pick, pro

FEATURED_ID = "evo-cannon-evo-bats-3-cycle"
FEATURED_CARDS = (
    ("cannon-ev1", 27000000), ("ice-wizard-hero", 26000023), ("bats-ev1", 26000049),
    ("barbarian-barrel", 28000015), ("knight", 26000000), ("lightning", 28000007),
    ("minion-giant", 26000107), ("skeletons", 26000010),
)
FEATURED_SOURCE = ("https://royaleapi.com/decks/stats/"
                   "barbarian-barrel,bats-ev1,cannon-ev1,ice-wizard-hero,knight,lightning,minion-giant,skeletons")
FEATURED_STATS_SOURCE = "https://royaleapi.com/decks/popular?time=7d&type=TopRanked"
ICON_ROOT = "https://api-assets.clashroyale.com/"
FEATURED_ICONS = (
    "cardevolutions/300/nZK1y-beLxO5vnlyUhK6-2zH2NzXJwqykcosqQ1cmZ8.png",
    "cardheroes/300/W3dkw0HTw9n1jB-zbknY2w3wHuyuLxSRIAV5fUT1SEY.png",
    "cardevolutions/300/EnIcvO21hxiNpoI-zO6MDjLmzwPbq8Z4JPo2OKoVUjU.png",
    "cards/300/Gb0G1yNy0i5cIGUHin8uoFWxqntNtRPhY_jeMXg7HnA.png",
    "cards/300/jAj1Q5rclXxU9kVImGqSJxa4wEMfEhvwNQ_4jiGUuqg.png",
    "cards/300/fpnESbYqe5GyZmaVVYe-SEu7tE0Kxh_HZyVigzvLjks.png",
    "cards/300/VRjL0yVLzrnoe-IBh2l2fDHDok0L-UoM9cG-X_8xbMk.png",
    "cards/300/oO7iKMU5m0cdxhYPZA3nWQiAUh2yoGgdThLWB1rVSec.png",
)
# IDs verified in the official battle log. This mapping does not establish simulator support.
EXTRA_CARD_IDS = {"void": 28000023, "runegiant": 26000101, "spiritempress": 28000025}
UNVERIFIED_ARENA = {"miniongiant"}


def variant_key(name):
    """Keep the equipped form in the identity and normalize spelling."""
    name = str(name or "").lower().replace("_", "-")
    for suffix in ("-ev1", "-ev2", "-hero"):
        if name.endswith(suffix):
            return cr_api.key_of(name[:-len(suffix)]) + suffix
    return cr_api.key_of(name)


def signature(cards):
    return tuple(sorted(variant_key(c) for c in cards))


def unverified_arena_cards(cards):
    return [c for c in cards if variant_key(c).split("-", 1)[0] in UNVERIFIED_ARENA]


def api_card_variant(card):
    """Used form in a Clash Royale battle log card entry."""
    name = card.get("name")
    level = card.get("evolutionLevel", 0)
    return variant_key(name) + {1: "-ev1", 2: "-hero"}.get(level, "")


def _entry(deck_id, name, cards, card_ids, games, win_rate, source, forms_known):
    return {"id": deck_id, "name": name, "cards": list(cards), "card_ids": card_ids,
            "games": games, "win_rate": win_rate, "source": source, "forms_known": forms_known,
            "unverified_arena_cards": unverified_arena_cards(cards),
            "copy_url": deck_pick.deck_link(card_ids, scheme=False) if card_ids else None}


@lru_cache(maxsize=1)
def _catalogue():
    from royale.brain import cards_db
    db = {cr_api.key_of(key): value for key, value in cards_db().items()}
    cards, ids = zip(*FEATURED_CARDS)
    out = [_entry(FEATURED_ID, "EvoCannon Evo Bats 3.0 Cycle", cards, list(ids),
                  35505, 0.523, FEATURED_SOURCE, True)]
    out[0].update(stats_source=FEATURED_STATS_SOURCE, captured_on="2026-11-25",
                  image_urls=dict(zip(cards, (ICON_ROOT + link for link in FEATURED_ICONS))),
                  unsupported_cards=[key for key in cards if variant_key(key).split("-")[0] not in db])
    for row in pro.wins().get("decks", []):
        keys = row.get("cards", [])
        if len(keys) != 8 or len(set(keys)) != 8 or not all(keys):
            continue
        ids = [db.get(key, {}).get("id") or EXTRA_CARD_IDS.get(key) for key in keys]
        label = " / ".join(db.get(key, {}).get("name") or key for key in keys[:3])
        games, wins = row.get("n"), row.get("w")
        rate = wins / games if games and isinstance(wins, (int, float)) else None
        out.append(_entry("archive:" + "+".join(sorted(keys)), label, keys,
                          ids if all(ids) and len(set(ids)) == 8 else None,
                          games, rate, "IL_Replay summary", False))
    return tuple(out)


def page(query="", offset=0, limit=50):
    query = query.casefold().strip()
    matches = [row for row in _catalogue() if not query
               or query in row["name"].casefold() or any(query in c.casefold() for c in row["cards"])]
    return {"total": len(matches), "offset": offset, "items": matches[offset:offset + limit]}


def lookup(deck_id):
    return next((row for row in _catalogue() if row["id"] == deck_id), None)


def prepare_copy(deck_id, owned_ids=None):
    """Prepare the existing in-game copy path. No emulator action takes place here."""
    entry = lookup(deck_id)
    if not entry:
        return {"ok": False, "error": "unknown_deck"}
    ids = entry["card_ids"]
    if not ids:
        return {"ok": False, "error": "unknown_card_ids"}
    if owned_ids is not None:
        missing = sorted(set(ids).difference(owned_ids))
        if missing:
            return {"ok": False, "error": "cards_not_owned", "missing_ids": missing}
    return {"ok": True, "deck": entry, "ids": ids, "copy_url": entry["copy_url"],
            "required_forms": [c for c in entry["cards"] if c.endswith(("-ev1", "-ev2", "-hero"))]}
