"""
The Clash Royale eyes: one look at the game (720x1280 portrait, any size scaled) -> everything the brain needs.
  hand / next card / which cards can be played   (card pictures of 139 cards, ClashRoyaleBuildABot)
  our elixir                                      (the elixir bar)
  every unit in the arena, ours or theirs, tile   (YOLO units model 97 kinds + ally / enemy model)
  the 4 princess towers' health                   (their health bars)
The deck is found by itself: in the first seconds of a battle every hand card is compared with all 139 pictures;
once the 8 are known the comparison is only among them (faster, no mix-up).
"""
import os, threading, time

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
        self._card_det = None
        self.set_deck(deck or [])

    # -------------------------------------------------------------- the deck
    def set_deck(self, names):
        from royale.vision.detectors.card_detector import CardDetector
        names = [n for n in names if n in self.by_name][:8]
        self.deck = names
        cards = [self.by_name[n] for n in names] if len(names) == 8 else self.all_cards
        self._card_det = CardDetector(cards)
        # units that can be ours: only those of our deck are asked "ours or theirs?" (others are theirs)
        self.units.cards = [self.by_name[n] for n in names]
        self.units.possible_ally_names = {u.name for n in names for u in self.by_name[n].units}

    def learn_deck(self, hand):
        """Hand cards seen in the first looks of a battle -> the deck once 8 different ones were seen 2+ times."""
        if len(self.deck) == 8: return False
        for n in hand:
            if n and n != "blank": self.seen_counts[n] = self.seen_counts.get(n, 0) + 1
        sure = [n for n, k in sorted(self.seen_counts.items(), key=lambda kv: -kv[1]) if k >= 2][:8]
        if len(sure) == 8:
            self.set_deck(sure)
            return True
        # cards seen so far can be ours already (ally / enemy check for them)
        self.units.possible_ally_names = {u.name for n in sure for u in self.by_name[n].units}
        return False

    # -------------------------------------------------------------- one look
    def look(self, frame_rgb):
        """frame_rgb: numpy RGB of the game screen. -> dict (see module doc)."""
        import numpy as np
        from PIL import Image
        img = Image.fromarray(frame_rgb).convert("RGB").resize((C.SCREENSHOT_WIDTH, C.SCREENSHOT_HEIGHT),
                                                                Image.Resampling.BILINEAR)
        with _LOCK:
            cards, ready = self._card_det.run(img)
            allies, enemies = self.units.run(img)
            nums = self.numbers.run(img)
        hand = [c.name for c in cards[1:5]]
        en = [(d.unit.name, d.position.tile_x, d.position.tile_y, float(d.position.conf)) for d in enemies]
        al = [(d.unit.name, d.position.tile_x, d.position.tile_y, float(d.position.conf)) for d in allies]
        hp, spells = {}, []
        try:                                         # the stronger eyes (174 kinds), in the background: never waited for
            from royale import strong_eyes
            if strong_eyes.ready():
                strong_eyes.submit(frame_rgb)
                self._merge(strong_eyes.latest(), frame_rgb.shape, img, en, al)
                hp, spells = self._health()
        except Exception:
            pass
        return {
            "next": cards[0].name, "hand": hand, "ready": list(ready),
            "elixir": float(nums.elixir.number),
            "enemies": en,
            "allies": al,
            "towers": {"their_left": nums.left_enemy_princess_hp.number, "their_right": nums.right_enemy_princess_hp.number,
                       "our_left": nums.left_ally_princess_hp.number, "our_right": nums.right_ally_princess_hp.number},
            "hp": hp, "spells": spells,
            "t": time.monotonic(),
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


    def _merge(self, dets, shape, small, en, al):
        """The stronger eyes' units added to the lists (same unit on the same tile: kept once, best confidence).
        Ours or theirs: our deck's units asked to the ally / enemy model, every other unit is theirs."""
        from royale import strong_eyes
        h, w = shape[:2]
        sw, sh = small.width / w, small.height / h
        for name, cf, x0, y0, x1, y1 in dets:
            u = strong_eyes.unit_name(name)
            if not u: continue
            dx, dy = (x0 + x1) / 2 * 720.0 / w, y1 * 1280.0 / h               # the 720x1280 game, bottom-centre
            tx = int(round((dx - C.TILE_INIT_X) / C.TILE_WIDTH - 0.5))
            ty = int(round((C.DISPLAY_HEIGHT - C.TILE_INIT_Y - dy) / C.TILE_HEIGHT - 0.5))
            side = "enemy"
            if u in self.units.possible_ally_names:
                try:
                    side = self.units.side_detector.run(small.crop((int(x0 * sw), int(y0 * sh), int(x1 * sw) + 1, int(y1 * sh) + 1)))
                except Exception:
                    pass
            lst = al if side == "ally" else en
            same = next((k for k, d in enumerate(lst) if d[0] == u and abs(d[1] - tx) <= 1 and abs(d[2] - ty) <= 1), None)
            if same is None: lst.append((u, tx, ty, cf))
            elif cf > lst[same][3]: lst[same] = (u, tx, ty, cf)


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
