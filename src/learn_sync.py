"""
Claude learning inbox (GitHub):

  bot  ->  repo/inbox/...      screens the bot did not understand (picture + the words it read + what it did)
  bot  ->  repo/armies/...     pictures of the armies it learned
  Claude (a Claude Code session on the repo) reads them, writes what to do on each screen into
           repo/knowledge/screens.json and marks every picture in repo/knowledge/status.json (done = ✓)
  bot  <-  knowledge/*.json    fetched every few minutes; Auto_Learn.handle_unknown_screen uses the rules

The repo and a GitHub token are set in the app settings (learn_repo "owner/name", github_token); the token
stays on this computer. A private repo is strongly recommended: game screenshots show the player name.
The protocol Claude follows is in docs/LEARNING.md.
"""
import base64, json, time
from pathlib import Path

BASE = Path.home() / ".CoC_Bot" / "learn"
STATE = BASE / "state.json"
KNOW = BASE / "knowledge.json"
STATUS = BASE / "status.json"
QUEUE = BASE / "queue.jsonl"
UPLOAD_EVERY = 600         # seconds between automatic uploads / fetches
MAX_PER_ROUND = 6


# ====================================================================== local state
def _load(p, default):
    try: return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError): return default


def _save(p, data):
    BASE.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _cfg():
    try:
        import settings
        a = settings.load_app()
    except Exception:
        a = {}
    return {"repo": (a.get("learn_repo") or "").strip().strip("/"), "token": (a.get("github_token") or "").strip(),
            "auto": a.get("learn_auto", True) is not False}


def configured():
    c = _cfg()
    return bool(c["repo"] and "/" in c["repo"] and c["token"])


def queue_army(id, name):
    BASE.mkdir(parents=True, exist_ok=True)
    with open(QUEUE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "army", "id": id, "name": name, "t": time.time()}, ensure_ascii=False) + "\n")


# ====================================================================== GitHub contents API
def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ClashFarmer"}


def _put(path, data, message):
    import requests
    c = _cfg()
    url = f"https://api.github.com/repos/{c['repo']}/contents/{path}"
    sha = None
    r = requests.get(url, headers=_headers(c["token"]), timeout=20)
    if r.status_code == 200: sha = r.json().get("sha")
    body = {"message": message, "content": base64.b64encode(data).decode("ascii")}
    if sha: body["sha"] = sha
    r = requests.put(url, headers=_headers(c["token"]), json=body, timeout=60)
    if r.status_code not in (200, 201): raise RuntimeError(f"GitHub {r.status_code}: {r.text[:160]}")


def _get_json(path):
    import requests
    c = _cfg()
    r = requests.get(f"https://api.github.com/repos/{c['repo']}/contents/{path}",
                     headers=dict(_headers(c["token"]), Accept="application/vnd.github.raw"), timeout=20)
    if r.status_code == 404: return None
    if r.status_code != 200: raise RuntimeError(f"GitHub {r.status_code}: {r.text[:160]}")
    return json.loads(r.text)


def test():
    """-> {"ok", "private", "error"} for the settings screen."""
    import requests
    c = _cfg()
    if not configured(): return {"ok": False, "error": "not_configured"}
    try:
        r = requests.get(f"https://api.github.com/repos/{c['repo']}", headers=_headers(c["token"]), timeout=15)
        if r.status_code == 404: return {"ok": False, "error": "repo_not_found"}
        if r.status_code == 401: return {"ok": False, "error": "bad_token"}
        if r.status_code != 200: return {"ok": False, "error": f"http_{r.status_code}"}
        d = r.json()
        can_push = (d.get("permissions") or {}).get("push", False)
        return {"ok": bool(can_push), "private": bool(d.get("private")), "error": "" if can_push else "no_write"}
    except Exception as e:
        return {"ok": False, "error": "offline", "detail": str(e)[:120]}


# ====================================================================== upload + fetch
def upload_pending(id, limit=MAX_PER_ROUND):
    """Send the unknown screens (and learned armies) that are not on GitHub yet. -> number uploaded."""
    import teach, version
    st = _load(STATE, {})
    done = st.setdefault("uploaded", {})
    n = 0
    folder = teach.DISCOVERED_DIR / teach._safe(id)
    for d in reversed(teach.discoveries(id, 40)):            # oldest first
        if n >= limit: break
        key = f"{id}/{d['shot']}"
        if key in done or not (folder / d["shot"]).exists(): continue
        stem = f"inbox/{time.strftime('%Y%m%d', time.localtime(d.get('t', time.time())))}/{teach._safe(id)}_{d['shot'][:-4]}"
        meta = dict(d, account=id, bot_version=version.VERSION, kind="screen")
        _put(stem + ".jpg", (folder / d["shot"]).read_bytes(), f"inbox: unknown screen {d['shot']}")
        _put(stem + ".json", json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"), f"inbox: words of {d['shot']}")
        done[key] = {"t": time.time(), "path": stem, "words": d.get("words", [])[:10], "phase": d.get("phase", ""),
                     "action": d.get("action", ""), "account": id}
        n += 1
    # learned armies
    if QUEUE.exists():
        import army_learn
        rest = []
        for line in QUEUE.read_text(encoding="utf-8").splitlines():
            try: q = json.loads(line)
            except ValueError: continue
            if n >= limit: rest.append(line); continue
            pic = army_learn.picture_path(q["name"])
            data = army_learn.load(q["name"])
            if not pic or not data: continue
            stem = f"armies/{army_learn._safe(q['name'])}"
            _put(stem + ".jpg", pic.read_bytes(), f"army: {q['name']}")
            _put(stem + ".json", json.dumps(dict(data, account=q.get("id")), ensure_ascii=False, indent=1).encode("utf-8"), f"army steps: {q['name']}")
            done[f"army/{q['name']}"] = {"t": time.time(), "path": stem, "army": q["name"]}
            n += 1
        QUEUE.write_text("\n".join(rest) + ("\n" if rest else ""), encoding="utf-8")
    st["last_upload"] = time.time()
    _save(STATE, st)
    if n: write_index()
    return n


def _seals():
    """The check seals (same design as in the app) uploaded once to the repo for the README."""
    st = _load(STATE, {})
    if st.get("seals_v") == 1: return
    try:
        from qt_ui.icons import GLYPHS
        for name in ("verified", "verified_gold"):
            _put(f"assets/{name}.svg", GLYPHS[name].encode("utf-8"), f"assets: {name} seal")
        st = _load(STATE, {})
        st["seals_v"] = 1
        _save(STATE, st)
    except Exception:
        pass


def write_index():
    """README.md of the learning repo: every picture the bot didn't know, its words and its state (waiting / learned)."""
    _seals()
    OK = '<img src="assets/verified_gold.svg" width="18" align="center">'
    st = _load(STATE, {})
    status = _load(STATUS, {}).get("items", {})
    rows = [v for v in st.get("uploaded", {}).values() if isinstance(v, dict) and v.get("path")]
    rows.sort(key=lambda v: v.get("t", 0), reverse=True)
    screens = [v for v in rows if not v.get("army")]
    armies = [v for v in rows if v.get("army")]
    learned = sum(1 for v in screens if (status.get(v["path"].split("/")[-1]) or {}).get("done"))
    out = ["# Clash Farmer — شاشات البوت ماكانش يعرفها", "",
           f"**{len(screens)}** شاشة اتبعتت — {OK} **{learned}** اتعلّمت — ⏳ **{len(screens) - learned}** مستنية Claude", "",
           "> Claude: اتبع `docs/LEARNING.md` في ريبو البوت. اكتب القواعد في `knowledge/screens.json` والحالة في `knowledge/status.json`.", "",
           "| الصورة | الحالة | اللي البوت قراه | كان بيعمل إيه |", "|---|---|---|---|"]
    for v in screens:
        name = v["path"].split("/")[-1]
        s_ = status.get(name) or {}
        state = (OK + " " + (s_.get("note_ar") or s_.get("note") or "اتعلّمت")) if s_.get("done") else "⏳ مستنية Claude"
        words = " · ".join(str(w).replace("|", "/") for w in v.get("words", [])[:8]) or "—"
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(v.get("t", 0)))
        out.append(f"| <img src=\"{v['path']}.jpg\" width=\"240\"><br>{when} | {state} | {words} | {v.get('phase') or '—'} {v.get('action') or ''} |")
    if armies:
        out += ["", "## الجيوش اللي البوت اتعلّمها منك", "", "| الجيش | الصورة |", "|---|---|"]
        for v in armies: out.append(f"| {v['army']} | <img src=\"{v['path']}.jpg\" width=\"240\"> |")
    _put("README.md", "\n".join(out).encode("utf-8"), f"index: {len(screens)} screens, {learned} learned")



def fetch_knowledge():
    """knowledge/screens.json + knowledge/status.json from the repo -> local copies. -> number of rules."""
    k = _get_json("knowledge/screens.json")
    if isinstance(k, dict): _save(KNOW, k)
    s = _get_json("knowledge/status.json")
    if isinstance(s, dict): _save(STATUS, s)
    st = _load(STATE, {})
    st["last_fetch"] = time.time()
    _save(STATE, st)
    return len((k or {}).get("screens", []))


def sync_now(id):
    st = _load(STATE, {})
    try:
        up = upload_pending(id, limit=20)
        before = json.dumps(_load(STATUS, {}), sort_keys=True)
        rules = fetch_knowledge()
        if not up and json.dumps(_load(STATUS, {}), sort_keys=True) != before: write_index()
        st = _load(STATE, {})
        st["error"] = ""
        _save(STATE, st)
        return {"ok": True, "uploaded": up, "rules": rules}
    except Exception as e:
        st = _load(STATE, {})
        st["error"] = str(e)[:200]
        _save(STATE, st)
        return {"ok": False, "error": str(e)[:200]}


def tick(id):
    """Called from the bot's idle loop: at most every UPLOAD_EVERY seconds."""
    if not configured() or not _cfg()["auto"]: return
    st = _load(STATE, {})
    if time.time() - st.get("last_upload", 0) < UPLOAD_EVERY: return
    st["last_upload"] = time.time()          # also on failure: don't hammer GitHub
    _save(STATE, st)
    res = sync_now(id)
    try:
        from utils import logger
        if res.get("ok"):
            if res["uploaded"]: logger.info(f"Learning: sent {res['uploaded']} screens to Claude, {res['rules']} rules known")
        else:
            logger.warning(f"Learning sync failed: {res.get('error')}")
    except Exception: pass


# ====================================================================== what the GUI shows
def overview(id):
    import teach
    st = _load(STATE, {})
    status = _load(STATUS, {}).get("items", {})
    up = st.get("uploaded", {})
    items = []
    for d in teach.discoveries(id, 40):
        key = f"{id}/{d['shot']}"
        name = f"{teach._safe(id)}_{d['shot'][:-4]}"
        s = status.get(name) or {}
        items.append({"shot": d["shot"], "t": d.get("t"), "words": d.get("words", [])[:12], "phase": d.get("phase"),
                      "state": "learned" if s.get("done") else ("sent" if key in up else "local"),
                      "note": s.get("note_ar") or s.get("note") or ""})
    know = _load(KNOW, {})
    c = _cfg()
    return {"configured": configured(), "repo": c["repo"], "auto": c["auto"], "last_upload": st.get("last_upload"),
            "last_fetch": st.get("last_fetch"), "error": st.get("error", ""), "rules": len(know.get("screens", [])),
            "rule_list": [{"id": r.get("id"), "title": r.get("title_ar") or r.get("title") or r.get("id")} for r in know.get("screens", [])][:50],
            "items": items}


# ====================================================================== using the knowledge (bot process)
def match_screen(words, phase=""):
    """The taught rule for a screen showing these OCR words, or None."""
    text = " ".join(w.lower() for w in words)
    best, best_score = None, 0
    for r in _load(KNOW, {}).get("screens", []):
        need = [w.lower() for w in r.get("match_all", [])]
        anyw = [w.lower() for w in r.get("match_any", [])]
        if not need and not anyw: continue
        if any(w not in text for w in need): continue
        if anyw and not any(w in text for w in anyw): continue
        if r.get("phase") and phase and r["phase"] != phase: continue
        score = len(need) * 2 + (1 if anyw else 0)
        if score > best_score: best, best_score = r, score
    return best


def run_actions(rule, boxes):
    """Do what Claude wrote for the screen. -> True when something was done."""
    import time as _t
    from utils import Input_Handler, _word_hit
    did = False
    for a in rule.get("actions", [])[:8]:
        kind = a.get("type")
        if kind == "tap_word":
            w = str(a.get("word", "")).lower()
            hit = next((b for b in boxes if b[5] > 0.3 and _word_hit(b[0], w)), None)
            if hit:
                Input_Handler.click((hit[1] + hit[3]) / 2, (hit[2] + hit[4]) / 2)
                did = True
            elif "x" in a and "y" in a:
                Input_Handler.click(float(a["x"]), float(a["y"]))
                did = True
        elif kind == "tap":
            Input_Handler.click(float(a["x"]), float(a["y"]))
            did = True
        elif kind == "close":
            Input_Handler.click_exit(n=1)
            did = True
        elif kind == "wait":
            _t.sleep(min(10.0, float(a.get("s", 1))))
    return did
