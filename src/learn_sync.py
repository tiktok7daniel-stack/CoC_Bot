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


def normalize_repo(text):
    """'https://github.com/owner/name(.git)' / 'github.com/owner/name/' / 'owner/name' -> 'owner/name'."""
    import re
    t = (text or "").strip()
    t = re.sub(r"^(https?://)?(www\.)?github\.com/", "", t, flags=re.I)
    t = t.strip().strip("/")
    if t.endswith(".git"): t = t[:-4]
    parts = [x for x in t.split("/") if x]
    return "/".join(parts[:2]) if len(parts) >= 2 else t


def _cfg():
    try:
        import settings
        a = settings.load_app()
    except Exception:
        a = {}
    token = (a.get("github_token") or "").strip()
    return {"repo": _canonical(normalize_repo(a.get("learn_repo") or ""), token), "token": token,
            "auto": a.get("learn_auto", True) is not False}


_CANON = {}


def _canonical(repo, token):
    """
    The repo's current name (it may have been renamed: GitHub forwards reads to the new name, but uploads to the old
    name can fail with 404). Asked once per run; a new name is also saved in the app settings.
    """
    if not repo or "/" not in repo or not token: return repo
    if repo in _CANON: return _CANON[repo]
    _CANON[repo] = repo
    try:
        import requests
        r = requests.get(f"https://api.github.com/repos/{repo}", headers=_headers(token), timeout=15, allow_redirects=True)
        if r.status_code == 200:
            name = r.json().get("full_name") or repo
            _CANON[repo] = name
            if name.lower() != repo.lower() or name != repo:
                try:
                    import settings
                    app = settings.load_app()
                    app["learn_repo"] = name
                    settings.save_app(app)
                except Exception:
                    pass
                _CANON[name] = name
    except Exception:
        _CANON.pop(repo, None)                 # offline: ask again next time
    return _CANON.get(repo, repo)


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
        # real write test: a tiny blob (nothing is committed, no branch changes). Needs Contents: Read and write.
        w = requests.post(f"https://api.github.com/repos/{c['repo']}/git/blobs", headers=_headers(c["token"]),
                          json={"content": "clash farmer write test", "encoding": "utf-8"}, timeout=15)
        if w.status_code in (200, 201):
            return {"ok": True, "private": bool(d.get("private")), "error": ""}
        if w.status_code == 409:            # empty repo: reading worked, writing is allowed once a first commit exists
            return {"ok": True, "private": bool(d.get("private")), "error": ""}
        return {"ok": False, "private": bool(d.get("private")), "error": "no_write", "detail": f"http_{w.status_code}"}
    except Exception as e:
        return {"ok": False, "error": "offline", "detail": str(e)[:120]}


# ====================================================================== upload + fetch
def upload_pending(id, limit=MAX_PER_ROUND):
    """Send the unknown screens (and learned armies) that are not on GitHub yet. -> number uploaded."""
    import teach, version
    st = _load(STATE, {})
    done = st.setdefault("uploaded", {})
    n = 0
    try:
        import settings
        auto_screens = settings.load_app().get("upload_unknown", False)
    except Exception:
        auto_screens = False
    if not auto_screens: limit_screens = 0
    else: limit_screens = limit
    folder = teach.DISCOVERED_DIR / teach._safe(id)
    for d in reversed(teach.discoveries(id, 40)):            # oldest first (only when "send unknown screens" is on)
        if n >= limit_screens: break
        key = f"{id}/{d['shot']}"
        if key in done or not (folder / d["shot"]).exists(): continue
        try:                                                   # a screen like one already sent: skip it
            import cv2, screen_memory
            pic = cv2.cvtColor(cv2.imread(str(folder / d["shot"])), cv2.COLOR_BGR2RGB)
            if screen_memory.seen_before(id, "uploaded", pic):
                done[key] = {"t": time.time(), "skipped": "same as one already sent"}
                continue
        except Exception:
            pass
        stem = f"inbox/{time.strftime('%Y%m%d', time.localtime(d.get('t', time.time())))}/{teach._safe(id)}_{d['shot'][:-4]}"
        meta = dict(d, account=id, bot_version=version.VERSION, kind="screen")
        _put(stem + ".jpg", (folder / d["shot"]).read_bytes(), f"inbox: unknown screen {d['shot']}")
        _put(stem + ".json", json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"), f"inbox: words of {d['shot']}")
        done[key] = {"t": time.time(), "path": stem, "words": d.get("words", [])[:10], "phase": d.get("phase", ""),
                     "action": d.get("action", ""), "account": id}
        n += 1
    # battle pictures (+ what the vision model found): Claude checks them and trains the next model with them
    try:
        import vision
        sent_b = st.setdefault("battles_sent", [])
        if settings.load_app().get("share_battles", True) is not False:
            nb = 0                                   # their own budget: every base attacked reaches Claude
            for jpg in sorted(vision.KEEP.glob("*.jpg"))[-40:]:
                if nb >= 12 or jpg.stem in sent_b: continue
                nb += 1
                meta = jpg.with_suffix(".json")
                stem = f"inbox/battles/{teach._safe(id)}_{jpg.stem}"
                _put(stem + ".jpg", jpg.read_bytes(), f"battle picture {jpg.stem}")
                if meta.exists(): _put(stem + ".json", meta.read_bytes(), f"battle objects {jpg.stem}")
                sent_b.append(jpg.stem)
                n += 1
            st["battles_sent"] = sent_b[-500:]
    except Exception:
        pass
    # the program's errors (with the screenshot taken at that moment): Claude reads and fixes them.
    # The same error (message + place) is sent once a day; the last 7 days on the first run.
    try:
        import stats
        if settings.load_app().get("send_errors", True) is not False:
            since = st.get("errors_sent_t") or time.time() - 7 * 86400
            day = time.strftime("%Y%m%d")
            seen = st.get("errors_seen", {}) if st.get("errors_day") == day else {}
            ne = 0
            newest = since
            shots = Path.home() / ".CoC_Bot" / "errors" / str(id)
            import version
            for e in stats.read(id, since=since + 0.001):
                if e.get("type") != "error": continue
                newest = max(newest, e.get("t", 0))
                sig = f"{e.get('message', '')[:80]}|{e.get('where', '')}"
                if sig in seen: continue
                if ne >= 10: break
                seen[sig] = 1
                stem = f"inbox/errors/{teach._safe(id)}_{time.strftime('%Y%m%d_%H%M%S', time.localtime(e.get('t', 0)))}_{abs(hash(sig)) % 1000:03d}"
                _put(stem + ".json", json.dumps(dict(e, account=id, bot_version=version.VERSION), ensure_ascii=False,
                                                indent=1).encode("utf-8"), f"error: {e.get('message', '')[:60]}")
                shot = shots / str(e.get("shot", ""))
                if e.get("shot") and shot.exists(): _put(stem + ".jpg", shot.read_bytes(), "error screenshot")
                ne += 1
            st.update(errors_sent_t=newest, errors_day=day, errors_seen=seen)
    except Exception:
        pass
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
    mp = _get_json("knowledge/map.json")                  # the screen map (navigator: every screen and its buttons)
    if isinstance(mp, dict) and mp: _save(BASE / "map.json", mp)
    c = _get_json("knowledge/model_cnn.json")             # the deep brain's examples (same pictures)
    if isinstance(c, dict) and c.get("items"):
        _save(BASE / "model_cnn.json", c)
        try: __import__("screen_cnn").load(force=True)
        except Exception: pass
    m = _get_json("knowledge/model.json")                 # the screen model Claude trained on the labelled pictures
    if isinstance(m, dict) and m.get("items"):
        _save(BASE / "model.json", m)
        try: __import__("screen_model").load(force=True)
        except Exception: pass
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
FINGERPRINT_MAX = 26     # dhash distance (of 128 bits) that still counts as "the same screen"


def match_picture(frame):
    """The taught rule whose example pictures look like this frame (works without reading any word)."""
    try:
        import capture_session as cs
        h = cs.dhash(frame)
    except Exception:
        return None, None
    best, best_d = None, 999
    for r in _load(KNOW, {}).get("screens", []):
        for fp in r.get("fingerprints", []):
            try: d = cs.distance(h, (int(fp[0]), int(fp[1])))
            except (ValueError, TypeError, IndexError): continue
            if d < best_d: best, best_d = r, d
    return (best, best_d) if best is not None and best_d <= FINGERPRINT_MAX else (None, best_d)


def match_screen(words, phase="", frame=None):
    """The taught rule for this screen: by its words, else by how it looks (fingerprint of the taught pictures)."""
    r = _match_words(words, phase)
    if r is None and frame is not None:
        r, _d = match_picture(frame)
    return r


def _match_words(words, phase=""):
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
            w = float(a.get("s", 1))
            # short waits are only for the screen to change: the bot sees it instantly now (long ones = loading)
            _t.sleep(min(10.0, w) if w >= 5 else min(w, 0.4))
    return did


# ====================================================================== capture sessions (one commit for all pictures)
def _api(method, path, body=None, timeout=60):
    import requests
    c = _cfg()
    # no "/" at the end: GitHub answers ".../repos/owner/name/" with 404 Not Found
    url = f"https://api.github.com/repos/{c['repo']}" + (f"/{path}" if path else "")
    r = requests.request(method, url, headers=_headers(c["token"]), json=body, timeout=timeout)
    if r.status_code >= 300: raise RuntimeError(f"GitHub {r.status_code}: {r.text[:160]}")
    return r.json()


def commit_files(files, message, progress=None):
    """files: {repo path: bytes} -> one commit on the default branch (Git Data API)."""
    repo = _api("GET", "")
    branch = repo.get("default_branch") or "main"
    head = _api("GET", f"git/ref/heads/{branch}")["object"]["sha"]
    base_tree = _api("GET", f"git/commits/{head}")["tree"]["sha"]
    tree = []
    for i, (path, data) in enumerate(files.items()):
        blob = _api("POST", "git/blobs", {"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"}, timeout=120)
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        if progress: progress(i + 1, len(files))
    new_tree = _api("POST", "git/trees", {"base_tree": base_tree, "tree": tree})["sha"]
    commit = _api("POST", "git/commits", {"message": message, "tree": new_tree, "parents": [head]})["sha"]
    _api("PATCH", f"git/refs/heads/{branch}", {"sha": commit})
    return commit


def send_capture(id, session):
    """Upload a capture session: pictures + their words + an index page, in one commit."""
    import capture_session as cs, version
    s = cs.load_session(id, session)
    if not s or not s.get("shots"): return {"ok": False, "error": "empty"}
    folder = cs.session_dir(id, session)
    root = f"captures/{session}_{cs._safe(id)}"
    files = {}
    lines = [f"# التقاط {session} — {len(s['shots'])} شاشة", "",
             "> Claude: افهم كل صورة (الشاشة بتاعة إيه، الأزرار، الجيش لو موجود) واكتب القواعد في `knowledge/` زي `LEARNING.md`، "
             "وحط الحالة في `knowledge/status.json` بالمفتاح `captures/<session>/<NNN>`.", "",
             "| # | الصورة | دوس على إيه قبلها | الكلام اللي اتقرا |", "|---|---|---|---|"]
    for sh in s["shots"]:
        p = folder / sh["file"]
        if not p.exists(): continue
        stem = sh["file"][:-4]
        files[f"{root}/{sh['file']}"] = p.read_bytes()
        meta = {"file": sh["file"], "t": sh.get("t"), "tap": sh.get("tap"), "words": sh.get("words", []), "note": sh.get("note", ""), "account": id,
                "session": session, "bot_version": version.VERSION, "kind": "capture"}
        files[f"{root}/{stem}.json"] = json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8")
        tap = f"({sh['tap'][0]:.2f}, {sh['tap'][1]:.2f})" if sh.get("tap") else "—"
        words = " · ".join(str(w).replace("|", "/") for w in (sh.get("words") or [])[:10]) or "—"
        note = (sh.get("note") or "").replace("|", "/")
        lines.append(f"| {stem} | <img src=\"{sh['file']}\" width=\"260\"> | {tap} | {('📝 ' + note + '<br>') if note else ''}{words} |")
    for b in s.get("battles", []):           # your attacks: their pictures + taps
        bdir = folder / b["folder"]
        if not bdir.exists(): continue
        for f in sorted(bdir.iterdir()):
            if f.suffix in (".jpg", ".json"): files[f"{root}/{b['folder']}/{f.name}"] = f.read_bytes()
        lines.append(f"| ⚔️ {b['folder']} | [{b['frames']} صورة]({b['folder']}/) | {b['taps']} نزلة جيش | {b['duration']:.0f} ثانية |")
    files[f"{root}/README.md"] = "\n".join(lines).encode("utf-8")
    files[f"{root}/session.json"] = json.dumps(dict(s, account=id), ensure_ascii=False, indent=1).encode("utf-8")

    def prog(i, n):
        cs.set_status(id, "sending", session=session, shots=len(s["shots"]), sent=i, total=n)
    try:
        sha = commit_files(files, f"capture {session}: {len(s['shots'])} screens", prog)
    except Exception as e:
        cs.set_status(id, "send_failed", session=session, shots=len(s["shots"]), error=str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}
    s["sent"] = time.time()
    s["sent_path"] = root
    s["commit"] = sha
    cs.save_session(id, session, s)
    cs.set_status(id, "sent", session=session, shots=len(s["shots"]), path=root)
    return {"ok": True, "path": root, "shots": len(s["shots"])}


def upload_shot(id, session, file, wait_words=10):
    """Send one picture right away (floating button): captures/<session>_<account>/NNN.jpg + .json."""
    import capture_session as cs, version
    if not configured(): return False
    deadline = time.time() + wait_words
    shot = None
    while time.time() < deadline:      # the words are read in the background: give them a moment
        d = cs.load_session(id, session) or {}
        shot = next((x for x in d.get("shots", []) if x["file"] == file), None)
        if shot is None: return False
        if shot.get("words"): break
        time.sleep(1)
    p = cs.session_dir(id, session) / file
    if not p.exists(): return False
    root = f"captures/{session}_{cs._safe(id)}"
    stem = file[:-4]
    meta = {"file": file, "t": shot.get("t"), "tap": shot.get("tap"), "words": shot.get("words", []), "note": shot.get("note", ""),
            "account": id, "session": session, "bot_version": version.VERSION, "kind": "capture"}
    try:
        _put(f"{root}/{file}", p.read_bytes(), f"picture {session}/{stem}")
        _put(f"{root}/{stem}.json", json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"), f"words {session}/{stem}")
    except Exception as e:
        st = _load(STATE, {})
        st["error"] = str(e)[:200]
        _save(STATE, st)
        return False
    with cs._LOCK:
        d = cs.load_session(id, session) or {}
        for x in d.get("shots", []):
            if x["file"] == file: x["sent"] = True
        cs.save_session(id, session, d)
    return True


# ====================================================================== unknown screens -> straight to Claude
# Automatic learning: every screen the bot doesn't understand is photographed and sent at once (when it stays still
# for a moment: a screen that flashes by is an animation), the user is told, and the bot carries on.
# A screen it keeps getting stuck on is sent as "stuck" (those come first for Claude).
STUCK_SECONDS = 20       # the same unknown screen for this long (or seen 3 times) = stuck
UNKNOWN_PER_DAY = 60     # never more pictures than this a day (a flood of the same kind of screen)
_stuck = {"hash": None, "since": 0.0, "seen": 0}


def note_unknown(id, frame, words, phase):
    """Called for every screen the bot doesn't know: sent as soon as it is seen twice in a row (once per screen:
    screens already sent or already taught are not sent again); sent as "stuck" when it doesn't go away."""
    import capture_session as cs
    try: h = cs.dhash(frame)
    except Exception: return False
    now = time.time()
    if _stuck["hash"] is not None and cs.distance(h, _stuck["hash"]) <= 10:
        _stuck["seen"] += 1
    else:
        _stuck.update(hash=h, since=now, seen=1)
        return False
    if _stuck["seen"] == 2:
        report_unknown(id, frame, phase, words=words, h=h)
    if now - _stuck["since"] < STUCK_SECONDS and _stuck["seen"] < 3: return False
    _stuck.update(hash=None, since=0.0, seen=0)
    return report_stuck(id, frame, words, phase, h)


def report_unknown(id, frame, phase, words=(), h=None, why="screen"):
    """A screen (or battle base, builder-menu row…) the bot doesn't understand: to Claude now, the bot carries on."""
    return _report(id, frame, words, phase, h, kind="unknown", why=why)


def report_stuck(id, frame, words, phase, h=None):
    """Save + send one screen the bot got stuck on (in the background), and tell the user."""
    return _report(id, frame, words, phase, h, kind="stuck")


def _report(id, frame, words, phase, h=None, kind="stuck", why="screen"):
    import capture_session as cs, threading
    try:
        import settings
        if settings.load_app().get("send_stuck", True) is False: return False
    except Exception:
        pass
    h = h or cs.dhash(frame)
    st = _load(STATE, {})
    key = "stuck_sent" if kind == "stuck" else "unknown_sent"
    sent = st.setdefault(key, [])
    if any(cs.distance(h, (int(a), int(b))) <= 12 for a, b in sent): return False   # this screen was sent already
    if why == "screen":
        rule, _d = match_picture(frame)
        if rule is not None: return False                                           # taught meanwhile
    if kind != "stuck":
        day = time.strftime("%Y%m%d")
        if st.get("unknown_day") != day: st.update(unknown_day=day, unknown_n=0)
        if st.get("unknown_n", 0) >= UNKNOWN_PER_DAY: return False
        st["unknown_n"] = st.get("unknown_n", 0) + 1
    sent.append([str(h[0]), str(h[1])])
    st[key] = sent[-500:]
    _save(STATE, st)
    import cv2
    name = time.strftime("%Y%m%d_%H%M%S")
    folder = BASE / kind
    folder.mkdir(parents=True, exist_ok=True)
    small = cv2.resize(frame, (1280, int(1280 * frame.shape[0] / frame.shape[1])))
    cv2.imwrite(str(folder / f"{name}.jpg"), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    meta = {"t": time.time(), "account": id, "phase": phase, "words": list(words)[:60], "kind": kind, "why": why,
            "note": "the bot got stuck on this screen (auto)" if kind == "stuck" else
                    f"the bot didn't understand this {why} and carried on (auto)"}
    (folder / f"{name}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")

    def send():
        if not configured(): return
        try:
            import version
            stem = f"inbox/{kind}/{_safe_id(id)}_{name}"
            _put(stem + ".jpg", (folder / f"{name}.jpg").read_bytes(), f"{kind}: {name}")
            _put(stem + ".json", json.dumps(dict(meta, bot_version=version.VERSION), ensure_ascii=False, indent=1).encode("utf-8"), f"{kind} words: {name}")
        except Exception as e:
            st2 = _load(STATE, {})
            st2["error"] = str(e)[:200]
            _save(STATE, st2)
    threading.Thread(target=send, daemon=True).start()
    try:
        from utils import logger, send_notification
        if kind == "stuck":
            logger.info(f"Stuck on a screen the bot doesn't know — picture sent to Claude ({phase})")
            send_notification("🤔 البوت وقف على شاشة مايعرفهاش — صوّرها وبعتها لـ Claude علشان يتعلّمها")
        else:
            what = {"screen": "screen", "vision": "base", "builder_row": "builder menu row"}.get(why, why)
            logger.info(f"Picture sent to Claude: did not understand this {what} ({phase}), carrying on")
    except Exception:
        pass
    return True


def _safe_id(x):
    return "".join(c for c in str(x) if c.isalnum() or c in "-_") or "main"
