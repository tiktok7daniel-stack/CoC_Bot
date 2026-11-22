"""
How every card is used and where it goes (the user's correction, 5.73: "learn how every card is used so you never
play it wrong"). Every move — from the rules, the battle engine, the trained AI or the learned brain — passes
through `check()` in Brain._play before it is tapped: a card put where it makes no sense is moved to its right
place, or not played at all.

Each card of the game gets a kind from its data (royale.brain.roles); the account's own cards are written out by
hand with what good players do with them (`OWN`, with an Egyptian-Arabic note for the user).

Board (the bot's tiles): x 0..17 left to right, y 0 = our back edge .. 31 = theirs; the river is y 15-16, our
bridges are y 13-14 at x 3 and x 14; our princess towers at (3.5, 5) and (14.5, 5).
"""

LEFT_X, RIGHT_X = 3, 14

# the account's cards (both decks): what each is for, where it goes on attack and on defense
OWN = {
    "hog_rider": {"kind": "win_bridge",
                  "ar": "الهوج: كارت الهجوم. بيتحط عند البريدج (أول النهر) في الحارة اللي البرج فيها أضعف، "
                        "وأحسن وقت بعد ما الخصم يصرف الكانون/المبنى بتاعه أو وقت ما معاه إكسير قليل."},
    "goblin_barrel": {"kind": "win_spell",
                      "ar": "برميل العفاريت: بيترمي على برج الخصم على طول. أحسن وقت بعد ما الخصم يصرف اللوج/الأسهم."},
    "witch": {"kind": "support_ranged",
              "ar": "الويتش: دعم من ورا. في الهجوم ورا كارت تقيل أو ورا البرج بتاعك عشان تبني هجمة؛ "
                    "في الدفاع ورا البرج مش قدام العدو، والهياكل بتشتت الأعداء."},
    "musketeer": {"kind": "support_ranged",
                  "ar": "المسكتير: بتضرب من بعيد (أرض وجو). في الدفاع ورا البرج أو في النص بعيد عن العدو؛ "
                        "في الهجوم ورا الهوج أو ورا كارت تاني، عمرها ما تتحط لوحدها قدام."},
    "bowler": {"kind": "support_splash",
               "ar": "البولر: تقيل وبيرمي كور بتزق الأعداء. ممتاز في الدفاع قدام الأسراب والأرضي؛ "
                     "في الهجوم بيمشي ورا أو جنب كارت الهجوم."},
    "valkyrie": {"kind": "mini_tank_splash",
                 "ar": "الفالكيري: بتلف وتضرب كل اللي حواليها. في الدفاع على العدو الأرضي/السرب مباشرة؛ "
                       "في الهجوم قدام الدعم عشان تاخد الضرب."},
    "cannon": {"kind": "building_defense",
               "ar": "الكانون: مبنى دفاع. بيتحط في النص (قدام الكينج بشوية) عشان يشد الهوج والجاينت بعيد عن البرج؛ "
                     "ما بيتحطش من غير سبب ولا في الضهر."},
    "bats": {"kind": "swarm_air",
             "ar": "الخفافيش: رخيصة وسريعة. في الدفاع على العدو اللي ما بيضربش جو (زي الميني بيكا والهوج)؛ "
                  "في الهجوم ورا كارت الهجوم. بتموت من اللوج/الأسهم/الزاب."},
    "spear_goblins": {"kind": "swarm_ranged",
                      "ar": "عفاريت الحربة: رخيصة وبتضرب من بعيد. دفاع ورا البرج أو مع البرميل/الهوج في الهجوم."},
    "arrows": {"kind": "spell_small",
               "ar": "الأسهم: على سرب أعداء ضعاف (هياكل، مينيونز، عفاريت، خفافيش) بس، مش على كارت تقيل ولا مكان فاضي."},
    "the_log": {"kind": "spell_small",
                "ar": "اللوج: بيترمي ورا الأعداء الأرضيين يتدحرج عليهم؛ لو مفيش حاجة والإكسير مليان يتدحرج على برجهم."},
}

# the game's other cards whose kind the data alone gets wrong
KIND_FIX = {
    **{n: "spell_utility" for n in ("clone", "freeze", "rage", "mirror", "tornado", "goblin_curse", "vines",
                                    "heal_spirit")},
    **{n: "win_spell" for n in ("miner", "goblin_drill")},
    **{n: "win_tank" for n in ("golem", "lava_hound", "elixir_golem", "goblin_giant", "electro_giant", "giant",
                               "goblinstein")},
    **{n: "mini_tank" for n in ("knight", "minipekka", "lumberjack", "bandit", "royal_ghost", "elite_barbarians",
                                "fisherman", "berserker", "ronin", "monk", "prince", "ice_golem", "rune_giant",
                                "golden_knight", "mighty_miner", "boss_bandit", "giant_skeleton", "pekka")},
    **{n: "mini_tank_splash" for n in ("dark_prince", "mega_knight", "valkyrie")},
    **{n: "support_ranged" for n in ("dart_goblin", "electro_wizard", "ice_wizard", "mega_minion", "inferno_dragon",
                                     "electro_dragon", "phoenix", "musketeer", "archers", "little_prince",
                                     "flying_machine", "cannon_cart", "archer_queen", "spirit_empress")},
    **{n: "support_splash" for n in ("baby_dragon", "skeleton_dragons", "night_witch", "firecracker", "sparky",
                                     "wizard", "executioner", "bowler", "bomber", "magic_archer", "hunter",
                                     "princess", "goblin_demolisher", "witch", "mother_witch")},
    **{n: "cycle_spirit" for n in ("fire_spirit", "ice_spirit", "electro_spirit")},
}
DAMAGE_SPELLS = {"arrows", "the_log", "zap", "barbarian_barrel", "giant_snowball", "royal_delivery", "fireball",
                 "poison", "rocket", "lightning", "earthquake", "void"}

KINDS_AR = {
    "spell_utility": "سبيل مساعد (فريز/ريج/كلون/تورنادو): مع هجمة أو دفاع، مش لوحده",
    "cycle_spirit": "سبيرت رخيص: على السرب أو مع الهجمة",
    "win_bridge": "كارت هجوم سريع: عند البريدج",
    "win_tank": "تانك هجوم: من الضهر أو عند البريدج",
    "win_spell": "بيترمي على برج الخصم",
    "siege": "X-Bow / Mortar: قدام النهر في نصك",
    "building_defense": "مبنى دفاع: في النص يشد العدو",
    "building_spawn": "مبنى بيطلع جيش: في الضهر",
    "support_ranged": "دعم من بعيد: ورا التانك أو ورا البرج",
    "support_splash": "دعم سبلاش: ورا/جنب التانك، في الدفاع على السرب",
    "mini_tank_splash": "ميني تانك: على العدو في الدفاع، قدام الدعم في الهجوم",
    "mini_tank": "ميني تانك / قاتل تانكات: على العدو في الدفاع",
    "swarm_air": "سرب جوي: على اللي ما بيضربش جو",
    "swarm_ranged": "سرب بيضرب من بعيد: ورا البرج",
    "swarm_ground": "سرب أرضي: على التانك اللي ما عندوش سبلاش",
    "spell_small": "سبيل صغير: على الأسراب بس",
    "spell_big": "سبيل كبير: على أكتر من كارت أو يخلّص برج",
    "troop": "كارت عادي",
}


def kind(name):
    """The card's kind: the account's own cards by hand, every other card from its data."""
    if name in OWN: return OWN[name]["kind"]
    if name in KIND_FIX: return KIND_FIX[name]
    from royale.brain import roles, card
    r, c = roles(name), card(name)
    if "spell" in r:
        if "win" in r: return "win_spell"
        if "small_spell" in r: return "spell_small"
        return "spell_big"
    if "building" in r:
        if name in ("x_bow", "mortar"): return "siege"
        return "building_defense" if "defense_building" in r else "building_spawn"
    if "win" in r:
        return "win_tank" if (c.get("speed") or 60) <= 60 and "tank" in r else "win_bridge"
    if "swarm" in r:
        if c.get("air"): return "swarm_air"
        return "swarm_ranged" if "ranged" in r else "swarm_ground"
    if "ranged" in r: return "support_splash" if "splash" in r else "support_ranged"
    if "tank" in r or (c.get("hp") or 0) >= 700:
        return "mini_tank_splash" if "splash" in r else "mini_tank"
    return "troop"


def note_ar(name):
    return OWN.get(name, {}).get("ar") or KINDS_AR.get(kind(name), "")


def _bridge(x):
    return (LEFT_X if x < 9 else RIGHT_X, 13)


def _threats(brain):
    """Their units on our half or about to cross (y <= 17)."""
    return [(u, x, y) for u, x, y in (brain._stable or []) if y <= 17]


def _ours_ahead(brain, x):
    """Our units already in that lane in front of our towers (a tank / win condition to support)."""
    from royale.brain import lane
    allies = list(getattr(brain, "_allies", []) or []) + list(getattr(brain, "_allies_extra", []) or [])
    side = lane(x)
    out = [a for a in allies if lane(a[1]) == side and a[2] >= 8]
    t = brain.elapsed()
    out += [(p["card"], p["tile"][0], p["tile"][1]) for p in getattr(brain, "plays", [])     # just played: the eyes
            if t - p["t"] <= 4 and lane(p["tile"][0]) == side and p["tile"][1] >= 8]          # may not show it yet
    return out


def check(brain, name, tile, why):
    """-> (tile, why) to play, the tile moved to the card's right place when needed; None = do not play it."""
    from royale.brain import lane, dist, THEIR_TOWERS
    k = kind(name)
    x, y = tile
    threats = _threats(brain)
    defending = bool(threats)
    full = getattr(brain, "_my_el", 0) >= 9.5
    if k == "win_bridge":
        # a fast win condition is an attack card: at the bridge, not dropped at home with nothing to defend
        if not defending and y < 12:
            nb = _bridge(x)
            return nb, f"{why} | {name}: attack at the {lane(x)} bridge"
        return tile, why
    if k == "building_defense":
        # in the middle to pull (Hog / Giant / Ram go for the nearest building), never at the back or forward
        # only against something really coming (5.92: 10 Cannons in one battle, two in its first 2 seconds)
        if not defending: return None
        t_now = brain.elapsed()
        if any(p["card"] == name and t_now - p["t"] < 8 for p in getattr(brain, "plays", [])):
            return None                                      # the last one still stands
        tx = x
        if threats:
            near = min(threats, key=lambda t: t[2])
            tx = 7 if lane(near[1]) == "left" else 10
        if not (5 <= tx <= 12) or not (6 <= y <= 11):
            return (max(6, min(11, tx)), 9), f"{why} | {name}: in the middle to pull"
        return tile, why
    if k == "building_spawn":
        if y > 9: return (x, 6), f"{why} | {name}: at the back"
        return tile, why
    if k in ("support_ranged", "swarm_ranged"):
        if defending:
            # in range of the threat but not on top of it (it dies at once): a few tiles behind it, our side
            near = min(threats, key=lambda t: dist((t[1], t[2]), tile))
            if dist((near[1], near[2]), tile) < 2.5 and near[2] - 4 >= 2:
                nt = (int(x), int(max(2, near[2] - 4)))
                return nt, f"{why} | {name}: behind, out of its reach"
            return tile, why
        if y >= 10 and not _ours_ahead(brain, x):
            # alone in front it just dies: behind our princess tower to build a push
            nt = (LEFT_X if x < 9 else RIGHT_X, 2)
            return nt, f"{why} | {name}: behind our tower (nothing in front of it)"
        return tile, why
    if k == "swarm_air":
        if not defending and not _ours_ahead(brain, x) and not full:
            return None                                      # bats alone at their tower do nothing
        return tile, why
    if k == "win_spell":
        return tile, why                                     # Brain._barrel_tile puts it on their tower
    return tile, why


def table():
    """Every card of the game with its kind and note (written to the learning repo for the user)."""
    from royale.brain import cards_db
    out = {}
    for n in sorted(cards_db()):
        out[n] = {"kind": kind(n), "note_ar": note_ar(n), "own": n in OWN}
    return out
