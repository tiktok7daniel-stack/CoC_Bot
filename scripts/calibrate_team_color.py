r"""
Measure the ours / theirs badge colours on THIS PC's real battles (6.7) instead of guessing them:

    .venv\Scripts\python scripts\calibrate_team_color.py                 the bot's saved battle pictures (royale.frames)
    .venv\Scripts\python scripts\calibrate_team_color.py shot1.png ...   battle screenshots you took (ours + theirs on it)

Each unit's side comes WITHOUT the colour (a unit of none of the account's cards is theirs; the side model, ours only
on our half and theirs only on theirs), then the badge / health-bar pixels over it give the hue ranges. Saved to
~/.CoC_Bot/team_color.json — the eyes use them from the next battle. The training (royale.trainer) also runs it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def from_screenshots(paths):
    import numpy as np, os
    from PIL import Image
    from royale import strong_eyes, team_color
    from royale.eyes import Eyes
    from royale.brain import unit_card
    from royale.vision import constants as C
    from royale.vision.detectors.side_detector import SideDetector
    if not strong_eyes.ensure():
        print("the big eyes model is not on this PC yet (it downloads on the first Clash Royale start)"); return
    mine = {c for d in Eyes.known_decks() for c in d}
    side = SideDetector(os.path.join(C.MODELS_DIR, "side.onnx"))
    samples = []
    for p in paths:
        fr = np.array(Image.open(p).convert("RGB"))
        pil = Image.fromarray(fr)
        h = fr.shape[0]
        x0a, y0a, x1a, y1a = strong_eyes.arena_box(fr.shape)
        mid = (y0a + y1a) / 2
        for name, cf, x0, y0, x1, y1 in strong_eyes.detect(fr, conf=0.5):
            u = strong_eyes.unit_name(name)
            if not u: continue
            cn = unit_card(u)
            if mine and cn and cn not in mine:
                samples.append((fr, (x0, y0, x1, y1), "enemy")); continue
            sd = side.run(pil.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1)))
            low = (y0 + y1) / 2 > mid
            if sd == "ally" and low: samples.append((fr, (x0, y0, x1, y1), "ally"))
            elif sd == "enemy" and not low: samples.append((fr, (x0, y0, x1, y1), "enemy"))
    res = team_color.calibrate(samples)
    print(f"ours: {res['n']['ally']} badges -> {res['ally']}\ntheirs: {res['n']['enemy']} badges -> {res['enemy']}"
          + ("\nthey overlapped: the defaults stay" if res.get("overlap") else ""))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        from_screenshots(sys.argv[1:])
    else:
        from royale import team_color
        team_color.auto_calibrate()
