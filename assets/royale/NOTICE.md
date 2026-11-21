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

## KataCR dataset (training data, downloaded on the user's PC, not shipped)
Clash-Royale-Detection-Dataset by wty-yy (https://github.com/wty-yy/Clash-Royale-Detection-Dataset), MIT License,
Copyright (c) 2024 wty: real labelled arena pictures and cut-out units used by royale.trainer to train the eyes,
including generated pictures (cut-outs pasted onto arenas, the KataCR "generative dataset" method).

## cards.json: sight, radius, deploy_ms, life_s, mass, levels
From the game's data tables as published by RoyaleAPI (cr-api-data, https://royaleapi.github.io/cr-api-data/),
via the copy kept in hastylmao/Hasty-CR (MIT License, Copyright (c) 2026 HastyCR contributors), merged by
scripts/build_royale_stats.py. Body blocking, tower-reading smoothing and the legal-tile mask follow ideas from
Hasty-CR and advaynathany/alphaclash (MIT); no code copied.
