"""
Per-account settings edited from the GUI.

Every account (instance ID) has its own JSON file in ~/.CoC_Bot/settings/<id>.json.
Defaults come from configs.py, so an untouched account behaves exactly as before.
The bot re-reads the file at the start of every cycle, so changes saved in the GUI
apply without restarting the bot.
"""
import sys, json, copy, os
from pathlib import Path

try:
    import configs
except:
    import configs_build as configs

APP_DATA_DIR = Path.home() / ".CoC_Bot"
SETTINGS_DIR = APP_DATA_DIR / "settings"
GLOBAL_PATH = APP_DATA_DIR / "app_settings.json"

def _cfg(name, default):
    return copy.deepcopy(getattr(configs, name, default))

def default_settings():
    return {
        "preset": "balanced",        # "safe" | "balanced" | "fast" | "custom"
        "clash_tag": "",             # the player tag (#ABC123) for the official Clash of Clans API
        "follow": "",                # plays like this account (its loadouts, recording, army, farm…), "" = own settings
        "game_mode": "coc",          # "coc" = Clash of Clans | "royale" = Clash Royale (LDPlayer 720x1280 portrait)
        "game_mode_set": "",         # "user" = the user picked this game (only that counts, never a guess)
        "royale": {                  # Clash Royale mode
            "deck": [],              # the 8 cards (found by itself in the first battle; can be set)
            "tag": "",               # player tag (#ABC123) for the official Clash Royale API (exact deck / results)
            "auto_deck": True,       # the bot picks the strongest deck you own (API + the meta) and copies it in
            "safe_play": True,       # never experiments in a battle: the best known way every time (still learns)
            "scan_cards": True,      # weekly: every card's Info page photographed and read (royale.card_scan)
            "local_ai": False,       # True: the local AI model (royale.board + royale.policy, learning every battle) plays
            "confirm_battles": False,  # True: waits in the lobby for the app's "Start a battle" button before each battle
            # the deck the bot puts in when the official API is not set up (8 cards). Hog 2.6: picked for this account
            # from 252k replays (52% over 14,280 games, side-corrected) and its levels (Hog / Cannon 15, ~13.6 avg)
            "wanted_deck": ["hog_rider", "cannon", "musketeer", "fireball", "ice_golem", "skeletons", "ice_spirit", "the_log"],
            "deck_slot": 0,          # the deck slot it uses (1-10; 0 = the slot selected in the game)
            "max_battles": 0,        # stop after this many battles (0 = keep playing)
            "notify": True,          # every result to the phone
            "auto_train": True,      # train the eyes on this PC's NVIDIA card by themselves (once a week at most)
            "manage_account": True,  # between battles: upgrade cards with gold, clan donations / requests, daily report
            "learned_brain": True,   # the neural network trained on 17 M real plays helps every decision
            "keep_frames": True,     # keep pictures of its battles: the eyes are trained on this PC's own screen
            "roboflow_datasets": [   # Roboflow datasets added to the training (needs the Roboflow key in Bot settings)
                "yolotrain-c7s7v/clash-royale-ut3g8/4", "clashroyale/clash-royale-of3d3/3",
                "angelfire/clash-royale-cylln/5", "clash-pxdrz/clash_grid/1", "dampiix/clash-royale-units/1",
                "nathan-yan/clash-royale-detection-cysig/7"],
        },
        "tasks": {
            "home_base": _cfg("UPGRADE_HOME_BASE", True),
            "heroes": _cfg("UPGRADE_HEROES", True),
            "home_lab": _cfg("UPGRADE_HOME_LAB", True),
            "pet_house": _cfg("UPGRADE_PETS", True),
            "builder_apprentice": _cfg("ASSIGN_BUILDER_APPRENTICE", True),
            "lab_assistant": _cfg("ASSIGN_LAB_ASSISTANT", True),
            "builder_base": _cfg("UPGRADE_BUILDER_BASE", True),
            "builder_lab": _cfg("UPGRADE_BUILDER_LAB", True),
            "home_attacks": _cfg("ATTACK_HOME_BASE", True),
            "builder_attacks": _cfg("ATTACK_BUILDER_BASE", True),
            "home_base_priority": _cfg("PRIORITY_HOME_BASE_UPGRADES", True),
            "home_lab_priority": _cfg("PRIORITY_HOME_LAB_UPGRADES", True),
            "pet_house_priority": _cfg("PRIORITY_PET_UPGRADES", True),
            "builder_base_priority": _cfg("PRIORITY_BUILDER_BASE_UPGRADES", True),
            "builder_lab_priority": _cfg("PRIORITY_BUILDER_LAB_UPGRADES", True),
        },
        "priorities": {
            "home_base": [l for l in ([x for x in lvl if x != "Wall"] for lvl in _cfg("HOME_BASE_UPGRADE_PRIORITY", [])) if l],
            "home_lab": _cfg("HOME_LAB_UPGRADE_PRIORITY", []),
            "pet_house": _cfg("PET_HOUSE_UPGRADE_PRIORITY", []),
            "builder_base": _cfg("BUILDER_BASE_UPGRADE_PRIORITY", []),
            "builder_lab": _cfg("BUILDER_LAB_UPGRADE_PRIORITY", []),
        },
        "walls": {
            "enabled": any("Wall" in lvl for lvl in _cfg("HOME_BASE_UPGRADE_PRIORITY", [])),
            "every_cycles": 1,       # upgrade walls every N cycles
            "max_per_run": 5,        # max wall upgrades per cycle
            "during_farming": False, # also upgrade walls between farming attacks
        },
        "budget": {
            "enabled": False,
            "keep_gold": 0,          # never spend gold below this
            "keep_elixir": 0,        # never spend elixir below this
            "keep_dark": 0,
        },
        "upgrades": {
            "max_per_cycle": _cfg("MAX_UPGRADES_PER_CHECK", 10),
            "every_cycles": 1,       # look for upgrades every N cycles (attacks run every cycle)
            "open_home_builders": _cfg("OPEN_HOME_BUILDERS", 0),
            "open_builder_builders": _cfg("OPEN_BUILDER_BUILDERS", 0),
            "start_from_menu_top": _cfg("START_FROM_MENU_TOP", True),
        },
        "attack": {
            "home_attacks_per_cycle": 2,
            "builder_attacks_per_cycle": 1,
            "troop_deploy_time": _cfg("TROOP_DEPLOY_TIME", 2),
            "slot_first": _cfg("ATTACK_SLOT_RANGE", (0, 100))[0],
            "slot_last": _cfg("ATTACK_SLOT_RANGE", (0, 100))[1],
            "exclude_clan_troops": _cfg("EXCLUDE_CLAN_TROOPS", True),
            "strategy": "auto",      # "auto" (learns the best) | "funnel" | "line" | "two_sides"
            "hero_delay": 1.0,       # seconds between the army and the heroes
            "hero_retap": 6,         # seconds after deploying to fire hero abilities (0 = off)
            "loot_filter": {         # skip bases with little loot (needs Next button + loot numbers taught)
                "enabled": False, "min_gold": 300000, "min_elixir": 300000, "min_dark": 0,
                "mode": "all", "max_skips": 30,
            },
            "farm": {                # attack non-stop; when the storages are full spend on walls/upgrades, then attack again
                "enabled": True,
                "gold_full": 0,      # gold counts as full from this amount (0 = learn the storage size by itself)
                "elixir_full": 0,
                "rest_minutes": 30,  # full and nothing to spend on: close the game and rest this long
                "walls_first": True, # storages full: all the walls the gold / elixir can pay first, then buildings
                "max_walls": False,  # wall-max mode: farm + walls until every wall is maxed, buildings too but 1 builder kept free
                "only": False,       # farm only: attack and collect, nothing else (no upgrades / walls / builder base / extras)
                "when_full": "pause", # farm only, a storage full: "pause" (you upgrade, then "كمل") | "wait" (attack again once you spent) | "stop"
                "full_rule": "any",   # "any": stop when gold OR elixir is full | "both": only when both are
            },
            "skip_when_full": {      # don't attack while the storages are (nearly) full
                "enabled": False, "gold": 0, "elixir": 0,
            },
            "battle_end": "wait",    # "wait" (game stays open) | "restart" (reopen game) | "leave" (end right after deploying)
            "leave_after": 0,        # "leave": seconds to wait after the army is down before ending
            "surrender_after": 0,    # seconds after deployment to end the battle early (0 = wait for the end)
            "smart_end": True,       # end the battle when the enemy loot stops going down
            "smart_end_after": 8,    # ... for this many seconds
        },
        "notify": {                  # phone (Telegram) + desktop notifications
            "upgrade_done": True,    # a running upgrade / lab research finished
            "auto_upgrade": True,    # the bot upgraded something
            "loot": False,           # loot summary after every attack
        },
        "limits": {
            "max_attacks": 0,        # stop after this many attacks in the session (0 = no limit)
            "max_hours": 0,          # stop after running this many hours (0 = no limit)
        },
        "breaks": {
            "enabled": False,        # not used: the bot never stops by itself (humanized breaks: close the game for a while now and then
            "every_minutes": 120,
            "length_minutes": 10,
        },
        # Loadouts: a saved army (by its in-game name) + how to deploy it
        "active_plan": "",           # name of the active loadout ("" = classic single point)
        "plans": [
            {"name": "هجوم ذكي", "mode": "smart", "army": "", "army_macro": "", "recording": "", "troops_where": "sides",
             "heroes_where": "sides", "clan_where": "sides", "spells_where": "center", "spells_delay": 5, "abilities_after": 12,
             "second_wave_spells": "", "second_wave_after": 18},
            {"name": "تنانين", "army": "", "army_macro": "", "recording": "", "troops_where": "sides", "heroes_where": "sides", "clan_where": "sides",
             "spells_where": "center", "spells_delay": 3, "abilities_after": 15, "second_wave_spells": "", "second_wave_after": 20},
            {"name": "أرضي", "army": "", "recording": "", "troops_where": "sides", "heroes_where": "sides", "clan_where": "bottom",
             "spells_where": "center", "spells_delay": 5, "abilities_after": 15, "second_wave_spells": "", "second_wave_after": 20},
            {"name": "جهة واحدة", "army": "", "recording": "", "troops_where": "right", "heroes_where": "right", "clan_where": "right",
             "spells_where": "center", "spells_delay": 4, "abilities_after": 12, "second_wave_spells": "", "second_wave_after": 18},
            {"name": "مخصص", "army": "", "recording": "", "troops_where": "sides", "heroes_where": "sides", "clan_where": "sides",
             "spells_where": "center", "spells_delay": 3, "abilities_after": 15, "second_wave_spells": "", "second_wave_after": 20},
        ],
        # Routines: taught buttons tapped in order at the start of every cycle (home village)
        "routines": [
            {"name": "army", "enabled": False, "steps": [
                {"key": "army_button", "multi": False, "wait": 1.0},
                {"key": "hero_add", "multi": True, "wait": 0.5},
                {"key": "train_button", "multi": False, "wait": 0.8},
                {"key": "close_button", "multi": False, "wait": 0.5}]},
            {"name": "collect", "enabled": False, "steps": [
                {"key": "collector_full", "multi": True, "wait": 0.3},
                {"key": "loot_cart", "multi": False, "wait": 1.0},
                {"key": "collect_button", "multi": False, "wait": 0.8},
                {"key": "close_button", "multi": False, "wait": 0.5}]},
            {"name": "custom", "enabled": False, "steps": []},
        ],
        "game": {
            "keep_open": True,       # don't close the game between cycles
            "never_close": True,     # the bot never closes the game / emulator: only the user does
            "apply_instantly": True, # start a cycle right after settings change while idle
            "anti_idle": True,       # nudge the map while waiting so the game doesn't disconnect for inactivity
            "auto_learn": True,      # learn buttons / loot numbers by reading the screen, record unknown screens
        },
        "schedule": {
            "enabled": False,
            "start": "00:00",
            "end": "23:59",
            "days": [0, 1, 2, 3, 4, 5, 6],  # 0 = Monday
            "check_interval": 5,
        },
    }

def default_app_settings():
    return {
        "language": "ar",
        "roboflow_api_key": "",      # the user's own free Roboflow key (Clash Royale training data); stays on this PC
        "ui_game": "",               # the program's face: "coc" | "royale" ("" = ask when it opens)
        "ui_game_remember": False,   # open straight into the last game, without asking
        "emulator": _cfg("EMULATOR_TYPE", "ldplayer"),
        "start_with_windows": False,
        "telegram_bot_token": _cfg("TELEGRAM_BOT_TOKEN", ""),
        "groq_api_key": _cfg("GROQ_API_KEY", ""),
        "clash_api_key": "",         # developer.clashofclans.com key (allowed IP = this PC's public IP)
        "royale_api_key": "",        # developer.clashroyale.com key (allowed IP = this PC's public IP)
        "royale_dev_email": "",      # or the developer.clashroyale.com login: a key is made for the current IP
        "royale_dev_password": "",
        "clash_dev_email": "",       # developer.clashofclans.com login: the bot makes a key for every new IP itself
        "clash_dev_password": "",
        "tesseract_path": _cfg("TESSERACT_PATH", ""),  # empty = find automatically
        "ldplayer_path": _cfg("LDPLAYER_BIN_PATH", ""), # ldconsole.exe; empty = find automatically
        "github_token": "",          # fine-grained token with Issues: read & write on the bot repo
        "auto_report": False,        # upload new errors to GitHub Issues automatically
        "last_report": 0,
        "suspend_emulator_on_idle": _cfg("SUSPEND_EMULATOR_ON_IDLE", False),
        "auto_start_emulator": _cfg("AUTO_START_EMULATOR", True),
        "accounts": list(_cfg("INSTANCE_IDS", ["main"])),
        "emulator_links": {},        # account -> emulator copy (LDPlayer index / BlueStacks instance) chosen on the setup screen
        "show_setup": True,          # show the setup screen when the app opens
        "show_hud": False,           # floating mini HUD orb (Clash Farmer)
        "keep_wall_builder": True,
        "battle_speed": True,        # the last minute of a battle at 4x speed (the green 1x / 2x / 4x button)
        "daily_rewards": True,       # the daily "Free!" gift and free season pass rewards (never anything paid)   # always keep one builder free (for walls)
        "live_stream": True,         # live video of the emulator screen (scrcpy): every look at the screen is instant
        "fast_capture": True,        # read the LDPlayer window directly (much faster than ADB screenshots)
        "desktop_notify": True,      # Windows notifications when upgrades / research finish
        "intro": True,               # 3D animated intro at startup
        "auto_update": False,
        "ask_plan": True,            # ask "what do you want to do today?" once a day when the game is open        # download new versions by itself, then only ask to restart
        "profiles": {},              # account -> {"name": display name} (pictures: ~/.CoC_Bot/avatars)
        "learn_repo": "",            # "owner/name" of the (private) GitHub repo Claude learns from
        "learn_auto": True,
        "upload_unknown": False,
        "send_stuck": True,          # stuck on the same unknown screen -> picture straight to Claude     # send the screens the bot didn't understand by itself (off: only your own pictures)          # send unknown screens / fetch what Claude taught automatically
        "ui": "qt",                  # "qt" = v4 desktop window, "web" = classic window
        "sync_settings": False,      # one set of settings for every account (saving one saves all)
        "display_w": 1920, "display_h": 1080, "display_dpi": 240, # emulator display the bot checks / sets
        "display_reset_1920": False, # one-time move back to 1920x1080 (3.8.0)
        "ocr_model": "auto",         # PaddleOCR PP-OCRv6: auto (medium on a graphics card) / medium (strongest) / small (fastest)
    }

def _merge(base, override):
    """Recursively overlay saved values on top of defaults (new keys keep their default)."""
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict) and out[k]:
            out[k] = _merge(out[k], v)
        elif k in out:
            out[k] = v
    return out

def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

def _safe_id(id):
    return "".join(c for c in str(id) if c.isalnum() or c in "-_") or "main"

OWN_KEYS = ("follow", "clash_tag", "game_mode", "game_mode_set", "royale")   # an account that follows another keeps only these of its own


def load(id):
    data = _merge(default_settings(), _read(SETTINGS_DIR / f"{_safe_id(id)}.json"))
    # 5.32.1: 5.29.2 guessed "Clash Royale" from a portrait screen and could switch a Clash of Clans account.
    # Only a game the user picked counts: anything else is Clash of Clans again.
    if data.get("game_mode") == "royale" and data.get("game_mode_set") != "user":
        data["game_mode"] = "coc"
    # "plays like" another account: everything (loadouts, recording, army, farm…) comes from that account, read
    # fresh every time, so a change there applies here at once. One level only (no chains / loops).
    lead = str(data.get("follow") or "").strip()
    if lead and _safe_id(lead) != _safe_id(id) and (SETTINGS_DIR / f"{_safe_id(lead)}.json").exists():
        led = _merge(default_settings(), _read(SETTINGS_DIR / f"{_safe_id(lead)}.json"))
        led.update({k: data.get(k, led.get(k)) for k in OWN_KEYS})
        data = led
    # 5.17: the smart attack is a loadout of its own (saved plan lists are kept as they are: it is added once)
    plans = data.get("plans") or []
    if not any(p.get("mode") == "smart" for p in plans if isinstance(p, dict)):
        plans.insert(0, copy.deepcopy(default_settings()["plans"][0]))
        data["plans"] = plans
    return data

def save(id, data):
    own = _read(SETTINGS_DIR / f"{_safe_id(id)}.json")
    if (data or {}).get("game_mode") and (data or {}).get("game_mode") != own.get("game_mode", "coc"):
        data = dict(data, game_mode_set="user")           # the user changed the game (Home / setup screen)
    lead = str((data or {}).get("follow", own.get("follow")) or "").strip()
    if lead and _safe_id(lead) != _safe_id(id):
        # this account follows another one: only its own keys are stored (the rest is the leader's, read live)
        own.update({k: (data or {}).get(k, own.get(k, "")) for k in OWN_KEYS})
        _write(SETTINGS_DIR / f"{_safe_id(id)}.json", _merge(default_settings(), own))
        return load(id)
    merged = _merge(default_settings(), data)
    _write(SETTINGS_DIR / f"{_safe_id(id)}.json", merged)
    return merged

def load_app():
    data = _merge(default_app_settings(), _read(GLOBAL_PATH))
    # only LDPlayer is used: another emulator's adb (BlueStacks HD-Adb) fights LDPlayer's for the same server and
    # drops the connection every few minutes (device offline / connection aborted)
    data["emulator"] = "ldplayer"
    if not data.get("display_reset_1920"): # the bot's images and positions are made for 1920x1080
        data.update(display_w=1920, display_h=1080, display_dpi=240, display_reset_1920=True)
        try: _write(GLOBAL_PATH, data)
        except Exception: pass
    # every account listed in configs is always available
    for i in getattr(configs, "INSTANCE_IDS", []):
        if i not in data["accounts"]: data["accounts"].append(i)
    return data

def save_app(data):
    data = dict(data or {})
    data.pop("account_games", None)          # computed for the app, not stored
    merged = _merge(default_app_settings(), data)
    merged["accounts"] = [a for a in dict.fromkeys(_safe_id(a) for a in merged["accounts"]) if a]
    _write(GLOBAL_PATH, merged)
    return merged

def apply_app_settings():
    """Make account list / emulator / keys from the GUI visible to configs-based code."""
    app = load_app()
    configs.INSTANCE_IDS = app["accounts"]
    configs.EMULATOR_TYPE = app["emulator"]
    configs.TELEGRAM_BOT_TOKEN = app["telegram_bot_token"]
    configs.GROQ_API_KEY = app["groq_api_key"]
    configs.SUSPEND_EMULATOR_ON_IDLE = app["suspend_emulator_on_idle"]
    configs.AUTO_START_EMULATOR = app["auto_start_emulator"]
    configs.TESSERACT_PATH = app["tesseract_path"]
    configs.LDPLAYER_BIN_PATH = app.get("ldplayer_path", "")
    configs.EMULATOR_LINKS = app.get("emulator_links", {}) or {}
    configs.DISPLAY_TARGET = (int(app.get("display_w", 1920)), int(app.get("display_h", 1080)), int(app.get("display_dpi", 240)))
    _push_globals({k: getattr(configs, k) for k in (
        "INSTANCE_IDS", "EMULATOR_TYPE", "TELEGRAM_BOT_TOKEN", "GROQ_API_KEY",
        "SUSPEND_EMULATOR_ON_IDLE", "AUTO_START_EMULATOR", "TESSERACT_PATH")})
    return app

def _push_globals(values):
    # modules did `from configs import *`, so their copies must be updated too
    for mod_name in ("utils", "upgrader", "attacker", "coc_bot", "launch", "gui_server.gui_server", "gui_server"):
        mod = sys.modules.get(mod_name)
        if mod is None: continue
        for k, v in values.items():
            if hasattr(mod, k): setattr(mod, k, v)

def apply(s, wall_budget=None):
    """Map account settings onto the configs constants the bot code reads."""
    t, p, u, a = s["tasks"], s["priorities"], s["upgrades"], s["attack"]
    home_priority = [list(lvl) for lvl in p["home_base"] if lvl]
    if (s["walls"]["enabled"] or s["attack"].get("farm", {}).get("max_walls")) and (wall_budget is None or wall_budget > 0):
        home_priority.append(["Wall"]) # walls go last so real buildings come first
    values = {
        "UPGRADE_HOME_BASE": t["home_base"], "UPGRADE_HEROES": t["heroes"],
        "UPGRADE_HOME_LAB": t["home_lab"], "UPGRADE_PETS": t["pet_house"],
        "ASSIGN_BUILDER_APPRENTICE": t["builder_apprentice"], "ASSIGN_LAB_ASSISTANT": t["lab_assistant"],
        "UPGRADE_BUILDER_BASE": t["builder_base"], "UPGRADE_BUILDER_LAB": t["builder_lab"],
        "ATTACK_HOME_BASE": t["home_attacks"], "ATTACK_BUILDER_BASE": t["builder_attacks"],
        "PRIORITY_HOME_BASE_UPGRADES": t["home_base_priority"], "PRIORITY_HOME_LAB_UPGRADES": t["home_lab_priority"],
        "PRIORITY_PET_UPGRADES": t["pet_house_priority"], "PRIORITY_BUILDER_BASE_UPGRADES": t["builder_base_priority"],
        "PRIORITY_BUILDER_LAB_UPGRADES": t["builder_lab_priority"],
        "HOME_BASE_UPGRADE_PRIORITY": home_priority,
        "HOME_LAB_UPGRADE_PRIORITY": [list(l) for l in p["home_lab"] if l],
        "PET_HOUSE_UPGRADE_PRIORITY": [list(l) for l in p["pet_house"] if l],
        "BUILDER_BASE_UPGRADE_PRIORITY": [list(l) for l in p["builder_base"] if l],
        "BUILDER_LAB_UPGRADE_PRIORITY": [list(l) for l in p["builder_lab"] if l],
        "MAX_UPGRADES_PER_CHECK": max(1, int(u["max_per_cycle"])),
        # wall-max mode keeps one builder free for the walls
        "OPEN_HOME_BUILDERS": max(1 if a.get("farm", {}).get("max_walls") else 0, int(u["open_home_builders"])),
        "OPEN_BUILDER_BUILDERS": max(0, int(u["open_builder_builders"])),
        "START_FROM_MENU_TOP": bool(u["start_from_menu_top"]),
        "TROOP_DEPLOY_TIME": float(a["troop_deploy_time"]),
        "ATTACK_SLOT_RANGE": (int(a["slot_first"]), int(a["slot_last"])),
        "EXCLUDE_CLAN_TROOPS": bool(a["exclude_clan_troops"]),
        "CHECK_INTERVAL": max(0, float(s["schedule"]["check_interval"])), # 0 = next cycle right away
        "NEVER_CLOSE_GAME": bool(s["game"].get("never_close", True)),
    }
    for k, v in values.items(): setattr(configs, k, v)
    _push_globals(values)

def in_schedule(s, now=None):
    from datetime import datetime
    sch = s["schedule"]
    if not sch["enabled"]: return True
    now = now or datetime.now()
    def mins(hhmm):
        h, m = (hhmm or "0:0").split(":")
        return int(h) * 60 + int(m)
    cur, start, end = now.hour * 60 + now.minute, mins(sch["start"]), mins(sch["end"])
    day = now.weekday()
    if start <= end:
        return day in sch["days"] and start <= cur <= end
    # window crossing midnight (e.g. 22:00 -> 06:00): the early-morning part belongs to the previous day
    if cur >= start: return day in sch["days"]
    return cur <= end and (day - 1) % 7 in sch["days"]

TASK_NAMES = list(default_settings()["tasks"].keys())

def exclusions(s):
    """Task names that are switched OFF (format used by Task_Handler / web app)."""
    return sorted(k for k, v in s["tasks"].items() if not v)

WAKE_DIR = APP_DATA_DIR / "wake"

def request_wake(id):
    """Ask an idle bot to start its next cycle now."""
    WAKE_DIR.mkdir(parents=True, exist_ok=True)
    (WAKE_DIR / _safe_id(id)).write_text("1")

def consume_wake(id):
    p = WAKE_DIR / _safe_id(id)
    if p.exists():
        try: p.unlink()
        except OSError: pass
        return True
    return False

def mtime(id):
    try: return (SETTINGS_DIR / f"{_safe_id(id)}.json").stat().st_mtime
    except OSError: return 0
