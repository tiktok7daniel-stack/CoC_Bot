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
            },
            "skip_when_full": {      # don't attack while the storages are (nearly) full
                "enabled": False, "gold": 0, "elixir": 0,
            },
            "battle_end": "wait",    # "wait" (game stays open) | "restart" (reopen game) | "leave" (end right after deploying)
            "leave_after": 0,        # "leave": seconds to wait after the army is down before ending
            "surrender_after": 0,    # seconds after deployment to end the battle early (0 = wait for the end)
            "smart_end": True,       # end the battle when the enemy loot stops going down
            "smart_end_after": 15,   # ... for this many seconds
        },
        "limits": {
            "max_attacks": 0,        # stop after this many attacks in the session (0 = no limit)
            "max_hours": 0,          # stop after running this many hours (0 = no limit)
        },
        "breaks": {
            "enabled": True,         # humanized breaks: close the game for a while now and then
            "every_minutes": 120,
            "length_minutes": 10,
        },
        # Loadouts: a saved army (by its in-game name) + how to deploy it
        "active_plan": "",           # name of the active loadout ("" = classic single point)
        "plans": [
            {"name": "تنانين", "army": "", "recording": "", "troops_where": "sides", "heroes_where": "sides", "clan_where": "sides",
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
        "emulator": _cfg("EMULATOR_TYPE", "bluestacks"),
        "start_with_windows": False,
        "telegram_bot_token": _cfg("TELEGRAM_BOT_TOKEN", ""),
        "groq_api_key": _cfg("GROQ_API_KEY", ""),
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
        "display_w": 1920, "display_h": 1080, "display_dpi": 240, # emulator display the bot checks / sets
        "display_reset_1920": False, # one-time move back to 1920x1080 (3.8.0)
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

def load(id):
    return _merge(default_settings(), _read(SETTINGS_DIR / f"{_safe_id(id)}.json"))

def save(id, data):
    merged = _merge(default_settings(), data)
    _write(SETTINGS_DIR / f"{_safe_id(id)}.json", merged)
    return merged

def load_app():
    data = _merge(default_app_settings(), _read(GLOBAL_PATH))
    if not data.get("display_reset_1920"): # the bot's images and positions are made for 1920x1080
        data.update(display_w=1920, display_h=1080, display_dpi=240, display_reset_1920=True)
        try: _write(GLOBAL_PATH, data)
        except Exception: pass
    # every account listed in configs is always available
    for i in getattr(configs, "INSTANCE_IDS", []):
        if i not in data["accounts"]: data["accounts"].append(i)
    return data

def save_app(data):
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
    if s["walls"]["enabled"] and (wall_budget is None or wall_budget > 0):
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
        "OPEN_HOME_BUILDERS": max(0, int(u["open_home_builders"])),
        "OPEN_BUILDER_BUILDERS": max(0, int(u["open_builder_builders"])),
        "START_FROM_MENU_TOP": bool(u["start_from_menu_top"]),
        "TROOP_DEPLOY_TIME": float(a["troop_deploy_time"]),
        "ATTACK_SLOT_RANGE": (int(a["slot_first"]), int(a["slot_last"])),
        "EXCLUDE_CLAN_TROOPS": bool(a["exclude_clan_troops"]),
        "CHECK_INTERVAL": max(0, float(s["schedule"]["check_interval"])), # 0 = next cycle right away
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
