"""
The eyes read what the brain needs beyond "what is where":

  health   every hurt unit shows a health bar over it (red = theirs, blue = ours); the filled part / the whole bar
           = how much life it has left. A unit with no bar is unhurt (the game hides full bars).
  spells   the big model sees spells landing (Fireball, Arrows, Zap, Log, Poison, Rocket, Lightning, Freeze, ...):
           theirs on our half are counted as cards they played (their elixir) and their area is kept free of troops
"""
SPELLS = {"arrows", "fireball", "zap", "the-log", "poison", "rocket", "lightning", "freeze", "rage", "tornado",
          "earthquake", "graveyard", "goblin-curse", "vines", "royal-delivery", "giant-snowball", "barbarian-barrel",
          "goblin-barrel", "clone", "void"}
SPELL_CARD = {"the-log": "the_log", "goblin-curse": "goblin_curse", "royal-delivery": "royal_delivery",
              "giant-snowball": "giant_snowball", "barbarian-barrel": "barbarian_barrel", "goblin-barrel": "goblin_barrel"}


def spell_card(model_name):
    return SPELL_CARD.get(model_name, model_name.replace("-", "_"))


def bar_fraction(frame, box, theirs=True):
    """frame: RGB picture; box: the unit's (x0, y0, x1, y1) pixels -> 0..1 life left, or None (no bar = unhurt).
    The bar's rows are the ones with the longest bright fill over the unit; along them: the fill, then the dark
    empty part (the game's colours, checked on real pictures); the middle answer of the best rows is kept."""
    import numpy as np
    h_img, w_img = frame.shape[:2]
    x0, y0, x1, y1 = box
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    ya, yb = int(max(0, y0 - 0.6 * h)), int(min(h_img, y0 + 0.2 * h))
    xa, xb = int(max(0, x0 - 0.4 * w)), int(min(w_img, x1 + 0.4 * w))
    if yb - ya < 2 or xb - xa < 6: return None
    s = frame[ya:yb, xa:xb].astype(np.int16)
    r, g, b = s[..., 0], s[..., 1], s[..., 2]
    if theirs:
        fill = (r > 185) & (g < 115) & (b < 125) & (r - g > 95)
        dark = (r > 55) & (r < 190) & (g < 100) & (b < 100) & (r - g > 30)
    else:
        fill = (b > 200) & (g > 150) & (r < 140)
        dark = (b > 50) & (b < 170) & (r < 80) & (b - r > 30)
    n = fill.shape[1]
    rows = []
    for row in range(fill.shape[0]):
        f = fill[row]
        if f.sum() < 3: continue
        # the longest fill run (1-pixel gaps allowed)
        best_a = best_e = cur_a = None
        k = 0
        while k < n:
            if f[k] or (k + 1 < n and f[k + 1] and cur_a is not None):
                if cur_a is None: cur_a = k
                k += 1
                if best_a is None or k - cur_a > best_e - best_a: best_a, best_e = cur_a, k
            else:
                cur_a = None; k += 1
        if best_a is None or best_e - best_a < 3: continue
        # a bar is thin (~4 px): a tall red blob (a tower, a red unit) is not one
        mid = (best_a + best_e) // 2
        if fill[max(0, row - 5):row + 6, mid].sum() > 7: continue
        k, miss = best_e, 0
        limit = best_a + int(1.3 * w) + 4
        while k < n and k <= limit and miss <= 2:       # the dark rest (2-pixel gaps allowed)
            miss = 0 if dark[row, k] else miss + 1
            k += 1
        if miss <= 2: continue                          # it never ended: the arena behind is dark red too — unsure
        end = k - miss
        total = end - best_a
        if 0.35 * w <= total:
            rows.append((best_e - best_a, (best_e - best_a) / total))
    if not rows: return None
    rows.sort(reverse=True)
    return round(float(np.median([fr for _, fr in rows[:3]])), 2)


def read(frame, dets, tile_of, theirs_of):
    """dets: the big model's [(name, conf, x0, y0, x1, y1)] -> ({(unit, tx, ty): life}, [(spell card, tx, ty)])."""
    from royale import strong_eyes
    hp, spells = {}, []
    for name, cf, x0, y0, x1, y1 in dets:
        if name in SPELLS:
            if cf >= 0.45:
                tx, ty = tile_of((x0 + x1) / 2, (y0 + y1) / 2)
                spells.append((spell_card(name), tx, ty))
            continue
        u = strong_eyes.unit_name(name)
        if not u or cf < 0.4: continue
        theirs = theirs_of(u, (x0, y0, x1, y1))
        try:
            f = bar_fraction(frame, (x0, y0, x1, y1), theirs)
        except Exception:
            f = None
        if f is not None and theirs:
            tx, ty = tile_of((x0 + x1) / 2, y1)
            hp[(u, tx, ty)] = max(0.05, f)
    return hp, spells
