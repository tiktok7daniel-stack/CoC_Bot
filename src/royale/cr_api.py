"""
The official Clash Royale API (developer.clashroyale.com): the game's own numbers, exactly, without touching the game.

  your account      every card you own with its level, your current deck (the bot knows its 8 cards before the
                    first battle starts: no guessing in the first seconds)
  every battle      the opponent's WHOLE deck (8 cards + levels), the crowns, who won — the bot learns from the
                    real result and the real deck, not from what it managed to see
  the meta          the battles of the best players in the world, every day: which decks are played right now
                    and how often each wins, which cards go together (the opponent's deck is guessed from them)
  all cards         the full card list of the current game version (new cards included)

Setup (in the app, never in a chat): developer.clashroyale.com -> My Account -> Create New Key with this PC's IP,
paste it in the Clash Royale screen with your player tag. Or the developer-site e-mail / password: the bot then
makes a key for the IP it has right now by itself (like the Clash of Clans one).
Answers are cached; the API is limited per key.
"""
import base64, json, time
from pathlib import Path

API = "https://api.clashroyale.com/v1"
DEV = "https://developer.clashroyale.com/api"
CACHE = Path.home() / ".CoC_Bot" / "royale_api"
KEYS = CACHE / "keys.json"
META = CACHE / "meta.json"
KEY_NAME = "ClashFarmer"


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def key_of(name):
    """API card name -> the bot's card key ("Mini P.E.K.K.A" -> "minipekka", "X-Bow" -> "xbow")."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _app():
    try:
        import settings
        return settings.load_app() or {}
    except Exception:
        return {}


def tag(account):
    try:
        import settings
        t = ((settings.load(account).get("royale") or {}).get("tag") or "").strip().upper().replace("O", "0")
    except Exception:
        t = ""
    if not t: return ""
    return t if t.startswith("#") else "#" + t


def _saved_keys():
    try: return json.loads(KEYS.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def auto_key():
    """Log in to developer.clashroyale.com, make / reuse a key for the IP Supercell sees now -> (key, ip)."""
    import requests
    a = _app()
    email, password = (a.get("royale_dev_email") or "").strip(), a.get("royale_dev_password") or ""
    if not email or not password: raise ApiError("no_login", "no developer-site login in the settings")
    s = requests.Session()
    r = s.post(f"{DEV}/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code in (401, 403): raise ApiError("login", "the developer-site e-mail / password were refused")
    if r.status_code != 200: raise ApiError("http", f"developer site: HTTP {r.status_code}")
    tok = (r.json() or {}).get("temporaryAPIToken", "")
    ip = ""
    try:
        part = tok.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        for lim in data.get("limits", []):
            if lim.get("cidrs"): ip = lim["cidrs"][0].split("/")[0]
    except Exception:
        pass
    if not ip:
        try:
            import clash_api
            ip = clash_api.public_ip()
        except Exception:
            ip = ""
    keys = (s.post(f"{DEV}/apikey/list", json={}, timeout=20).json() or {}).get("keys", [])
    have = next((k for k in keys if k.get("name") == KEY_NAME and ip in (k.get("cidrRanges") or [])), None)
    if have is None:
        if len(keys) >= 10:
            ours = [k for k in keys if k.get("name") == KEY_NAME]
            if not ours: raise ApiError("keys_full", "10 keys already exist on the developer site (none made by the bot)")
            s.post(f"{DEV}/apikey/revoke", json={"id": ours[0]["id"]}, timeout=20)
        r = s.post(f"{DEV}/apikey/create", json={"name": KEY_NAME, "description": "made by Clash Farmer for " + ip,
                                                  "cidrRanges": [ip], "scopes": ["royale"]}, timeout=20)
        have = (r.json() or {}).get("key") or {}
        if not have.get("key"): raise ApiError("http", f"developer site: could not make a key (HTTP {r.status_code})")
    saved = _saved_keys()
    saved[ip] = have["key"]
    CACHE.mkdir(parents=True, exist_ok=True)
    KEYS.write_text(json.dumps(dict(list(saved.items())[-10:])), encoding="utf-8")
    return have["key"], ip


def _get(path, key):
    import requests
    from urllib.parse import quote
    r = requests.get(API + quote(path, safe="/?=&"), headers={"Authorization": f"Bearer {key}",
                                                              "Accept": "application/json"}, timeout=10)
    if r.status_code == 200: return r.json()
    try: body = r.json() or {}
    except ValueError: body = {}
    reason = body.get("reason", "")
    if r.status_code == 403 and "invalidIp" in reason: raise ApiError("ip", "the key does not allow this PC's IP")
    if r.status_code == 403: raise ApiError("key", "the key was refused")
    if r.status_code == 404: raise ApiError("tag", "not found")
    if r.status_code == 429: raise ApiError("limit", "too many requests")
    raise ApiError("http", f"HTTP {r.status_code} {reason}".strip())


def fetch(path, max_age=0):
    """GET with the key from the settings (or one made for this IP), cached for max_age seconds."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / ("c_" + "".join(ch if ch.isalnum() else "_" for ch in path)[:120] + ".json")
    if max_age:
        try:
            if time.time() - cf.stat().st_mtime < max_age: return json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    key = (_app().get("royale_api_key") or "").strip()
    try:
        if not key: raise ApiError("no_key", "no key")
        data = _get(path, key)
    except ApiError as e:
        if e.code not in ("ip", "no_key", "key"): raise
        k2 = None
        for k in _saved_keys().values():
            try:
                data = _get(path, k); k2 = k
                break
            except ApiError:
                continue
        if k2 is None:
            k2, _ip = auto_key()                       # raises when there is no developer-site login
            data = _get(path, k2)
    try: cf.write_text(json.dumps(data), encoding="utf-8")
    except OSError: pass
    return data


# ------------------------------------------------------------------ what the bot uses
def player(account):
    t = tag(account)
    if not t: raise ApiError("no_tag", "no player tag")
    return fetch(f"/players/{t}", max_age=600)


def my_deck(account):
    """[(card key, level, max level, evolution)] of the current deck, from the API."""
    p = player(account)
    return [(key_of(c.get("name")), c.get("level"), c.get("maxLevel"), c.get("evolutionLevel") or 0)
            for c in p.get("currentDeck") or []]


def last_battle(account, after=0.0):
    """The newest battle of the player (newer than `after`, a unix time) ->
    {"won", "crowns", "their_crowns", "their_deck": [(key, level)], "my_deck": [...], "time", "type"} or None."""
    t = tag(account)
    if not t: return None
    log = fetch(f"/players/{t}/battlelog")
    if not log: return None
    b = log[0]
    bt = b.get("battleTime", "")                       # 20261120T101500.000Z
    try:
        import calendar
        ts = calendar.timegm(time.strptime(bt[:15], "%Y%m%dT%H%M%S"))          # the API's times are UTC
    except ValueError:
        ts = 0.0
    if ts and ts < after - 60: return None
    me, them = (b.get("team") or [{}])[0], (b.get("opponent") or [{}])[0]
    cr, tcr = me.get("crowns", 0), them.get("crowns", 0)
    return {"won": cr > tcr, "crowns": cr, "their_crowns": tcr, "time": ts, "type": b.get("type"),
            "their_deck": [(key_of(c.get("name")), c.get("level")) for c in them.get("cards") or []],
            "my_deck": [(key_of(c.get("name")), c.get("level")) for c in me.get("cards") or []],
            "their_name": them.get("name"), "their_trophies": them.get("startingTrophies")}


def build_meta(players=60, max_age=20 * 3600):
    """The best players' newest battles -> which decks are played now and how often they win, and which cards are
    played together (for guessing a deck from 1-2 cards) -> ~/.CoC_Bot/royale_api/meta.json (once a day)."""
    try:
        if time.time() - META.stat().st_mtime < max_age: return json.loads(META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    tops = []
    for path in ("/locations/global/pathoflegend/players?limit=200", "/locations/57000006/pathoflegend/players?limit=200",
                 "/locations/global/rankings/players?limit=200"):
        try:
            tops = (fetch(path, max_age=86400) or {}).get("items") or []
            if tops: break
        except ApiError:
            continue
    decks, pairs, n_cards, seen = {}, {}, {}, set()
    for p in tops[:players]:
        try:
            log = fetch(f"/players/{p['tag']}/battlelog", max_age=6 * 3600)
        except ApiError:
            continue
        for b in log or []:
            for side, other in (("team", "opponent"), ("opponent", "team")):
                me, them = (b.get(side) or [{}])[0], (b.get(other) or [{}])[0]
                cards = sorted(key_of(c.get("name")) for c in me.get("cards") or [])
                if len(cards) != 8: continue
                bid = (b.get("battleTime"), tuple(cards))
                if bid in seen: continue
                seen.add(bid)
                d = decks.setdefault("|".join(cards), {"n": 0, "w": 0})
                d["n"] += 1
                d["w"] += int(me.get("crowns", 0) > them.get("crowns", 0))
                for c in cards:
                    n_cards[c] = n_cards.get(c, 0) + 1
                    for o in cards:
                        if o != c: pairs.setdefault(c, {}).setdefault(o, 0); pairs[c][o] += 1
    meta = {"made": time.time(), "battles": len(seen),
            "decks": sorted(({"cards": k.split("|"), **v} for k, v in decks.items() if v["n"] >= 2),
                            key=lambda d: -d["n"])[:300],
            "with": {c: sorted(((o, round(k / n_cards[c], 3)) for o, k in os_.items()), key=lambda x: -x[1])[:20]
                     for c, os_ in pairs.items()}}
    if seen:
        CACHE.mkdir(parents=True, exist_ok=True)
        META.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def meta():
    try: return json.loads(META.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def predict_deck(seen_keys):
    """The current meta's guess of their whole deck from the cards seen: the most played real deck that has
    every seen card, else the cards most often played with them. -> [(key, probability)]."""
    m = meta()
    seen = [s for s in seen_keys if s]
    if not m or not seen: return []
    best = [d for d in m.get("decks", []) if all(s in d["cards"] for s in seen)]
    if best:
        tot = sum(d["n"] for d in best)
        score = {}
        for d in best:
            for c in d["cards"]:
                score[c] = score.get(c, 0) + d["n"] / tot
        return sorted(score.items(), key=lambda x: -x[1])[:8]
    w = m.get("with", {})
    score = {}
    for s in seen:
        for o, p in w.get(s, []):
            score[o] = score.get(o, 0) + p / len(seen)
    return [(s, 1.0) for s in seen] + sorted(((o, p) for o, p in score.items() if o not in seen),
                                             key=lambda x: -x[1])[:8 - len(seen)]
