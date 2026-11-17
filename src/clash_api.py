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
    import re, requests
    from urllib.parse import quote
    r = requests.get(API + quote(path, safe="/"), headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                     timeout=8)
    if r.status_code == 200: return r.json()
    try: body = r.json() or {}
    except ValueError: body = {}
    reason, msg = body.get("reason", ""), body.get("message", "")
    if r.status_code == 403 and "invalidIp" in reason:
        m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", msg)        # Supercell says which IP it saw
        e = ApiError("ip", "the key does not allow this PC's IP")
        e.ip = m.group(1) if m else ""
        raise e
    if r.status_code == 403: raise ApiError("key", "the key was refused")
    if r.status_code == 404: raise ApiError("tag", "no player with this tag")
    if r.status_code == 429: raise ApiError("limit", "too many requests, try again in a minute")
    raise ApiError("http", f"HTTP {r.status_code} {reason}".strip())


# ---------------------------------------------------------------- keys made automatically (the IP keeps changing)
# Many connections (mobile data, VPNs, company proxies) change their public IP often; a key only works from the IPs
# written in it. With the developer-site login in the settings, the bot does what the well-known API libraries do:
# it logs in to developer.clashofclans.com, reads the IP Supercell sees right now, and makes a key for it (or reuses
# the one it made before for that IP). At most 10 keys exist per account: the oldest "ClashFarmer" key is removed.
DEV = "https://developer.clashofclans.com/api"
KEYS = CACHE / "keys.json"
KEY_NAME = "ClashFarmer"


def _dev_login():
    try:
        import settings
        a = settings.load_app()
        return (a.get("clash_dev_email") or "").strip(), a.get("clash_dev_password") or ""
    except Exception:
        return "", ""


def _saved_keys():
    try: return json.loads(KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def auto_key():
    """Log in to the developer site, make / reuse a key for the IP Supercell sees now -> (key, ip). Raises ApiError."""
    import base64, requests
    email, password = _dev_login()
    if not email or not password: raise ApiError("no_login", "no developer-site login in the settings")
    s = requests.Session()
    r = s.post(f"{DEV}/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code in (401, 403): raise ApiError("login", "the developer-site email / password were refused")
    if r.status_code != 200: raise ApiError("http", f"developer site: HTTP {r.status_code}")
    tok = (r.json() or {}).get("temporaryAPIToken", "")
    ip = ""
    try:                                                   # the IP Supercell sees, written in the temporary token
        part = tok.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        for lim in data.get("limits", []):
            if lim.get("cidrs"): ip = lim["cidrs"][0].split("/")[0]
    except Exception:
        pass
    if not ip: ip = public_ip()
    keys = (s.post(f"{DEV}/apikey/list", json={}, timeout=20).json() or {}).get("keys", [])
    have = next((k for k in keys if k.get("name") == KEY_NAME and ip in (k.get("cidrRanges") or [])), None)
    if have is None:
        if len(keys) >= 10:                                # the account's limit: drop our oldest key
            ours = [k for k in keys if k.get("name") == KEY_NAME]
            if not ours: raise ApiError("keys_full", "10 keys already exist on the developer site (none made by the bot)")
            s.post(f"{DEV}/apikey/revoke", json={"id": ours[0]["id"]}, timeout=20)
        r = s.post(f"{DEV}/apikey/create", json={"name": KEY_NAME, "description": "made by Clash Farmer for " + ip,
                                                  "cidrRanges": [ip], "scopes": ["clash"]}, timeout=20)
        have = (r.json() or {}).get("key") or {}
        if not have.get("key"): raise ApiError("http", f"developer site: could not make a key (HTTP {r.status_code})")
    saved = _saved_keys()
    saved[ip] = have["key"]
    CACHE.mkdir(parents=True, exist_ok=True)
    KEYS.write_text(json.dumps(dict(list(saved.items())[-10:])), encoding="utf-8")
    return have["key"], ip


def _fetch(path):
    """GET with the right key: the one typed in, the ones made for each IP seen, a new one when the IP is new."""
    tried, last = set(), None
    cands = [k for k in [_key()] + list(reversed(list(_saved_keys().values()))) if k]
    for k in cands:
        if k in tried: continue
        tried.add(k)
        try:
            return _get(path, k)
        except ApiError as e:
            if e.code not in ("ip", "key"): raise
            last = e
            want = getattr(e, "ip", "")                  # a key made for exactly this IP: that one next
            sk = _saved_keys().get(want)
            if sk and sk not in tried:
                tried.add(sk)
                try: return _get(path, sk)
                except ApiError as e2:
                    if e2.code not in ("ip", "key"): raise
    email, password = _dev_login()
    if email and password:                              # a new IP: make its key now
        k, _ip = auto_key()
        return _get(path, k)
    if last: raise last
    raise ApiError("no_key", "no API key in the settings")


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
    tag = _tag(account)
    if not tag: return {"error": "no_tag", "message": "no player tag in this account's settings"}
    try:
        d = _fetch(f"/players/{tag}")
    except ApiError as e:
        out = {"error": e.code, "message": str(e)}
        if e.code == "ip": out["ip"] = getattr(e, "ip", "") or public_ip()
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
