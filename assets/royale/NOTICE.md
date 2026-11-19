# Clash Royale mode — third-party parts

- `models/units_M_480x352.onnx`, `models/side.onnx`, `cards/*.jpg` and the detector code in `src/royale/vision/`
  come from **ClashRoyaleBuildABot** (https://github.com/Pbatch/ClashRoyaleBuildABot, commit 6ad4bf9),
  MIT License, Copyright (c) 2022 Peter Batchelor — see `src/royale/vision/LICENSE_BuildABot.md`.
- `cards.json` numbers (hitpoints, damage, speed, range, splash…) are read from the game-data tables published by
  **RoyaleFish** (https://github.com/fabiospalla9-tech/RoyaleFish, `data_16635/`, Apache-2.0) with
  `scripts/build_royale_cards.py`.

Not affiliated with, endorsed by, or representative of Supercell.

## pro.json
Statistics (what answered what, where cards are played, what follows what) counted from the public
IL_Replay dataset (https://huggingface.co/datasets/VanguardX101/IL_Replay, 252,197 games) by
scripts/build_royale_pro.py. Only aggregated counts are shipped, no replay data.
