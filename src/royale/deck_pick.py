"""
The bot picks its own deck: the strongest deck you can play with the cards you own, and puts it in the game.

  1. your cards and their levels      official API (royale.cr_api.player): every card you own, its level
  2. the decks that win right now     the best players' newest battles (royale.cr_api.build_meta): each deck, how
                                      often it is played and how often it wins
  3. the choice                       only decks you own all 8 cards of; score = win rate (more battles = surer)
                                      + your levels in it (a deck you have high levels in wins more for you)
                                      + a little for decks a bot plays well (cheap cycle decks, one clear win
                                      condition) and for the deck you play now (no change for nothing)
  4. into the game                    the game's own "copy deck" link (the one RoyaleAPI's Copy buttons use):
                                      opened in the emulator, the game asks to copy it into the deck slot that is
                                      selected — the bot taps Copy / OK (never anything that costs gems)

Nothing is bought, only a deck slot changes. The slot it uses: Settings -> "the bot's deck slot" (0 = the one that
is selected in the game).
"""
import json, time
from pathlib import Path

STATE = Path.home() / ".CoC_Bot" / "royale_api" / "deck_pick.json"
WIN_CONDITIONS = {"hogrider", "giant", "golem", "royalgiant", "balloon", "goblinbarrel", "miner", "graveyard", "xbow",
                  "mortar", "lavahound", "ramrider", "battleram", "electrogiant", "goblingiant", "royalhogs",
                  "wallbreakers", "goblindrill", "elixirgolem", "threemusketeers", "sparky", "pekka", "megaknight"}


def _std_level(level, max_level):
    """The API's level is per rarity (a legendary 'level 5' of 8); the game's shown level = level + (16 - max)."""
    try: return int(level) + (16 - int(max_level))
    except (TypeError, ValueError): return 0


def owned(account):
    """{card key: (shown level, card id)} of every card the player owns."""
    from royale import cr_api
    p = cr_api.player(account)
    out = {}
    for c in p.get("cards") or []:
        out[cr_api.key_of(c.get("name"))] = (_std_level(c.get("level"), c.get("maxLevel")), c.get("id"))
    return out, [cr_api.key_of(c.get("name")) for c in p.get("currentDeck") or []], p


def _tower(p):
    """The tower troop of the current deck (kept when the deck is copied)."""
    for c in p.get("currentDeckSupportCards") or []:
        if c.get("id"): return c["id"]
    return None


def choose(account, min_battles=3):
    """-> {"cards": [8 keys], "score", "win", "n", "level", "why"} or None."""
    from royale import cr_api
    have, current, p = owned(account)
    if not have: return None
    meta = cr_api.build_meta()
    king = max((lv for lv, _id in have.values()), default=14)
    best = None
    # the decks of today's best players (API) + every deck of the 252k replays with its real win rate
    try:
        from royale import pro
        replay_decks = pro.wins().get("decks") or []
    except Exception:
        replay_decks = []
    for d in list(meta.get("decks", [])) + replay_decks:
        cards = d["cards"]
        if len(cards) != 8 or any(c not in have for c in cards) or d["n"] < min_battles: continue
        win = (d["w"] + 2) / (d["n"] + 4)                         # pulled toward 50% when it has few battles
        lv = sum(have[c][0] for c in cards) / 8.0
        lvl = (lv - (king - 3)) / 3.0                              # 0 = 3 levels under your best, 1 = your best
        wcs = sum(1 for c in cards if c in WIN_CONDITIONS)
        bot = 0.02 * (wcs == 1)
        same = 0.03 if sorted(cards) == sorted(current) else 0.0
        score = win + 0.06 * max(-1.0, min(1.0, lvl)) + bot + same
        if best is None or score > best["score"]:
            best = {"cards": cards, "score": round(score, 4), "win": round(d["w"] / max(1, d["n"]), 3), "n": d["n"],
                    "level": round(lv, 1), "ids": [have[c][1] for c in cards]}
    if best:
        best["current"] = current
        best["tower"] = _tower(p)
        best["why"] = (f"{best['win'] * 100:.0f}% wins in {best['n']} battles of the best players, "
                       f"your levels {best['level']}")
    return best


def deck_link(ids, tower=None, scheme=True):
    """The game's own copy-deck link (what the game's share button / RoyaleAPI's Copy button open)."""
    q = "deck=" + ";".join(str(i) for i in ids) + "&l=Royals" + (f"&tt={tower}" if tower else "")
    return f"clashroyale://copyDeck?{q}" if scheme else f"https://link.clashroyale.com/en/?clashroyale://copyDeck?{q}"


def apply(account, pick, log, slot=0):
    """Open the copy-deck link in the emulator and confirm the game's Copy dialog. -> True when the deck is in."""
    from royale import game
    from royale.account import _bad, _tab, TABS, TAB_Y
    import utils
    dev = utils.ADB_Manager.adbutils_device
    if slot:                                                     # the bot's own slot: Cards tab, its number
        _tab("cards")
        ws = game.words(game.frame())
        s = game.find_word(ws, str(slot), y_min=0.12, y_max=0.3)
        if s:
            game.tap(*s); time.sleep(1.0)
    for scheme in (True, False):
        dev.shell(f'am start -a android.intent.action.VIEW -d "{deck_link(pick["ids"], pick.get("tower"), scheme)}"')
        time.sleep(4.0)
        if game.find_word(game.words(game.frame()), "copy", "use deck", y_min=0.3): break
    for _ in range(8):
        ws = game.words(game.frame())
        if _bad(ws):
            log.info("Clash Royale: the deck copy asked for something that costs — backed out")
            break
        b = game.find_word(ws, "copy", "use deck", "use", "ok", "confirm", "yes", y_min=0.3)
        if b:
            game.tap(*b)
            time.sleep(1.5)
            ws2 = game.words(game.frame())
            if not game.find_word(ws2, "copy", "use deck", y_min=0.3):
                _write(account, pick)
                game.tap(TABS["battle"], TAB_Y)
                time.sleep(1.2)
                return True
        time.sleep(1.0)
    game.tap(TABS["battle"], TAB_Y)
    return False


def _write(account, pick):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        d = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        d[str(account)] = {"t": time.time(), **{k: v for k, v in pick.items() if k != "current"}}
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass


def due(account, every=12 * 3600):
    try:
        d = json.loads(STATE.read_text(encoding="utf-8")).get(str(account)) or {}
        return time.time() - d.get("t", 0) > every
    except (OSError, ValueError):
        return True


def choose_offline(levels, current=None, min_games=300):
    """No official API: the collection the bot read from the screen ({card: level}) x every deck of the 252k
    replays with its real (side-corrected) win rate -> the best deck for THIS account.
    score = win rate (pulled toward 50% on few games) + 4% per level above 13 on average (a deck you have high
    levels in wins more for you) + a little for one clear win condition (the bot plays those best)."""
    from royale import pro
    key = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())
    lv = {key(k): v for k, v in (levels or {}).items()}
    if len(lv) < 30: return None                                   # the collection was not read well enough
    known = sorted(lv.values())
    default = known[len(known) // 2] - 1                           # a card not read: just under the usual level
    best = None
    for d in pro.wins().get("decks") or []:
        if d["n"] < min_games or len(d["cards"]) != 8: continue
        cards = d["cards"]
        win = (d["w"] + 75) / (d["n"] + 150)                     # a few hundred games are not proof: toward 50%
        avg = sum(lv.get(c, default) for c in cards) / 8.0
        wcs = sum(1 for c in cards if c in WIN_CONDITIONS)
        proven = 0.02 * min(1.0, d["n"] / 5000.0)                 # thousands of games: proven, not luck
        score = win + 0.04 * (avg - 13) + 0.01 * (wcs == 1) + proven + \
            (0.02 if current and sorted(cards) == sorted(current) else 0)
        if best is None or score > best["score"]:
            best = {"cards": cards, "score": round(score, 4), "win": round(d["w"] / d["n"], 3), "n": d["n"],
                    "level": round(avg, 1)}
    if best:
        best["why"] = f"{best['win'] * 100:.0f}% wins over {best['n']} replay games, your levels {best['level']}"
    return best
