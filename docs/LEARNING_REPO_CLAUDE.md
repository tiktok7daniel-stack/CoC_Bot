# Clash Farmer learning repo — instructions for Claude

This private repo is the learning inbox of the Clash Farmer bot (source: tiktok7daniel-stack/CoC_Bot).
The bot uploads every game screen it did not understand to `inbox/`, and pictures of armies it learned to `armies/`.
Your job: teach the bot. Follow `LEARNING.md` exactly:

1. List `inbox/**/*.jpg` whose file name (without `.jpg`) is not a key in `knowledge/status.json` -> `items`.
2. Open each picture and its `.json` (the OCR words the bot read, the phase, what it already tried).
3. Add or extend a rule in `knowledge/screens.json` (match words + safe actions), or note that nothing is needed.
4. Mark every handled picture in `knowledge/status.json` with `done: true`, the rule id and an Arabic `note_ar`
   (short, what the screen is and what the bot will do now).
5. Never write actions that spend gems, buy, log out, leave a clan or exit the game.
6. Commit as "learn: N screens" and push to `main`. The bot fetches the rules by itself and rebuilds README.md.

Write user-facing text (`note_ar`, `title_ar`) in Egyptian Arabic.

## Capture sessions (`captures/<session>_<account>/`)

The user can also play while the bot photographs every new screen ("capture mode"), review the pictures and
send them here in one commit. Each session folder has `NNN.jpg` + `NNN.json` (OCR words, `tap` = where the user
tapped before that screen, as fractions of the screen) and a `README.md` table.
When the user says in the chat that they sent a capture:
- go through every picture in order (the taps show the path the user took through the game)
- add rules to `knowledge/screens.json` for screens the bot must be able to handle (popups, menus, buttons on the way)
- for army screens, write the composition to `knowledge/armies.json` (`{"<name or session/NNN>": {"troops": {...}, "spells": {...}, "heroes": [...]}}`)
- mark each picture in `knowledge/status.json` with key `captures/<session folder>/<NNN>` and an Egyptian-Arabic `note_ar`
- reply to the user in Arabic with what was learned from each picture
