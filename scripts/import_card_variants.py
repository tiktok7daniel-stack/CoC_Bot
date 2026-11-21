"""
The hand shows a card's EVOLVED picture when its evolution is charged and a HERO card's own picture (Hero Bowler,
Hero Knight, ...): the eyes had only the plain pictures, so those cards were not recognised (the user's evolved
Witch / Musketeer and Hero Bowler) and the deck was never learned. This copies every evolution / hero picture of
RoyaleAPI's cr-api-assets (clone it: https://github.com/RoyaleAPI/cr-api-assets, cards-150/) next to the plain
ones as <card>_ev1.jpg, <card>_hero.jpg, <card>_hero_ev1.jpg (and plain pictures of cards the bot lacked).

  python scripts/import_card_variants.py <cr-api-assets/cards-150>
"""
import os, sys
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "royale", "cards")
SIZE = (252, 313)                      # the size of the pictures the eyes already have


def to_jpg(src, dst):
    im = Image.open(src).convert("RGBA")
    bg = Image.new("RGBA", im.size, (8, 8, 12, 255))           # the dark corners of the existing pictures
    bg.alpha_composite(im)
    bg.convert("RGB").resize(SIZE, Image.Resampling.LANCZOS).save(dst, quality=92)


def main(src):
    n = 0
    for f in sorted(os.listdir(src)):
        if not f.endswith(".png"): continue
        stem = f[:-4]
        suffix = ""
        for s in ("-hero-ev1", "-hero", "-ev1"):
            if stem.endswith(s):
                stem, suffix = stem[:-len(s)], s.replace("-", "_")
                break
        name = stem.replace("-", "_")
        dst = os.path.join(OUT, f"{name}{suffix}.jpg")
        if not suffix and os.path.exists(dst): continue        # the plain pictures the eyes were built with stay
        if suffix and not os.path.exists(os.path.join(OUT, f"{name}.jpg")): continue
        to_jpg(os.path.join(src, f), dst)
        n += 1
    print(f"{n} pictures added")


if __name__ == "__main__":
    main(sys.argv[1])
