"""
The Clash Royale eyes: one look at the game (720x1280 portrait, any size scaled) -> everything the brain needs.
  hand / next card / which cards can be played   (card pictures of 139 cards, ClashRoyaleBuildABot)
  our elixir                                      (the elixir bar)
  every unit in the arena, ours or theirs, tile   (YOLO units model 97 kinds + ally / enemy model)
  the 4 princess towers' health                   (their health bars)
The deck is found by itself: in the first seconds of a battle every hand card is compared with all 139 pictures;
once the 8 are known the comparison is only among them (faster, no mix-up).
"""
import math, os, threading, time

from royale.vision import constants as C

_LOCK = threading.Lock()


class Eyes:
    def __init__(self, deck=None):
        from royale.vision.namespaces.cards import Cards
        from royale.vision.detectors.number_detector import NumberDetector
        from royale.vision.detectors.unit_detector import UnitDetector
        self._Cards = Cards
        self.all_cards = [getattr(Cards, f) for f in Cards.__dataclass_fields__
                          if getattr(Cards, f).name != "blank" and
                          os.path.exists(os.path.join(C.IMAGES_DIR, "cards", f"{getattr(Cards, f).name}.jpg"))]
        self.by_name = {c.name: c for c in self.all_cards}
        self.numbers = NumberDetector()
        self.units = UnitDetector(os.path.join(C.MODELS_DIR, "units_M_480x352.onnx"), [])
        self.seen_counts = {}
        self.deck = []
        from royale.unit_tracker import UnitTracker
        from royale.team_color import TeamColor
        self.tracker = UnitTracker()              # every unit followed: id, speed, its side kept (6.6)
        self.colors = TeamColor()                 # ours / theirs from the badge / health-bar colour (6.6)
        self.two_v_two = False                    # 2v2: a unit not in our deck can be our partner's
        self.hand_cls = None                      # the hand-card model (royale.hand_classifier), when trained
        self._side_cache = []                     # avoid rerunning the per-unit ONNX classifier on every look
        self.last_timings = {}
        # 6.7: ONE arena detector a look. The big model (174 kinds: evolutions, heroes, every new card) is the eyes when
        # it answers for this very picture (on the graphics card); BuildABot's 97-kind model only fills in while it
        # is not ready / runs on the processor in the background — or always, with royale.dual_eyes (Advanced)
        self.dual = False
        self.single_used = 0
        self._card_det = None
        self.set_deck(deck or [])

    # -------------------------------------------------------------- the deck
    def set_deck(self, names):
        from royale.vision.detectors.card_detector import CardDetector
        names = [n for n in names if n in self.by_name][:8]
        self.deck = names
        cards = [self.by_name[n] for n in names] if len(names) == 8 else self.all_cards
        self._card_det = CardDetector(cards)
        # units that can be ours: only those of our deck are asked "ours or theirs?" (others are theirs).
        # While the deck is not known yet EVERY unit is asked: before 5.43.1 an unknown deck meant "everything is
        # theirs", so the bot's own first troops were taken for the enemy and spelled (Fireball on itself)
        self.units.cards = [self.by_name[n] for n in names]
        self.units.possible_ally_names = ({u.name for n in names for u in self.by_name[n].units} if len(names) == 8
                                          else {u.name for c in self.all_cards for u in c.units})

    @staticmethod
    def known_decks():
        """The account's real decks (5.87): the learning repo's knowledge/royale_my_cards.json (deck + 2v2 deck, fetched
        by learn_sync) and the deck in the settings. A hand reading is checked against them."""
        import json as _j
        from pathlib import Path as _P
        out = []
        try:
            d = _j.loads((_P.home() / ".CoC_Bot" / "learn" / "royale_my_cards.json").read_text(encoding="utf-8"))
            for k, v in d.items():
                if not k.startswith("deck"): continue
                cards = v.get("cards") if isinstance(v, dict) else v
                if isinstance(cards, list) and len(cards) == 8 and all(isinstance(c, str) for c in cards):
                    out.append(list(cards))
        except (OSError, ValueError, AttributeError):
            pass
        if out: return out                          # the account's decks written down: they are the truth (5.92)
        try:
            import settings, utils
            dk = ((settings.load(utils.INSTANCE_ID) or {}).get("royale") or {}).get("deck") or []
            if len(dk) == 8 and dk not in out: out.append(list(dk))
        except Exception:
            pass
        return out

    def _snap(self, sure):
        """5+ of the cards read are one of the account's real decks -> that deck exactly (a card misread — Goblin
        Barrel read as Goblin Gang, both with a goblin face — is put right, before it is locked in for the battle)."""
        best = None
        decks = self.known_decks()
        anywhere = {c for k in decks for c in k}
        for k in decks:
            ov = len(set(sure) & set(k))
            odd = [c for c in sure if c not in k]
            # 5+ in common; or 4 when the rest (at most 2) are in none of the decks: misreads (5.92: Goblin Gang)
            ok = ov >= 5 or (ov >= 4 and len(odd) <= 2 and not any(c in anywhere for c in odd))
            if ok and (best is None or ov > best[0]): best = (ov, k)
        return best[1] if best else None

    def learn_deck(self, hand):
        """Hand cards seen in the first looks of a battle -> the deck once 8 different ones were seen 2+ times
        (or once 5 of them make one of the account's known decks)."""
        if len(self.deck) == 8: return False
        for n in hand:
            if n and n != "blank": self.seen_counts[n] = self.seen_counts.get(n, 0) + 1
        sure = [n for n, k in sorted(self.seen_counts.items(), key=lambda kv: -kv[1]) if k >= 2][:8]
        if len(sure) >= 5:
            real = self._snap(sure)
            if real and all(n in self.by_name for n in real):
                self.set_deck(real)
                return True
        if len(sure) == 8:
            self.set_deck(sure)
            return True
        # the deck is not known yet: every unit stays "ask ours or theirs" (set_deck)
        return False

    # -------------------------------------------------------------- one look
    def look(self, frame_rgb):
        """frame_rgb: numpy RGB of the game screen. -> dict (see module doc)."""
        import numpy as np
        from PIL import Image
        started = time.perf_counter()
        seen_t = time.time()
        img = Image.fromarray(frame_rgb).convert("RGB").resize((C.SCREENSHOT_WIDTH, C.SCREENSHOT_HEIGHT),
                                                                Image.Resampling.BILINEAR)
        t_prep = time.perf_counter()
        big, big_now = [], False
        try:                                         # the big model first: is it the eyes of this very picture?
            from royale import strong_eyes
            if strong_eyes.ready():
                big = strong_eyes.look_now(frame_rgb)
                big_now = strong_eyes.same_moment()
        except Exception:
            big = []
        t_big = time.perf_counter()
        # `look_now` may return the last background result when the detector is slower than
        # this game frame. Those boxes belong to an older image; using them with this frame's
        # colour/team reads moves detections across time and can assign the wrong side. Keep
        # the large model only when it actually analyzed this frame; otherwise use the
        # current-frame side detector below.
        big_current = big if big_now else []
        with _LOCK:
            cards, ready = self._card_det.run(img)
            if big_now and not self.dual:
                allies, enemies = [], []             # one detector this look (the big one, same moment)
                self.single_used += 1
            else:
                allies, enemies = self.units.run(img)
            nums = self.numbers.run(img)
        t_models = time.perf_counter()
        hand = [c.name for c in cards[1:5]]
        nxt = cards[0].name
        # the picture each hand card shows: "_ev1" = its evolution is charged (this play comes out evolved),
        # "_hero" = a hero card (its ability button comes up when it is on the field)
        hand_look = list(getattr(self._card_det, "last_variants", [""] * 5))[1:5]
        try:                                         # the hand-card model (6.6): sure where the pictures mix up
            nxt, hand, hand_look = self._hand_model(frame_rgb, nxt, hand, hand_look)
        except Exception:
            pass
        t_hand = time.perf_counter()
        now = time.monotonic()
        h, w = frame_rgb.shape[:2]
        kx, ky = w / float(C.SCREENSHOT_WIDTH), h / float(C.SCREENSHOT_HEIGHT)
        # every unit found, with its box on the real picture and what the small side model said
        raw = [(d.unit.name, float(d.position.conf), tuple(v * k for v, k in zip(d.position.bbox, (kx, ky, kx, ky))),
                side, "units") for lst, side in ((enemies, "enemy"), (allies, "ally")) for d in lst]
        hp, spells = {}, []
        if big_current:
            try: hp, spells = self._health()
            except Exception: pass
        en, al = self._units(frame_rgb, raw, big_current, img, now, hp, spells)
        t_track = time.perf_counter()
        self.last_timings = {
            "prep_ms": round((t_prep - started) * 1000, 1),
            "big_ms": round((t_big - t_prep) * 1000, 1),
            "models_ms": round((t_models - t_big) * 1000, 1),
            "hand_ms": round((t_hand - t_models) * 1000, 1),
            "track_ms": round((t_track - t_hand) * 1000, 1),
            "total_ms": round((t_track - started) * 1000, 1),
        }
        return {
            "next": nxt, "hand": hand, "ready": list(ready), "hand_look": hand_look,
            "elixir": float(nums.elixir.number),
            "enemies": en,
            "allies": al,
            "towers": {"their_left": nums.left_enemy_princess_hp.number, "their_right": nums.right_enemy_princess_hp.number,
                       "our_left": nums.left_ally_princess_hp.number, "our_right": nums.right_ally_princess_hp.number},
            "hp": hp, "spells": spells, "evo": list(getattr(self, "evo_now", []) or []),
            "tracks": self.tracker.snapshot(now),
            "vision_source": "large-current-frame" if big_now else "small-current-frame",
            "t": now, "_seen_t": seen_t,
        }

    def _health(self):
        """Health bars of their units + spells landing, from the big model's last picture (royale.health)."""
        from royale import strong_eyes, health
        seen = strong_eyes.last_seen()
        if not seen or time.monotonic() - strong_eyes._A.get("t", 0) > 0.8: return {}, []
        fr, dets = seen
        h, w = fr.shape[:2]

        def tile_of(px, py):
            dx, dy = px * 720.0 / w, py * 1280.0 / h
            return (int(round((dx - C.TILE_INIT_X) / C.TILE_WIDTH - 0.5)),
                    int(round((C.DISPLAY_HEIGHT - C.TILE_INIT_Y - dy) / C.TILE_HEIGHT - 0.5)))
        return health.read(fr, dets, tile_of, lambda u, box: True)


    @staticmethod
    def _tile_f(box, w, h):
        """A box on the picture -> the unit's feet in tiles (floats; the int tile is round())."""
        x0, y0, x1, y1 = box
        dx, dy = (x0 + x1) / 2 * 720.0 / w, y1 * 1280.0 / h
        return ((dx - C.TILE_INIT_X) / C.TILE_WIDTH - 0.5, (C.DISPLAY_HEIGHT - C.TILE_INIT_Y - dy) / C.TILE_HEIGHT - 0.5)

    def _units(self, frame, raw, big, small, now, hp=None, spells=None):
        """Both eye models' units -> (enemies, allies) [(unit, tile x, tile y, conf)], every one followed by the
        tracker (6.6). Ours or theirs, from the surest evidence down:
          the colour over its head (its level badge — there even at full health — or its health bar): 2-3 votes
          the small side model (only asked for units of our deck): 1 vote
          not a unit of our deck (so it can only be theirs; not in 2v2, where the partner's are ours too): 1.5
          the track's own history: once 3 votes ahead it keeps its side (a doubtful look can not flip it)
        The same unit seen by both models on the same tile is kept once (the big model's finer box, surer)."""
        from royale import strong_eyes
        from royale.unit_tracker import Det
        h, w = frame.shape[:2]
        try: self.colors.prepare(frame)
        except Exception: pass
        sw, sh = small.width / w, small.height / h
        # Keep the side classifier's last answer for a nearby tracked unit. Calling the
        # 16x16 ONNX model for every unit on every look serialized many GPU syncs.
        self._side_cache = [c for c in self._side_cache if now - c[4] <= 0.8]
        cand = []                                          # (unit, conf, box, side_model or None, evolved, col_read)
        for u, cf, box, side, _src in raw:
            cand.append([u, cf, box, side if u in self.units.possible_ally_names else None, False, None])
        self.evo_now = []
        for name, cf, x0, y0, x1, y1 in big or []:
            u = strong_eyes.unit_name(name)
            if not u: continue
            box = (x0, y0, x1, y1)
            fx, fy = self._tile_f(box, w, h)
            try: col_read = self.colors.team(box)
            except Exception: col_read = (None, 0.0)
            side = None
            if u in self.units.possible_ally_names and col_read[1] < 2.0:
                cached = next((c for c in reversed(self._side_cache)
                               if c[0] == u and abs(c[1] - fx) <= 1.2 and abs(c[2] - fy) <= 1.2), None)
                if cached:
                    side = cached[3]
                    self._side_cache.remove(cached)
                    self._side_cache.append((u, fx, fy, side, now))
                try:
                    if side is None:
                        side = self.units.side_detector.run(small.crop((int(x0 * sw), int(y0 * sh), int(x1 * sw) + 1, int(y1 * sh) + 1)))
                        self._side_cache.append((u, fx, fy, side, now))
                except Exception:
                    side = None
            same = None
            for c in cand:
                if c[0] != u: continue
                gx, gy = self._tile_f(c[2], w, h)
                if abs(gx - fx) <= 1.2 and abs(gy - fy) <= 1.2: same = c; break
            if same is None:
                cand.append([u, cf, box, side, name.endswith("-evolution"), col_read])
            else:
                # both eyes see it on the same tile: surer than either alone (5.83); the big model's box is finer
                same[1] = min(0.99, 1 - (1 - float(same[1])) * (1 - float(cf)))
                same[2] = box
                same[3] = side or same[3]
                same[4] = same[4] or name.endswith("-evolution")
                same[5] = col_read
        # the towers the big model sees this look: a "unit" whose middle sits INSIDE one is a tower skin / decoration
        # until it moves (6.8: skulls / Christmas decorations were read as Archers and Wall Breakers)
        towers = []
        for name, cf, x0, y0, x1, y1 in big or []:
            if name.endswith("-tower") and cf >= 0.4:
                mx, my = 0.15 * (x1 - x0), 0.15 * (y1 - y0)
                towers.append((x0 + mx, y0 + my, x1 - mx, y1 - my))
        dets, extra = [], []
        for u, cf, box, side, evolved, col_read in cand:
            fx0, fy0 = self._tile_f(box, w, h)
            if not (-0.5 <= fx0 <= 17.5 and -0.5 <= fy0 <= 31.5): continue     # the arena's edge / the buttons below
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            on_tower = any(a <= cx <= c and b <= cy <= d for a, b, c, d in towers)
            if on_tower and cf < 0.6: continue                                 # a doubtful one on a tower: never
            votes = {"ally": 0.0, "enemy": 0.0}
            if col_read is not None:
                col, sure = col_read
            else:
                try: col, sure = self.colors.team(box)
                except Exception: col, sure = None, 0.0
            if col: votes[col] += sure
            if side in ("ally", "enemy"): votes[side] += 1.0
            if u not in self.units.possible_ally_names and not self.two_v_two: votes["enemy"] += 1.5
            team = max(votes, key=votes.get) if any(votes.values()) else None
            fx, fy = self._tile_f(box, w, h)
            dets.append(Det(u, fx, fy, float(cf), team, abs(votes["ally"] - votes["enemy"]), box, on_tower))
            extra.append(evolved)
        en, al = [], []
        for (d, tr), evolved in zip(self.tracker.update(dets, now), extra):
            if tr is None: continue            # 6.8: not followed (a doubtful new box, a tower decoration): not a unit
            # the track's side once settled; a new / doubtful one: this look's evidence
            # 6.9.17: the track's whole record (where it was born, our own placement, every colour / side-model read)
            team = tr.team
            tx, ty = int(round(d.x)), int(round(d.y))
            if evolved and team != "ally": self.evo_now.append((d.name, tx, ty))
            (al if team == "ally" else en).append((d.name, tx, ty, d.conf))
            if tr is not None and hp:                        # its health bar, for the hidden-for-a-moment rule
                lf = self._match_hp(hp, d.name, tx, ty)
                if lf is not None: tr.life = float(lf)
        # 6.7: a followed unit hidden for a moment (a spell's flash, behind a tower) stays in the battle state for
        # 0.4 s, moved on its speed — the engine does not plan as if it died and change its mind when it is back
        for tr in self.tracker.ghosts(now, dead=lambda t: self._killed(t, spells)):
            x, y = tr.at(now)
            (al if tr.team == "ally" else en).append((tr.name, int(round(x)), int(round(y)), max(0.5, 0.9 * tr.conf)))
        return en, al

    @staticmethod
    def _match_hp(hp, name, tx, ty):
        """Exact (name, tx, ty) match, else closest matching unit within 2 tiles when health frame lagged."""
        lf = hp.get((name, tx, ty))
        if lf is not None: return lf
        best_d, best_lf = 2.25, None
        for (nm, hx, hy), val in hp.items():
            if nm != name: continue
            dist = math.hypot(hx - tx, hy - ty)
            if dist <= best_d:
                best_d, best_lf = dist, val
        return best_lf

    @staticmethod
    def _killed(tr, spells):
        """A damage spell that landed on it in this look kills it (its life left x its hp <= the spell's damage)."""
        if not spells: return False
        try:
            from royale.brain import card, unit_card, SPELL_DAMAGE_DEFAULT, SPELL_SPLASH_DEFAULT
            c = card(unit_card(tr.name) or "") or {}
            hp_left = (c.get("hp") or 300) * (tr.life if tr.life is not None else 1.0)
            for sp, sx, sy in spells:
                s = card(sp) or {}
                rad = s.get("splash") or SPELL_SPLASH_DEFAULT.get(sp, 2.5)
                dmg = s.get("damage") or SPELL_DAMAGE_DEFAULT.get(sp, 100)
                if math.hypot(tr.x - sx, tr.y - sy) <= rad + 0.5 and hp_left <= dmg: return True
        except Exception:
            return False
        return False

    def _hand_model(self, frame, nxt, hand, looks):
        """The hand-card model's reading where it is sure, else the picture matcher's (royale.hand_classifier)."""
        from royale import hand_classifier
        if self.hand_cls is None:
            self.hand_cls = hand_classifier.HandClassifier.load()
            if self.hand_cls is None: return nxt, hand, looks
        allowed = set(self.deck) if len(self.deck) == 8 else None
        out = self.hand_cls.read(frame, allowed=allowed, known=set(self.by_name))
        if not out: return nxt, hand, looks
        names = [nxt] + list(hand)
        looks5 = [""] + list(looks)
        for k, r in enumerate(out[:5]):
            if r is None: continue
            names[k], looks5[k] = r
        return names[0], names[1:5], looks5[1:5]


# ------------------------------------------------------------------ where to tap (fractions of the screen)
def tile_xy(tile_x, tile_y):
    x = C.TILE_INIT_X + (tile_x + 0.5) * C.TILE_WIDTH
    y = C.DISPLAY_HEIGHT - C.TILE_INIT_Y - (tile_y + 0.5) * C.TILE_HEIGHT
    return x / C.DISPLAY_WIDTH, y / C.DISPLAY_HEIGHT


def card_xy(slot):
    x = C.DISPLAY_CARD_INIT_X + C.DISPLAY_CARD_WIDTH / 2 + slot * C.DISPLAY_CARD_DELTA_X
    y = C.DISPLAY_CARD_Y + C.DISPLAY_CARD_HEIGHT / 2
    return x / C.DISPLAY_WIDTH, y / C.DISPLAY_HEIGHT


def in_battle(frame_rgb):
    """The elixir bar (purple) at the bottom = a battle is on. Cheap pixel check."""
    import numpy as np
    h, w = frame_rgb.shape[:2]
    box = frame_rgb[int(h * 0.955):int(h * 0.99), int(w * 0.03):int(w * 0.96)].astype(np.int16)
    if box.size == 0: return False
    purple = (box[..., 0] > 150) & (box[..., 2] > 150) & (box[..., 1] < 110)
    drop = frame_rgb[int(h * 0.93):int(h * 0.985), int(w * 0.03):int(w * 0.13)].astype(np.int16)
    drop_p = ((drop[..., 0] > 150) & (drop[..., 2] > 150) & (drop[..., 1] < 110)).mean() if drop.size else 0
    return float(purple.mean()) > 0.02 or float(drop_p) > 0.08
