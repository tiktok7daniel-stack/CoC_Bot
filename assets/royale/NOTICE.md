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

## pro_wins.json
Results (victory / defeat, side-corrected), decks and card plays of the 252k RoyaleAPI Path-of-Legends replays in
VanguardX101/IL_Replay, joined game by game by scripts/build_royale_wins.py: how often each answer, deck and
attack combo won. Only aggregated counts are shipped.

## cards/ (berserker, boss_bandit, goblin_curse, goblin_demolisher, goblin_machine, goblinstein, suspicious_bush, vines, rune_giant, spirit_empress, void)
Card pictures from RoyaleAPI's cr-api-assets (https://github.com/RoyaleAPI/cr-api-assets), cropped to the bot's
card format. Elixir costs of Rune Giant / Spirit Empress / Void worked out from the replays' deck average elixir.

## attack_atlas.json, the evolutions' numbers, the recent pro plays in pro.json
attack_atlas.json: scripts/build_royale_attack_atlas.py (simulated against the defenses of the replays).
cards.json "evo": RoyaleFish data_16635 card_logic (Apache-2.0), scripts/build_royale_stats.py --evo.
pro.json "place" also holds 11k recent pro plays from hastylmao/Hasty-CR data/vod (MIT), scripts/build_royale_vod.py.

## cards/*_ev1.jpg, *_hero.jpg, *_hero_ev1.jpg
The evolved and hero card pictures: RoyaleAPI cr-api-assets (cards-150), https://github.com/RoyaleAPI/cr-api-assets,
under Supercell's Fan Content Policy (https://supercell.com/en/fan-content-policy/); scripts/import_card_variants.py.
bowler_hero.jpg: cut from the user's own deck screenshot (not in cr-api-assets yet).
