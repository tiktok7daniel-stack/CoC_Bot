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


def choose(account, heroes=()):
    """The official API's collection (exact levels, which cards have their evolution) -> the same choice as without
    the API (royale.deck_pick.choose_offline): every proven deck (300+ replay games, 30+ battles of today's best
    players), your levels, your evolutions / hero, and YOUR deck kept unless another is clearly better.
    -> {"cards", "ids", "why", "current", "tower"} or {"keep": True, ...} or None."""
    from royale import cr_api
    have, current, p = owned(account)
    if not have: return None
    evo = [cr_api.key_of(c.get("name")) for c in p.get("cards") or [] if c.get("evolutionLevel")]
    try:
        meta = [d for d in (cr_api.build_meta().get("decks") or []) if d.get("n", 0) >= 30]
    except Exception:
        meta = []
    pick = choose_offline({k: lv for k, (lv, _id) in have.items()}, current=current, evo=evo, heroes=heroes,
                          extra_decks=meta, owned=set(have))
    if not pick: return None
    pick["current"] = current
    pick["tower"] = _tower(p)
    pick["evo"] = evo
    if not pick.get("keep"):
        pick["ids"] = [have[c][1] for c in pick["cards"]]
    return pick


def slot_order(cards, evo=(), heroes=()):
    """The game's deck slots: 1 = evolution, 2 = hero, 3 = evolution (the user's deck page) -> the cards in that
    order, so the copied deck comes out with its evolutions / hero in their slots."""
    k = lambda s: "".join(ch for ch in str(s).lower() if ch.isalnum())
    ev = [c for c in cards if k(c) in {k(e) for e in evo or ()}][:2]
    he = [c for c in cards if k(c) in {k(h) for h in heroes or ()} and c not in ev][:1]
    rest = [c for c in cards if c not in ev and c not in he]
    out = [ev[0] if ev else rest.pop(0)] + [he[0] if he else rest.pop(0)] + \
          [ev[1] if len(ev) > 1 else rest.pop(0)] + rest
    return out


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
    copied = False
    for _ in range(8):
        ws = game.words(game.frame())
        if _bad(ws):
            log.info("Clash Royale: the deck copy asked for something that costs — backed out")
            break
        # only the game's own Copy button counts; a plain OK / Yes is tapped only after Copy (its "replace?")
        b = game.find_word(ws, "copy", "use deck", y_min=0.3)
        if not b and copied: b = game.find_word(ws, "ok", "confirm", "yes", y_min=0.3)
        if b:
            game.tap(*b)
            copied = True
            time.sleep(1.5)
            if not game.find_word(game.words(game.frame()), "copy", "use deck", "ok", "confirm", "yes", y_min=0.3):
                break
            continue
        if copied: break
        time.sleep(1.0)
    game.tap(TABS["battle"], TAB_Y)
    time.sleep(1.2)
    if not copied:
        log.info("Clash Royale: the copy-deck window never showed — the deck was NOT changed")
    # "copied" is only a hope: the first battle's hand (or the official API) tells whether the deck really changed
    return copied


def _write(account, pick):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        d = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        d[str(account)] = {"t": time.time(), **{k: v for k, v in pick.items() if k != "current"}}
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass


def forget(account):
    """The deck did not really change: try again next time."""
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        d.pop(str(account), None)
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except (OSError, ValueError):
        pass


def mark(account, pick):
    _write(account, pick)


def due(account, every=12 * 3600):
    try:
        d = json.loads(STATE.read_text(encoding="utf-8")).get(str(account)) or {}
        return time.time() - d.get("t", 0) > every
    except (OSError, ValueError):
        return True


def choose_offline(levels, current=None, min_games=300, evo=(), heroes=(), extra_decks=(), owned=None):
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
    evo_k, hero_k = {key(n) for n in evo or ()}, {key(n) for n in heroes or ()}
    # an evolved card or a hero in the deck is much stronger than its plain card: +1.5% each (2 evo + 1 hero slots)
    power = lambda cards: 0.015 * min(2, len(evo_k & set(cards))) + 0.015 * min(1, len(hero_k & set(cards)))
    best = None
    for d in list(pro.wins().get("decks") or []) + list(extra_decks or []):
        if len(d["cards"]) != 8: continue
        if d["n"] < (30 if d in (extra_decks or ()) else min_games): continue
        cards = d["cards"]
        if owned is not None and any(c not in owned for c in cards): continue      # a card you do not have
        win = (d["w"] + 75) / (d["n"] + 150)                     # a few hundred games are not proof: toward 50%
        avg = sum(lv.get(c, default) for c in cards) / 8.0
        wcs = sum(1 for c in cards if c in WIN_CONDITIONS)
        proven = 0.02 * min(1.0, d["n"] / 5000.0)                 # thousands of games: proven, not luck
        score = win + 0.04 * (avg - 13) + 0.01 * (wcs == 1) + proven + power(cards) + \
            (0.02 if current and sorted(cards) == sorted(key(c) for c in current) else 0)
        if best is None or score > best["score"]:
            best = {"cards": cards, "score": round(score, 4), "win": round(d["w"] / d["n"], 3), "n": d["n"],
                    "level": round(avg, 1)}
    if best:
        best["why"] = f"{best['win'] * 100:.0f}% wins over {best['n']} replay games, your levels {best['level']}"
    # the deck the player has now (learned from the battles), studied the same way: it is changed only when the
    # other one is clearly better (+3%) — a home-made deck with your evolutions / hero is often the strongest
    if best and current and len(current) == 8:
        try:
            from royale import deck_study
            st = deck_study.study(list(current), evo=evo, heroes=heroes)
            cur_k = [key(c) for c in current]
            cur_avg = sum(lv.get(c, default) for c in cur_k) / 8.0
            cur = st["estimate"] + 0.04 * (cur_avg - 13) + power(cur_k) + 0.02
            if cur + 0.03 >= best["score"]:
                return {"keep": True, "cards": cur_k, "score": round(cur, 4), "other": best,
                        "why": f"your deck ~{st['estimate'] * 100:.0f}% (levels {cur_avg:.1f}, evolutions / hero "
                               f"counted) vs the best other {best['win'] * 100:.0f}% (levels {best['level']})"}
        except Exception:
            pass
    return best
