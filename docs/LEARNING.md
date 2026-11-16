# Clash Farmer — learning protocol (for Claude)

The bot (Clash Farmer) sends every screen it could not understand to a **learning repo** on GitHub
(set in the app: Bot → Learning with Claude). A Claude session teaches the bot by reading those pictures
and writing rules back into the same repo. The bot fetches the rules every few minutes and uses them
the next time it sees that screen.

## What the bot writes

```
inbox/<YYYYMMDD>/<account>_<YYYYMMDD_HHMMSS>.jpg    screenshot, 960x540
inbox/<YYYYMMDD>/<account>_<YYYYMMDD_HHMMSS>.json   {"words": [...OCR words...], "phase": "...", "action": "tap:Later" | "", "t": ..., "bot_version": "..."}
armies/<name>.jpg                                    the army screen of a learned army
armies/<name>.json                                   {"name", "steps": [{"x","y","word","gap"}], ...}
```

`phase` is what the bot was doing (start_game, to_home, home_attack, …); `action` is what it already tried.

## What Claude writes

### `knowledge/screens.json`

```json
{
  "version": 1,
  "screens": [
    {
      "id": "season_bank_popup",
      "title": "Season bank popup",
      "title_ar": "نافذة بنك الموسم",
      "match_all": ["season bank"],
      "match_any": ["claim", "collect"],
      "phase": "",
      "actions": [
        {"type": "tap_word", "word": "claim", "x": 0.5, "y": 0.82},
        {"type": "wait", "s": 1},
        {"type": "close"}
      ],
      "source": "inbox/20261116/main_20261116_101010.jpg"
    }
  ]
}
```

- `match_all`: lowercase words/phrases that must ALL appear in the OCR text (use the `.json` words, they
  are exactly what the bot reads). Pick 1–3 distinctive ones; never only generic words like "okay".
- `match_any` (optional): at least one must appear. `phase` (optional): only in that phase.
- `actions` (max 8, in order):
  - `tap_word` — tap the OCR word (fuzzy); `x`/`y` (fractions 0–1 of the screen) is the fallback position
  - `tap` — tap `x`, `y` (fractions)
  - `wait` — `s` seconds (≤ 10)
  - `close` — tap the top-right corner (closes most windows)
- **Never** write actions that spend gems, buy anything, log out, leave/delete the clan or exit the game.
  For those screens use a rule whose action is `close` (or a `tap_word` on "cancel"/"no").

### `knowledge/status.json`

```json
{"items": {"main_20261116_101010": {"done": true, "rule": "season_bank_popup", "note_ar": "نافذة بنك الموسم — البوت هيدوس Claim ويقفل"}}}
```

One entry per inbox picture (key = file name without extension). `done: true` shows **✓ learned** in the
app next to that picture with the Arabic note. Pictures that need nothing (loading screens, a normal
screen the bot already knows) get `done: true` with a note saying so and no rule.

## The routine

1. Pull the learning repo; list `inbox/**.jpg` whose name is not yet in `knowledge/status.json`.
2. For each: look at the picture and its `.json` words; decide what screen it is and the safe way out
   or forward; add/extend a rule (reuse an existing rule if the same screen appears again).
3. For `armies/*.jpg`: optionally add `knowledge/armies.json` `{"<name>": {"troops": {"dragon": 10, ...}, "spells": {...}}}`.
4. Update `knowledge/status.json` for every picture handled, commit ("learn: N screens"), push.
