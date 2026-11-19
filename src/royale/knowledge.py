"""
What a good Clash Royale player knows, written down for the brain: the decks (archetypes) and how each is played,
how every win condition is stopped (with what, where, when), which counters to keep for which threat, and what goes
together in an attack. The brain (royale.brain) reads it every decision.

Card names are the vision's / cards.json names (snake_case).
"""

# ------------------------------------------------------------------ the opponent's deck: which archetype?
# seen cards (any 2 of the "keys" give it away) -> archetype
ARCHETYPES = {
    "beatdown": {"keys": {"golem", "giant", "electro_giant", "goblin_giant", "lava_hound", "elixir_golem", "royal_giant"},
                 "need": 1,
                 "plan_ar": "تانك تقيل ورا ودعم وراه: ما تهاجمش بإكسير كتير بدري، دافع قريب من البرج (البرج يساعد)، واضرب "
                            "اللاين التاني أول ما ينزّل التانك ورا، وموّت الدعم (ساحرة / ويزارد / بيبي دراجون) بالسبيل"},
    "lavaloon": {"keys": {"lava_hound", "balloon", "minions", "mega_minion", "inferno_dragon", "skeleton_dragons"},
                 "need": 2,
                 "plan_ar": "جو بس: خلي دايمًا كارتين بيضربوا جو، Arrows/Fireball للـ Lava Pups والمينيونز، والبالون "
                            "يتصد قبل ما يوصل البرج بكارت جو ورا البرج"},
    "hog_cycle": {"keys": {"hog_rider", "ice_spirit", "skeletons", "the_log", "ice_golem", "cannon", "musketeer"},
                  "need": 2,
                  "plan_ar": "سريع وبيكرر الهوج: خلي رد للهوج دايمًا في إيدك (مبنى أو Mini P.E.K.K.A)، والمبنى في نص "
                             "الساحة بيشد الهوج، وهاجم أول ما رده (المدفع) يطلع من إيده"},
    "log_bait": {"keys": {"goblin_barrel", "princess", "goblin_gang", "dart_goblin", "rocket", "skeleton_barrel", "inferno_tower"},
                 "need": 2,
                 "plan_ar": "عايزك تضيّع الـ Log: شيل الـ Log / Arrows / Zap للـ Goblin Barrel بس، وارميه على البرج "
                            "لحظة ما البرميل يوصل، والبرنسيس بالكروت مش بالسبيل لو تقدر"},
    "siege": {"keys": {"x_bow", "mortar", "tesla", "archers", "knight"},
              "need": 2,
              "plan_ar": "X-Bow / Mortar على البريدج: حط تانك أو كارت قوي على المبنى أول ما يتحط، وما تسيبوش يضرب "
                         "البرج، وهاجم اللاين التاني"},
    "bridge_spam": {"keys": {"pekka", "battle_ram", "bandit", "royal_ghost", "electro_wizard", "magic_archer", "ram_rider", "dark_prince", "prince"},
                    "need": 2,
                    "plan_ar": "ضغط سريع على البريدج: ما تسيبش إكسيرك يقل، رد بكارت رخيص يشتّت (سكيليتونز / Ice Spirit) "
                               "وموّتهم قرب البرج، وما تهاجمش بكل إكسيرك"},
    "graveyard": {"keys": {"graveyard", "poison", "baby_dragon", "valkyrie", "freeze", "ice_wizard", "tornado"},
                  "need": 2,
                  "plan_ar": "Graveyard على البرج: كارت سبلاش (فالكيري / بيبي دراجون) أو Poison على الهياكل، وحط "
                             "حاجة جنب البرج على طول"},
    "miner_control": {"keys": {"miner", "poison", "wall_breakers", "bats", "spear_goblins", "goblin_gang"},
                      "need": 2,
                      "plan_ar": "Miner بيقرّص البرج: كارت رخيص على المينر عند البرج، وما تستعجلش"},
}

# ------------------------------------------------------------------ how each threat is stopped
# key: the threat's CARD name -> roles the answer should have (best first), where it goes, how urgent
#   where: pull   a building in the middle pulls it off the tower (building-only troops)
#          front  in front of it on its lane (melee / tanky)
#          behind behind our tower (ranged)
#          onit   right on it (spells, swarms that surround it)
#          tower  on our tower it attacks (goblin barrel, miner, graveyard)
#          late   let it come to the tower, the tower helps (tanks): place at the tower when it crosses the bridge
COUNTERS = {
    "hog_rider":     {"want": ["defense_building", "dps", "swarm"], "where": "pull", "avoid": ["spell"]},
    "ram_rider":     {"want": ["defense_building", "dps", "swarm"], "where": "pull"},
    "battle_ram":    {"want": ["defense_building", "swarm", "dps"], "where": "pull"},
    "royal_hogs":    {"want": ["splash", "defense_building", "small_spell"], "where": "pull"},
    "giant":         {"want": ["dps", "swarm", "defense_building"], "where": "late"},
    "royal_giant":   {"want": ["dps", "defense_building", "swarm"], "where": "pull"},
    "golem":         {"want": ["dps", "swarm"], "where": "late"},
    "electro_giant": {"want": ["dps", "ranged"], "where": "late", "avoid": ["swarm"]},
    "goblin_giant":  {"want": ["dps", "splash"], "where": "late"},
    "pekka":         {"want": ["swarm", "dps"], "where": "front", "avoid": ["tank"]},
    "mega_knight":   {"want": ["dps", "ranged"], "where": "front", "avoid": ["swarm"]},
    "prince":        {"want": ["swarm", "defense_building", "dps"], "where": "front"},
    "dark_prince":   {"want": ["dps", "defense_building"], "where": "front", "avoid": ["swarm"]},
    "balloon":       {"want": ["anti_air", "ranged", "big_spell"], "where": "behind"},
    "lava_hound":    {"want": ["anti_air", "dps"], "where": "behind"},
    "goblin_barrel": {"want": ["small_spell", "splash"], "where": "tower", "urgent": True},
    "graveyard":     {"want": ["splash", "big_spell"], "where": "tower", "urgent": True},
    "miner":         {"want": ["swarm", "cycle", "dps"], "where": "tower"},
    "x_bow":         {"want": ["tank", "dps", "big_spell"], "where": "onit", "urgent": True},
    "mortar":        {"want": ["tank", "dps"], "where": "onit", "urgent": True},
    "skeleton_army": {"want": ["small_spell", "splash"], "where": "onit"},
    "goblin_gang":   {"want": ["small_spell", "splash"], "where": "onit"},
    "minion_horde":  {"want": ["small_spell", "splash"], "where": "onit"},
    "minions":       {"want": ["small_spell", "anti_air"], "where": "onit"},
    "bats":          {"want": ["small_spell", "anti_air"], "where": "onit"},
    "wall_breakers": {"want": ["small_spell", "swarm", "cycle"], "where": "onit"},
    "barbarians":    {"want": ["splash", "big_spell"], "where": "front"},
    "witch":         {"want": ["big_spell", "dps"], "where": "onit"},
    "wizard":        {"want": ["big_spell", "dps"], "where": "onit"},
    "musketeer":     {"want": ["big_spell", "dps"], "where": "onit"},
    "princess":      {"want": ["small_spell", "swarm"], "where": "onit"},
    "sparky":        {"want": ["small_spell", "swarm", "dps"], "where": "front"},
    "inferno_dragon": {"want": ["anti_air", "small_spell"], "where": "behind"},
    "baby_dragon":   {"want": ["anti_air", "dps"], "where": "behind"},
    "goblin_drill":  {"want": ["swarm", "splash", "small_spell"], "where": "tower", "urgent": True},
    "royal_recruits": {"want": ["splash", "dps"], "where": "front"},
    "bowler":        {"want": ["swarm", "dps"], "where": "front"},
    "elite_barbarians": {"want": ["swarm", "splash", "defense_building"], "where": "front"},
    "electro_dragon": {"want": ["anti_air", "dps"], "where": "behind"},
    "royal_ghost":   {"want": ["splash", "small_spell", "dps"], "where": "front"},
    "bandit":        {"want": ["swarm", "small_spell", "dps"], "where": "front"},
}

# counters the bot keeps for a threat it knows the opponent has (not spent on anything else)
RESERVE = {
    "goblin_barrel": ["the_log", "arrows", "zap", "barbarian_barrel", "giant_snowball"],
    "graveyard": ["poison", "valkyrie", "baby_dragon"],
    "hog_rider": ["cannon", "tesla", "tombstone", "inferno_tower", "bomb_tower", "mini_pekka", "minipekka"],
    "balloon": ["musketeer", "minions", "mega_minion", "arrows", "electro_wizard", "wizard"],
    "lava_hound": ["minions", "mega_minion", "inferno_dragon", "arrows", "fireball"],
    "skeleton_army": ["the_log", "zap", "arrows", "valkyrie"],
    "x_bow": ["giant", "knight", "ice_golem", "pekka", "royal_giant"],
}

# their cards that answer OUR win condition: when one was just played (out of their hand), push now
ANSWERS_TO = {
    "hog_rider": ["cannon", "tesla", "tombstone", "inferno_tower", "bomb_tower", "goblin_cage", "mini_pekka",
                  "tornado", "skeleton_army", "guards"],
    "giant": ["inferno_tower", "inferno_dragon", "mini_pekka", "pekka", "skeleton_army", "minion_horde"],
    "balloon": ["musketeer", "minions", "mega_minion", "electro_wizard", "wizard", "inferno_dragon", "arrows"],
    "golem": ["inferno_tower", "inferno_dragon", "pekka", "mini_pekka"],
    "royal_giant": ["inferno_tower", "mini_pekka", "pekka", "skeleton_army"],
    "goblin_barrel": ["the_log", "arrows", "zap", "barbarian_barrel"],
    "miner": ["the_log", "skeletons", "zap"],
    "ram_rider": ["cannon", "tesla", "mini_pekka"],
    "battle_ram": ["cannon", "tesla", "skeletons"],
}

# what goes with what in an attack: after the first, the second is played behind it
SUPPORT = {
    "giant": ["musketeer", "wizard", "witch", "baby_dragon", "mini_pekka", "minions", "archers", "electro_wizard"],
    "golem": ["night_witch", "baby_dragon", "lumberjack", "mega_minion", "electro_dragon"],
    "lava_hound": ["balloon", "minions", "mega_minion", "inferno_dragon"],
    "royal_giant": ["fisherman", "hunter", "electro_spirit", "mega_minion"],
    "pekka": ["battle_ram", "bandit", "electro_wizard", "magic_archer"],
    "electro_giant": ["tornado", "dark_prince", "mother_witch"],
    "hog_rider": ["ice_spirit", "skeletons", "fireball", "the_log"],
}
# never two of these together (overcommitting: they hit back on the other lane)
NOT_TOGETHER = [{"golem", "giant", "royal_giant", "electro_giant", "pekka", "mega_knight", "lava_hound"}]


def archetype(seen):
    """Cards the opponent played so far -> (archetype name, its plan in Egyptian Arabic) or (None, None)."""
    s = set(seen or ())
    best, score = None, 0
    for name, a in ARCHETYPES.items():
        n = len(s & a["keys"])
        if n >= a["need"] and n > score: best, score = name, n
    return (best, ARCHETYPES[best]["plan_ar"]) if best else (None, None)


def reserved(their_seen, my_card):
    """Is my_card kept for a threat the opponent has? -> the threat or None."""
    for threat, keep in RESERVE.items():
        if threat in (their_seen or ()) and my_card in keep: return threat
    return None


# ------------------------------------------------------------------ every other card of the game
# COUNTERS above is written by hand for the cards that need special care. Every other card (all 110 of cards.json)
# gets its answer worked out from what it is (flies, hits buildings only, a group, a tank, a building, a spell);
# what real players actually answered it with comes on top of that from royale.pro (252k games).
_DERIVED = {}


def counter(name, c=None):
    """-> {"want": [roles, best first], "where": ..., "urgent"?, "avoid"?} for any card."""
    if not name: return {}
    if name in COUNTERS: return COUNTERS[name]
    if name in _DERIVED: return _DERIVED[name]
    c = c or {}
    kind, hp, n = c.get("kind"), (c.get("hp") or 0), max(1, c.get("count") or 1)
    if kind == "spell" or not c:
        out = {}
    elif kind == "building":
        # a building of theirs on our side (x-bow / mortar like): something sturdy on it at once
        out = {"want": ["tank", "dps", "big_spell"], "where": "onit", "urgent": bool(c.get("damage"))}
    elif c.get("buildings_only"):
        out = ({"want": ["dps", "swarm", "defense_building"], "where": "late"} if hp * n >= 2500 else
               {"want": ["defense_building", "dps", "swarm"], "where": "pull"})
        if c.get("air"): out = {"want": ["anti_air", "ranged", "big_spell"], "where": "behind"}
    elif c.get("air"):
        out = ({"want": ["small_spell", "anti_air", "splash"], "where": "onit"} if n >= 3 else
               {"want": ["anti_air", "ranged", "dps"], "where": "behind"})
    elif n >= 3:
        out = {"want": ["small_spell", "splash"], "where": "onit"}
    elif hp * n >= 2500:
        out = {"want": ["dps", "swarm"], "where": "late", "avoid": ["small_spell"]}
    elif (c.get("range") or 0) >= 4:
        out = {"want": ["big_spell", "dps", "swarm"], "where": "onit"}
    else:
        out = {"want": ["dps", "swarm", "splash"], "where": "front"}
    _DERIVED[name] = out
    return out
