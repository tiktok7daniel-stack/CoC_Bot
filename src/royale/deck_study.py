"""
The deck studied before it is played (like a player who looks at a new deck before the battle). From the 252k
replays (who won, side-corrected) and the game's numbers, for THESE 8 cards:

  roles      win conditions, spells, buildings, air defence, splash, cycle cards; which ones are evolved / heroes
  attack     the main win condition (the one that wins most) and the second; where each starts (the attack atlas /
             where winners start it) and which card of the deck goes with it (the pairs of the deck that win most)
  defence    for the cards players meet most, the best answer the deck has and how often it won with it;
             the threats the deck has no good answer to = what to be careful with (keep that answer, defend early)
  shape      average elixir, the cost of a 4-card cycle, the estimated strength vs the usual deck

-> royale.brain uses it (pairs behind the win condition, the cards kept for the deck's weak spots) and the user
   gets it on the phone in Egyptian Arabic.
"""
ROLE_AR = {"win": "بيكسب البرج", "spell": "سبيل", "building": "مبنى دفاع", "anti_air": "بيضرب الطيران",
           "splash": "ضرب جماعي", "cycle": "رخيص للدوران", "tank": "تانك"}


def _k(n):
    return "".join(ch for ch in str(n).lower() if ch.isalnum())


def study(deck, levels=None, evo=(), heroes=()):
    from royale import pro
    from royale.brain import roles, card
    deck = [n for n in deck if n and n != "blank"]
    if len(deck) != 8: return None
    W = pro.wins()
    cw = W.get("cards") or {}
    combos = W.get("combos") or {}
    answers = W.get("answers") or {}
    out = {"deck": deck, "evo": sorted(set(evo) & set(deck)), "heroes": sorted(set(heroes) & set(deck))}
    R = {n: roles(n) for n in deck}
    out["roles"] = {n: sorted(r) for n, r in R.items()}
    costs = {n: (card(n) or {}).get("cost", 3) for n in deck}
    out["avg_elixir"] = round(sum(costs.values()) / 8.0, 1)
    out["cycle4"] = sum(sorted(costs.values())[:4])

    # the win conditions: the one that wins most first
    wins = [n for n in deck if "win" in R[n]]
    wr = lambda n: (cw.get(_k(n)) or [0, 0.5])[1]
    wins.sort(key=lambda n: -wr(n))
    out["win_conditions"] = wins

    # the deck's pairs that win most (either order), real games only
    pairs = []
    for i, a in enumerate(deck):
        for b in deck[i + 1:]:
            n = w = 0
            for key in (f"{_k(a)}+{_k(b)}", f"{_k(b)}+{_k(a)}"):
                v = combos.get(key)
                if v: n += v[0]; w += v[0] * v[1]
            if n >= 150: pairs.append((a, b, n, round(w / n, 3)))
    pairs.sort(key=lambda p: -p[3])
    out["pairs"] = pairs[:8]

    # how each win condition is played: where it starts, what goes with it
    plan = {}
    for n in wins:
        spot = pro.attack_best(n, "left") or pro.place(n, "left")
        # what winners play right after it in the same push (troops / spells of this deck), then the pairs
        fol = pro.follows(n, [m for m in deck if m != n]) or {}
        mates = [(m, round(f, 2)) for m, f in sorted(fol.items(), key=lambda kv: -kv[1])
                 if f >= 0.08 and "building" not in R.get(m, ())][:2]
        if not mates:
            mates = [(b if a == n else a, w) for a, b, _c, w in pairs if n in (a, b) and
                     "building" not in R[b if a == n else a]][:2]
        plan[n] = {"spot": list(spot) if spot else None, "with": mates}
    out["attack"] = plan

    # defence: the threats met most (all rows of a card summed), the best answer of THIS deck
    met = {}
    for key, row in answers.items():
        threat = key.split("|")[0]
        met.setdefault(threat, {})
        for a, (n, w) in row.items():
            m = met[threat].setdefault(a, [0, 0.0])
            m[0] += n; m[1] += n * w
    freq = sorted(met, key=lambda t: -sum(v[0] for v in met[t].values()))
    names = {_k(n): n for n in deck}
    defence, weak = {}, []
    allk = {_k(n): n for n in __import__("royale.brain", fromlist=["cards_db"]).cards_db()}
    threats = [t for t in freq if (card(allk.get(t, "")) or {}).get("kind") in ("troop", "hero", "building")]
    for t in threats[:30]:
        # a defender is a card that stops it (not a win condition thrown at their other lane)
        opts = [(names[a], v[1] / v[0], v[0]) for a, v in met[t].items()
                if a in names and v[0] >= 100 and ("win" not in R[names[a]] or "spell" in R[names[a]])]
        if not opts:
            weak.append((t, None, None)); continue
        best = max(opts, key=lambda o: o[1])
        defence[t] = [best[0], round(best[1], 3)]
        if best[1] < 0.5: weak.append((t, best[0], round(best[1], 3)))
    out["defence"] = defence
    # the hardest ones: no answer at all, then the lowest best answers (under 53%)
    weak += sorted([(t, a, w) for t, (a, w) in defence.items() if 0.5 <= w < 0.53], key=lambda x: x[2])
    out["weak"] = weak[:8]
    # keep these for the weak spots: the deck's best answer to each threat it struggles with
    out["keep_for"] = {t: a for t, a, w in weak if a and w is not None and w < 0.5}

    # an estimate of the deck's strength from its cards and pairs (the replays have no games of most home-made
    # decks): 50% + how its cards and its pairs do vs the usual card
    est = 0.5 + sum(wr(n) - 0.5 for n in deck) / 8.0 + (sum(p[3] - 0.5 for p in pairs[:4]) / 4.0 if pairs else 0)
    out["estimate"] = round(est, 3)
    out["text_ar"] = text_ar(out, levels)
    return out


def text_ar(s, levels=None):
    from royale.brain import card
    t = lambda n: n.replace("_", " ")
    L = ["🧠 حللت الديك قبل ما ألعب بيه:"]
    if s["win_conditions"]:
        main = s["win_conditions"][0]
        L.append(f"• الهجوم الأساسي: {t(main)}" + (f"، والتاني: {', '.join(t(w) for w in s['win_conditions'][1:])}"
                                                   if len(s["win_conditions"]) > 1 else ""))
        for n, p in s["attack"].items():
            mates = " + ".join(t(m) for m, _w in p["with"])
            L.append(f"   - {t(n)}" + (f" يبدأ من ({p['spot'][0]},{p['spot'][1]})" if p["spot"] else "") +
                     (f" ومعاه {mates}" if mates else ""))
    else:
        L.append("• مفيش كارت بيكسب البرج لوحده في الديك ده — الهجوم هيبقى بعد الدفاع (كاونتر)")
    if s["pairs"]:
        L.append("• أحسن كروت مع بعض: " + "، ".join(f"{t(a)}+{t(b)} {w * 100:.0f}%" for a, b, _n, w in s["pairs"][:3]))
    if s["evo"] or s["heroes"]:
        L.append("• متطور: " + (", ".join(t(n) for n in s["evo"]) or "—") +
                 " | هيرو: " + (", ".join(t(n) for n in s["heroes"]) or "—"))
    L.append(f"• متوسط الإكسير {s['avg_elixir']} — دورة 4 كروت بـ {s['cycle4']}")
    if s["weak"]:
        L.append("• نقط ضعف الديك (هاخد بالي منها وأحتفظ بالرد): " +
                 "، ".join(t(w) + (f" (الرد: {t(a)})" if a else " (مفيش رد كويس)") for w, a, _x in s["weak"][:5]))
    L.append(f"• قوة الديك التقريبية: {s['estimate'] * 100:.0f}% (50% = ديك عادي)")
    return "\n".join(L)
