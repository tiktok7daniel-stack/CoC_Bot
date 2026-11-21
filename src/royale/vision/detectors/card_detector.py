import os
from collections.abc import Sequence

import numpy as np
from PIL import Image
from scipy.optimize import linear_sum_assignment

from royale.vision.constants import CARD_CONFIG, IMAGES_DIR
from royale.vision.namespaces.cards import Card, Cards

# the card pictures the bot cut from the player's own Info pages (royale.card_scan)
USER_DIR = os.path.join(os.path.expanduser("~"), ".CoC_Bot", "learn", "royale_cards")


class CardDetector:
    HAND_SIZE = 5
    MULTI_HASH_SCALE = 0.355
    MULTI_HASH_INTERCEPT = 163

    def __init__(
        self,
        cards: Sequence[Card],
        hash_size: int = 8,
        grey_std_threshold: int = 5,
    ):
        # Build a new list rather than extending the caller's. The blanks let
        # the matcher assign empty hand slots.
        self.cards = [*cards, *([Cards.BLANK] * self.HAND_SIZE)]
        self.hash_size = hash_size
        self.grey_std_threshold = grey_std_threshold

        self.card_hashes = self._calculate_card_hashes()

    def _calculate_multi_hash(self, image):
        gray_image = self._calculate_hash(image)
        light_image = (
            self.MULTI_HASH_SCALE * gray_image + self.MULTI_HASH_INTERCEPT
        )
        dark_image = (
            gray_image - self.MULTI_HASH_INTERCEPT
        ) / self.MULTI_HASH_SCALE
        multi_hash = np.vstack([gray_image, light_image, dark_image]).astype(
            np.float32
        )
        return multi_hash

    def _calculate_hash(self, image):
        return np.array(
            image.resize(
                (self.hash_size, self.hash_size), Image.Resampling.BILINEAR
            ).convert("L"),
            dtype=np.float32,
        ).ravel()

    # plain, evolved, hero, evolved hero; "_user" = the same card cut from the player's own screen (the game's
    # current art can differ from the published pictures)
    VARIANTS = ("", "_ev1", "_hero", "_hero_ev1", "_user", "_ev1_user", "_hero_user")

    def _calculate_card_hashes(self):
        """Every card with every picture it can show in the hand: plain, evolved (its evolution is charged), hero
        and evolved hero -> one row each; the closest picture of a card is its distance."""
        rows, self.row_card, self.row_variant = [], [], []
        try:
            for i, card in enumerate(self.cards):
                for v in self.VARIANTS:
                    path = os.path.join(IMAGES_DIR, "cards", f"{card.name}{v}.jpg")
                    if v.endswith("_user"):                  # the bot's own pictures (royale.card_scan) come first
                        own = os.path.join(USER_DIR, f"{card.name}{v}.jpg")
                        if os.path.exists(own): path = own
                    if v and not os.path.exists(path): continue
                    multi_hash = self._calculate_multi_hash(Image.open(path))
                    rows.append(np.tile(np.expand_dims(multi_hash, axis=2), (1, 1, self.HAND_SIZE)))
                    self.row_card.append(i)
                    self.row_variant.append(v)
        except Exception as e:
            raise RuntimeError("Can't load cards and their images."
            ) from e
        self.row_card = np.array(self.row_card)
        self.last_variants = [""] * self.HAND_SIZE
        return np.stack(rows).astype(np.float32)

    def _detect_cards(self, image):
        crops = [image.crop(position) for position in CARD_CONFIG]
        crop_hashes = np.array(
            [self._calculate_hash(crop) for crop in crops]
        ).T
        row_diffs = np.mean(
            np.amin(np.abs(crop_hashes - self.card_hashes), axis=1), axis=1
        )                                                        # (pictures, hand slots)
        n = len(self.cards)
        hash_diffs = np.full((n, row_diffs.shape[1]), np.inf, np.float32)
        best_row = np.zeros((n, row_diffs.shape[1]), np.int64)
        for r in range(row_diffs.shape[0]):
            c = self.row_card[r]
            better = row_diffs[r] < hash_diffs[c]
            hash_diffs[c][better] = row_diffs[r][better]
            best_row[c][better] = r
        _, idx = linear_sum_assignment(hash_diffs.T)
        cards = [self.cards[i] for i in idx]
        # which picture it showed: "_ev1" = its next play comes out evolved, "_hero" = it is a hero card
        self.last_variants = [self.row_variant[best_row[i][k]] for k, i in enumerate(idx)]

        return cards, crops

    def _detect_if_ready(self, crops):
        ready = []
        for i, crop in enumerate(crops[1:]):
            std = np.mean(np.std(np.array(crop), axis=2))
            if std > self.grey_std_threshold:
                ready.append(i)
        return ready

    def run(self, image):
        cards, crops = self._detect_cards(image)
        ready = self._detect_if_ready(crops)
        return cards, ready
