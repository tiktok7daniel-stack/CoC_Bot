"""
The official Clash of Clans API (developer.clashofclans.com): your account exactly as Supercell knows it — Town Hall,
every hero / pet / troop / spell / equipment level and its max, trophies, clan — without reading the screen.

Setup (in the app, never in a chat):
  1. developer.clashofclans.com -> sign in -> My Account -> Create New Key
  2. "Allowed IP addresses": your PC's public IP (the app shows it: "My IP")
  3. paste the key in Settings -> "Clash of Clans API key", and the player tag (#ABC123) in the account's settings

What the bot does with it:
  - the account card in the app (levels, how far from max, what's next)
  - upgrades: a hero that is behind goes first (heroes matter most), the Telegram status shows it too
Answers are cached 30 minutes (the API is also limited per key).
"""
import json, time
from pathlib import Path

API = "https://api.clashofclans.com/v1"
CACHE = Path.home() / ".CoC_Bot" / "clash_api"
HEROES = ("Barbarian King", "Archer Queen", "Grand Warden", "Royal Champion", "Minion Prince")


def _key():
    try:
        import settings
        return (settings.load_app().get("clash_api_key") or "").strip()
    except Exception:
        return ""


def _tag(account):
    try:
        import settings
        t = (settings.load(account).get("clash_tag") or "").strip().upper().replace("O", "0")
    except Exception:
        t = ""
    if not t: return ""
    return t if t.startswith("#") else "#" + t


def public_ip():
    """This PC's address on the internet (what the API key must allow)."""
    import requests
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            r = requests.get(url, timeout=8)
            if r.ok and r.text.strip(): return r.text.strip()
        except Exception:
            pass
    return ""


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _get(path, key):
    import requests
    from urllib.parse import quote
    r = requests.get(API + quote(path, safe="/"), headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                     timeout=15)
    if r.status_code == 200: return r.json()
    try: reason = (r.json() or {}).get("reason", "")
    except ValueError: reason = ""
    if r.status_code == 403 and "invalidIp" in reason: raise ApiError("ip", "the key does not allow this PC's IP")
    if r.status_code == 403: raise ApiError("key", "the key was refused")
    if r.status_code == 404: raise ApiError("tag", "no player with this tag")
    if r.status_code == 429: raise ApiError("limit", "too many requests, try again in a minute")
    raise ApiError("http", f"HTTP {r.status_code} {reason}".strip())


def profile(account="main", max_age=1800, force=False):
    """The player's data from the API (cached) -> dict, or {"error": code, "message": ...}."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{''.join(c for c in account if c.isalnum() or c in '-_') or 'main'}.json"
    if not force:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if time.time() - d.get("_t", 0) < max_age: return d
        except (OSError, ValueError):
            pass
    key, tag = _key(), _tag(account)
    if not key: return {"error": "no_key", "message": "no API key in the settings"}
    if not tag: return {"error": "no_tag", "message": "no player tag in this account's settings"}
    try:
        d = _get(f"/players/{tag}", key)
    except ApiError as e:
        out = {"error": e.code, "message": str(e)}
        if e.code == "ip": out["ip"] = public_ip()
        return out
    except Exception as e:
        return {"error": "net", "message": str(e)[:200]}
    d["_t"] = time.time()
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def summary(p):
    """The parts the app and the bot use."""
    if not p or p.get("error"): return p or {}
    home = lambda items: [x for x in items or [] if x.get("village") == "home"]
    heroes = [{"name": h["name"], "level": h["level"], "max": h["maxLevel"]} for h in home(p.get("heroes"))]
    troops = home(p.get("troops"))
    pets = [t for t in troops if t.get("name") in PETS]
    troops = [t for t in troops if t.get("name") not in PETS and not t.get("name", "").startswith("Super ")]
    def pct(items):
        items = [i for i in items if i.get("maxLevel")]
        return round(100 * sum(i["level"] for i in items) / max(1, sum(i["maxLevel"] for i in items)))
    behind = sorted(heroes, key=lambda h: h["level"] / max(1, h["max"]))
    return {
        "name": p.get("name"), "tag": p.get("tag"), "th": p.get("townHallLevel"), "th_weapon": p.get("townHallWeaponLevel"),
        "exp": p.get("expLevel"), "trophies": p.get("trophies"), "best": p.get("bestTrophies"), "league": (p.get("league") or {}).get("name"),
        "war_stars": p.get("warStars"), "clan": (p.get("clan") or {}).get("name"), "bh": p.get("builderHallLevel"),
        "heroes": heroes, "hero_behind": behind[0]["name"] if behind and behind[0]["level"] < behind[0]["max"] else None,
        "equipment": [{"name": e["name"], "level": e["level"], "max": e["maxLevel"]} for e in home(p.get("heroEquipment"))],
        "pets": [{"name": t["name"], "level": t["level"], "max": t["maxLevel"]} for t in pets],
        "troops_pct": pct(troops), "spells_pct": pct(home(p.get("spells"))), "heroes_pct": pct([dict(level=h["level"], maxLevel=h["max"]) for h in heroes]),
        "updated": p.get("_t"),
    }


PETS = ("L.A.S.S.I", "Electro Owl", "Mighty Yak", "Unicorn", "Frosty", "Diggy", "Poison Lizard", "Phoenix",
        "Spirit Fox", "Angry Jelly", "Sneezy")


def hero_priority(account="main"):
    """Heroes in the order they should be upgraded (furthest from max first) — [] without the API."""
    s = summary(profile(account))
    if not s or s.get("error"): return []
    return [h["name"] for h in sorted(s.get("heroes", []), key=lambda h: h["level"] / max(1, h["max"])) if h["level"] < h["max"]]
