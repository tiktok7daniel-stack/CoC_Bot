import sys
from pathlib import Path

if hasattr(sys, "_MEIPASS"):
    path = Path(sys._MEIPASS) / "gui_server"
else:
    path = Path(__file__).parent.resolve()
    sys.path.append(str(path.parent))

sys.path.append(str(path))

import os
import time
from flask import Flask, render_template, jsonify, abort, request
try:
    import configs
except:
    import configs_build as configs
import settings as bot_settings
import stats
from version import VERSION

app = Flask(__name__)
app.json.ensure_ascii = False
bot_pipe = None

class Instance:
    """A running bot process (one per account)."""
    def __init__(self, id):
        self.id = id
        self.run_status = ""
        self.end_time = 0
        self.started_at = time.time()

instances = {}

def accounts():
    return bot_settings.load_app()["accounts"]

def valid_id(id):
    return id in accounts()

# ---------------------------------------------------------------- pages

@app.route("/", methods=["GET"])
def home():
    return render_template("app.html", version=VERSION)

# ---------------------------------------------------------------- state / control

def instance_state(id):
    inst = instances.get(id)
    if inst is None:
        return {"id": id, "running": False, "status": "stopped", "end_time": 0}
    paused = inst.end_time > time.time()
    return {
        "id": id,
        "running": True,
        "status": "paused" if paused else (inst.run_status if inst.run_status != "" else "starting"),
        "end_time": inst.end_time,
        "started_at": inst.started_at,
    }

@app.route("/api/state", methods=["GET"])
def api_state():
    return jsonify({
        "version": VERSION,
        "current_time": time.time(),
        "accounts": [instance_state(i) for i in accounts()],
    })

@app.route("/api/account/<id>/<action>", methods=["POST"])
def api_account_action(id, action):
    if not valid_id(id): return jsonify({"ok": False, "error": "invalid_id"}), 400
    if action == "start":
        if id not in instances:
            instances[id] = Instance(id)
            bot_pipe.send({"action": "start", "id": id})
        return jsonify({"ok": True})
    if action == "stop":
        if instances.pop(id, None) is not None:
            bot_pipe.send({"action": "stop", "id": id})
        return jsonify({"ok": True})
    if action == "wake": # "run a cycle now"
        if id not in instances: return jsonify({"ok": False, "error": "not_running"}), 400
        bot_settings.request_wake(id)
        return jsonify({"ok": True})
    if action == "pause":
        inst = instances.get(id)
        if inst is None: return jsonify({"ok": False, "error": "not_running"}), 400
        minutes = float((request.json or {}).get("minutes", 0))
        inst.end_time = time.time() + minutes * 60 if minutes > 0 else 0
        return jsonify({"ok": True, "end_time": inst.end_time})
    abort(404)

# legacy endpoint (old home page / external tools)
@app.route("/instance_action", methods=["POST"])
def handle_instance_start_stop():
    data = request.json or {}
    id, action = data.get("id", ""), data.get("action", "")
    if action not in ("start", "stop") or not valid_id(id): return jsonify(0)
    api_account_action(id, action)
    return jsonify(1)

# ---------------------------------------------------------------- settings

@app.route("/api/settings/<id>", methods=["GET", "POST"])
def api_settings(id):
    if not valid_id(id): abort(404)
    if request.method == "POST":
        saved = bot_settings.save(id, request.json or {})
        # "same settings for every account": what is saved on one account is saved on all of them
        app_cfg = bot_settings.load_app()
        if app_cfg.get("sync_settings"):
            for other in app_cfg.get("accounts", []):
                if other != id and valid_id(other): bot_settings.save(other, _keep_own(other, saved))
        return jsonify(saved)
    return jsonify(bot_settings.load(id))

# what stays different on every account even when settings are shared: the loadout it attacks with
# (its own saved army / its own recording)
PER_ACCOUNT = ("active_plan",)

def _keep_own(target, data):
    import copy
    out = copy.deepcopy(data)
    if (bot_settings.SETTINGS_DIR / f"{bot_settings._safe_id(target)}.json").exists():
        mine = bot_settings.load(target)
        for k in PER_ACCOUNT: out[k] = mine.get(k, out.get(k))
    return out

@app.route("/api/settings_copy", methods=["POST"])
def api_settings_copy():
    """Copy one account's settings to other accounts ({"from": id, "to": [ids] | "all"})."""
    d = request.json or {}
    src = d.get("from", "")
    if not valid_id(src): abort(404)
    accounts = bot_settings.load_app().get("accounts", [])
    targets = [a for a in accounts if a != src] if d.get("to") == "all" else [a for a in (d.get("to") or []) if a != src]
    data = bot_settings.load(src)
    done = []
    for t in targets:
        if valid_id(t):
            bot_settings.save(t, _keep_own(t, data))
            bot_settings.request_wake(t) if t in instances else None
            done.append(t)
    return jsonify({"ok": True, "copied": done})

@app.route("/api/app_settings", methods=["GET", "POST"])
def api_app_settings():
    if request.method == "POST":
        data = request.json or {}
        saved = bot_settings.save_app(data)
        bot_settings.apply_app_settings()
        try:
            import updater
            if sys.platform == "win32" and updater.autostart_enabled() != bool(saved["start_with_windows"]):
                updater.set_autostart(bool(saved["start_with_windows"]))
        except Exception as e:
            return jsonify({**saved, "warning": str(e)})
        return jsonify(saved)
    data = bot_settings.load_app()
    try:
        import updater
        if sys.platform == "win32": data["start_with_windows"] = updater.autostart_enabled()
    except Exception: pass
    data["platform"] = sys.platform
    return jsonify(data)

@app.route("/api/defaults", methods=["GET"])
def api_defaults():
    return jsonify(bot_settings.default_settings())

@app.route("/api/vocab", methods=["GET"])
def api_vocab():
    """Building / troop names for the priority pickers (from the bot's cached game vocabulary)."""
    try:
        import json
        cache = Path(__file__).resolve().parent.parent / "cache.json"
        if not cache.exists(): cache = Path.home() / ".CoC_Bot" / "cache.json"
        vocab = json.loads(cache.read_text()).get("vocab", {}) if cache.exists() else {}
    except Exception:
        vocab = {}
    return jsonify(vocab)

# ---------------------------------------------------------------- stats / log

@app.route("/api/stats/<id>", methods=["GET"])
def api_stats(id):
    if not valid_id(id): abort(404)
    return jsonify(stats.summary(id))

@app.route("/api/stats_daily/<id>", methods=["GET"])
def api_stats_daily(id):
    """Permanent per-day statistics. id = an account or "all"; ?days=N (0 = everything)."""
    days = int(request.args.get("days", 0) or 0)
    if id == "all":
        accs = bot_settings.load_app().get("accounts", []) if hasattr(bot_settings, "load_app") else []
        return jsonify({"days": stats.merge_days([stats.daily(a, days) for a in accs])})
    if not valid_id(id): abort(404)
    return jsonify({"days": stats.daily(id, days)})

@app.route("/api/stats/<id>/reset", methods=["POST"])
def api_stats_reset(id):
    if not valid_id(id): abort(404)
    stats.clear(id)
    return jsonify({"ok": True})

def log_path(id):
    if getattr(sys, "frozen", False):
        return Path.home() / ".CoC_Bot" / "debug" / f"{id}.log"
    return Path("debug") / f"{id}.log"

@app.route("/api/log/<id>", methods=["GET"])
def api_log(id):
    if not valid_id(id): abort(404)
    n = min(int(request.args.get("n", 400)), 3000)
    p = log_path(id)
    if not p.exists(): return jsonify({"lines": []})
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 400_000))
            text = f.read().decode("utf-8", errors="replace")
        return jsonify({"lines": text.splitlines()[-n:]})
    except OSError:
        return jsonify({"lines": []})

# ---------------------------------------------------------------- errors / diagnostics

ERRORS_DIR = Path.home() / ".CoC_Bot" / "errors"

@app.route("/api/errors/<id>", methods=["GET"])
def api_errors(id):
    if not valid_id(id): abort(404)
    return jsonify({"items": stats.problems(id)})

@app.route("/api/errors/<id>/clear", methods=["POST"])
def api_errors_clear(id):
    if not valid_id(id): abort(404)
    stats.record(id, "errors_cleared")
    return jsonify({"ok": True})

@app.route("/api/errors/<id>/shot/<name>", methods=["GET"])
def api_error_shot(id, name):
    from flask import send_from_directory
    if not valid_id(id) or "/" in name or "\\" in name or ".." in name: abort(404)
    return send_from_directory(ERRORS_DIR / id, name)

@app.route("/api/errors/<id>/open", methods=["POST"])
def api_errors_open(id):
    if not valid_id(id): abort(404)
    folder = ERRORS_DIR / id
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32": os.startfile(str(folder))
        elif sys.platform == "darwin":
            import subprocess; subprocess.Popen(["open", str(folder)])
        return jsonify({"ok": True, "path": str(folder)})
    except Exception as e:
        return jsonify({"ok": False, "path": str(folder), "error": str(e)})

@app.route("/api/report/<id>", methods=["POST"])
def api_report(id):
    """Zip log + recent events + settings + error screenshots onto the Desktop, to send for help."""
    import zipfile, json as _json
    if not valid_id(id): abort(404)
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        onedrive = Path.home() / "OneDrive" / "Desktop"
        desktop = onedrive if onedrive.exists() else Path.home()
    out = desktop / f"CoC_Bot_report_{id}_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            lp = log_path(id)
            if lp.exists(): z.write(lp, f"{id}.log")
            z.writestr("errors.json", _json.dumps(stats.problems(id, 300), ensure_ascii=False, indent=1))
            z.writestr("summary.json", _json.dumps(stats.summary(id), ensure_ascii=False, indent=1, default=str))
            z.writestr("settings.json", _json.dumps(bot_settings.load(id), ensure_ascii=False, indent=1))
            z.writestr("version.txt", VERSION)
            for shot in sorted((ERRORS_DIR / id).glob("*.jpg"))[-25:]:
                z.write(shot, f"screenshots/{shot.name}")
        return jsonify({"ok": True, "path": str(out)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---------------------------------------------------------------- setup screen (emulator / accounts)

@app.route("/api/setup/status", methods=["GET"])
def api_setup_status():
    from gui_server import emu_setup
    return jsonify(emu_setup.status(bot_settings.load_app(), list(instances.keys())))

@app.route("/api/setup/<action>", methods=["POST"])
def api_setup_action(action):
    from gui_server import emu_setup
    data = request.json or {}
    app_cfg = bot_settings.load_app()
    acc = str(data.get("account", ""))
    if action == "link": # account -> emulator copy
        links = dict(app_cfg.get("emulator_links", {}) or {})
        if str(data.get("copy", "")) == "": links.pop(acc, None)
        else: links[acc] = data["copy"]
        app_cfg["emulator_links"] = links
        bot_settings.save_app(app_cfg); bot_settings.apply_app_settings()
        return jsonify({"ok": True})
    if action == "add_account":
        name = bot_settings._safe_id(data.get("name", ""))
        if not name: return jsonify({"ok": False, "error": "no_name"}), 400
        if name not in app_cfg["accounts"]: app_cfg["accounts"].append(name)
        if str(data.get("copy", "")) != "":
            app_cfg.setdefault("emulator_links", {})[name] = data["copy"]
        bot_settings.save_app(app_cfg); bot_settings.apply_app_settings()
        return jsonify({"ok": True})
    if acc not in app_cfg["accounts"]: return jsonify({"ok": False, "error": "invalid_id"}), 400
    fn = {"launch": emu_setup.launch, "fix_res": emu_setup.fix_resolution, "open_game": emu_setup.open_game,
          "auto": emu_setup.auto_setup}.get(action)
    if fn is None: abort(404)
    r = fn(app_cfg, acc)
    return jsonify({"ok": r == "ok", "result": r})

# ---------------------------------------------------------------- unit pictures (uploaded to the project)

@app.route("/api/units", methods=["GET"])
def api_units():
    import unit_icons
    return jsonify(unit_icons.catalog())

@app.route("/unit/<group>/<name>.png", methods=["GET"])
def unit_picture(group, name):
    import unit_icons
    from flask import send_file
    p = unit_icons.path(group, name)
    if p is None: abort(404)
    return send_file(str(p), mimetype="image/png", max_age=86400)

# ---------------------------------------------------------------- village intelligence (Clash Farmer)

@app.route("/api/village/<id>", methods=["GET"])
def api_village(id):
    import village
    if not valid_id(id): abort(404)
    data = village.load(id)
    data["pending"] = village.pending(id)
    data["now"] = time.time()
    return jsonify(data)

@app.route("/api/village/<id>/command", methods=["POST"])
def api_village_command(id):
    """1-tap upgrade {cmd: "upgrade", name} / batch walls {cmd: "walls", count} / rescan {cmd: "scan"}."""
    import village
    if not valid_id(id): abort(404)
    d = request.json or {}
    if d.get("cmd") not in ("upgrade", "walls", "scan", "army"): return jsonify({"ok": False, "error": "bad_cmd"}), 400
    n = village.push_command(id, d["cmd"], name=str(d.get("name", ""))[:60], count=int(d.get("count", 10) or 10))
    inst = instances.get(id)
    if inst is None: return jsonify({"ok": True, "queued": n, "running": False})
    inst.end_time = 0                       # a paused bot would never pick it up
    bot_settings.request_wake(id)
    return jsonify({"ok": True, "queued": n, "running": True})

# ---------------------------------------------------------------- battle recordings

@app.route("/api/recordings", methods=["GET"])
def api_recordings():
    import recorder
    return jsonify({"items": recorder.list_recordings()})

@app.route("/api/recordings/delete", methods=["POST"])
def api_recordings_delete():
    import recorder
    recorder.delete((request.json or {}).get("name", ""))
    return jsonify({"ok": True})

@app.route("/api/record/<id>", methods=["POST"])
def api_record(id):
    import recorder
    if not valid_id(id): abort(404)
    name = str((request.json or {}).get("name", "")).strip()
    if not name: return jsonify({"ok": False, "error": "no_name"}), 400
    recorder.request(id, name)
    recorder.set_status(id, "waiting")
    inst = instances.get(id)
    if inst is None: # the recording runs inside the bot: start it
        instances[id] = Instance(id)
        bot_pipe.send({"action": "start", "id": id})
    else:
        inst.end_time = 0 # a paused bot would never pick the request up
        bot_settings.request_wake(id)
    return jsonify({"ok": True})

# ---------------------------------------------------------------- learned armies (the bot watched the user)

@app.route("/api/armies", methods=["GET"])
def api_armies():
    import army_learn
    return jsonify({"items": army_learn.list_armies()})

@app.route("/api/armies/picture/<name>", methods=["GET"])
def api_army_picture(name):
    from flask import send_file
    import army_learn
    p = army_learn.picture_path(name)
    if not p: abort(404)
    return send_file(str(p), mimetype="image/jpeg")

@app.route("/api/armies/delete", methods=["POST"])
def api_army_delete():
    import army_learn
    army_learn.delete(str((request.json or {}).get("name", "")))
    return jsonify({"ok": True})

@app.route("/api/armies/learn/<id>", methods=["POST"])
def api_army_learn(id):
    import army_learn
    if not valid_id(id): abort(404)
    name = str((request.json or {}).get("name", "")).strip()
    if not name: return jsonify({"ok": False, "error": "no_name"}), 400
    army_learn.request(id, name)
    army_learn.set_status(id, "waiting", name=name)
    inst = instances.get(id)
    if inst is None:
        instances[id] = Instance(id)
        bot_pipe.send({"action": "start", "id": id})
    else:
        inst.end_time = 0
        bot_settings.request_wake(id)
    return jsonify({"ok": True})

@app.route("/api/armies/done/<id>", methods=["POST"])
def api_army_done(id):
    import army_learn
    if not valid_id(id): abort(404)
    army_learn.request_stop(id)
    return jsonify({"ok": True})

@app.route("/api/armies/status/<id>", methods=["GET"])
def api_army_status(id):
    import army_learn
    if not valid_id(id): abort(404)
    return jsonify(army_learn.get_status(id) or {})

# ---------------------------------------------------------------- Claude learning inbox (GitHub)

@app.route("/api/learn/<id>", methods=["GET"])
def api_learn(id):
    import learn_sync
    if not valid_id(id): abort(404)
    return jsonify(learn_sync.overview(id))

@app.route("/api/learn/<id>/sync", methods=["POST"])
def api_learn_sync(id):
    import learn_sync
    if not valid_id(id): abort(404)
    if not learn_sync.configured(): return jsonify({"ok": False, "error": "not_configured"})
    return jsonify(learn_sync.sync_now(id))

@app.route("/api/learn_test", methods=["POST"])
def api_learn_test():
    import learn_sync
    return jsonify(learn_sync.test())

@app.route("/api/record_status/<id>", methods=["GET"])
def api_record_status(id):
    import recorder
    if not valid_id(id): abort(404)
    return jsonify(recorder.get_status(id) or {})

# ---------------------------------------------------------------- teach the bot

@app.route("/api/teach", methods=["GET"])
def api_teach():
    import teach
    return jsonify({"catalog": teach.CATALOG, "taught": teach.load_meta()})

@app.route("/api/teach/capture/<id>", methods=["GET", "POST"])
def api_teach_capture(id):
    from flask import send_file
    import teach
    if not valid_id(id): abort(404)
    if request.method == "POST":
        if id not in instances: return jsonify({"ok": False, "error": "not_running"})
        teach.request_capture(id)
        return jsonify({"ok": True})
    p = teach.capture_path(id)
    if not p.exists(): abort(404)
    r = send_file(str(p), mimetype="image/png")
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/api/teach/save", methods=["POST"])
def api_teach_save():
    import teach
    d = request.json or {}
    if not valid_id(d.get("id", "")): abort(404)
    try:
        e = teach.teach(d.get("key", ""), d.get("rect", [0, 0, 0, 0]), teach.capture_path(d["id"]))
        return jsonify({"ok": True, "entry": e})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@app.route("/api/teach/forget", methods=["POST"])
def api_teach_forget():
    import teach
    teach.forget((request.json or {}).get("key", ""))
    return jsonify({"ok": True})

@app.route("/api/teach/template/<key>", methods=["GET"])
def api_teach_template(key):
    from flask import send_file
    import teach
    p = teach.template_path(key)
    if not p.exists(): abort(404)
    r = send_file(str(p), mimetype="image/png")
    r.headers["Cache-Control"] = "no-store"
    return r

@app.route("/api/discovered/<id>", methods=["GET"])
def api_discovered(id):
    import teach
    if not valid_id(id): abort(404)
    return jsonify({"items": teach.discoveries(id)})

@app.route("/api/discovered/<id>/img/<name>", methods=["GET"])
def api_discovered_img(id, name):
    from flask import send_from_directory
    import teach
    if not valid_id(id) or "/" in name or "\\" in name or ".." in name: abort(404)
    return send_from_directory(teach.DISCOVERED_DIR / teach._safe(id), name)

@app.route("/api/discovered/<id>/use", methods=["POST"])
def api_discovered_use(id):
    """Load a recorded screen into the Teach tab so the user can teach from it."""
    import shutil, teach
    name = (request.json or {}).get("full", "")
    if not valid_id(id) or "/" in name or "\\" in name or ".." in name: abort(404)
    src = teach.DISCOVERED_DIR / teach._safe(id) / name
    if not src.exists(): return jsonify({"ok": False})
    teach.CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, teach.capture_path(id))
    return jsonify({"ok": True})

# ---------------------------------------------------------------- live system info (home page cards)

@app.route("/api/system/<id>", methods=["GET"])
def api_system(id):
    import json
    if not valid_id(id): abort(404)
    out = {"cpu": None, "ram": None, "ram_mb": None, "uptime": None, "adb": None, "emulator": bot_settings.load_app().get("emulator"),
           "phase": None, "phase_age": None}
    try:
        import psutil
        out["cpu"] = psutil.cpu_percent(interval=0.2)
        out["ram"] = psutil.virtual_memory().percent
    except Exception:
        pass
    inst = instances.get(id)
    if inst: out["uptime"] = time.time() - inst.started_at
    p = Path.home() / ".CoC_Bot" / "phase" / f"{id}.json"
    try:
        d = json.loads(p.read_text())
        out.update(adb=d.get("adb"), emulator=d.get("emulator") or out["emulator"], phase=d.get("phase"), phase_age=time.time() - d.get("t", 0))
        if inst and d.get("pid"):
            import psutil
            out["ram_mb"] = int(psutil.Process(int(d["pid"])).memory_info().rss / 2**20)
    except Exception:
        pass
    return jsonify(out)

# ---------------------------------------------------------------- system check

def _bluestacks_conf():
    for c in (r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf", "/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf"):
        if Path(c).exists(): return Path(c)
    return None

@app.route("/api/syscheck/<id>", methods=["GET"])
def api_syscheck(id):
    """Checks everything the bot depends on; each item: {key, status: ok|warn|bad, info}."""
    import re, shutil, subprocess, importlib.util
    if not valid_id(id): abort(404)
    out = []
    add = lambda key, status, info="": out.append({"key": key, "status": status, "info": str(info)})
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
    app_cfg = bot_settings.load_app()

    # Python
    v = sys.version_info
    add("python", "ok" if v >= (3, 11) else "bad", f"{v.major}.{v.minor}.{v.micro}")

    # ADB program: the same one the bot uses (LDPlayer's / BlueStacks' own, else adb on PATH)
    from gui_server import emu_setup
    ld_con = emu_setup.ld_console(app_cfg) if app_cfg.get("emulator") == "ldplayer" else None
    adb = emu_setup.adb_exe(app_cfg, ld_con)
    add("adb", "ok" if adb else "bad", adb or "")

    # Other programs running their own ADB (they kill each other's connection)
    try:
        import psutil
        paths = set()
        for proc in psutil.process_iter(["name", "exe"]):
            name = (proc.info.get("name") or "").lower()
            if name in ("adb.exe", "hd-adb.exe", "adb"):
                paths.add(proc.info.get("exe") or name)
        # LDPlayer / BlueStacks start their own adb: that is the one the bot uses, not a conflict
        own_dirs = {str(Path(adb).parent).lower()} if adb else set()
        others = [x for x in paths if str(Path(x).parent).lower() not in own_dirs
                  and not (adb and str(Path(x)).lower() == str(Path(adb)).lower())]
        add("adb_conflict", "warn" if others else "ok", " | ".join(sorted(others)))
    except Exception as e:
        add("adb_conflict", "warn", e)

    # BlueStacks instance, port and resolution
    port = None
    conf = _bluestacks_conf() if app_cfg.get("emulator") == "bluestacks" else None
    if app_cfg.get("emulator") == "bluestacks":
        if conf is None:
            add("bs_instance", "bad", "bluestacks.conf")
        else:
            text = conf.read_text(errors="ignore")
            inst = next((m.group(1) for m in re.finditer(r'^bst\.instance\.([^.]+)\.display_name="?(.*?)"?$', text, re.M) if m.group(2) == id), None)
            if inst is None:
                add("bs_instance", "bad", id)
            else:
                get = lambda k: (re.search(rf'^bst\.instance\.{re.escape(inst)}\.{k}="?(.*?)"?$', text, re.M) or [None, None])[1]
                port = get("adb_port")
                add("bs_instance", "ok", f"{id} → {inst}, ADB 127.0.0.1:{port}")
                w, h = get("fb_width"), get("fb_height")
                if w and h: add("resolution", "ok" if (w, h) == ("1920", "1080") else "bad", f"{w}×{h}")
                if get("enable_adb_access") == "0": add("bs_adb_setting", "bad", "")

    # LDPlayer copy linked to this account, its port, resolution and connection
    if app_cfg.get("emulator") == "ldplayer":
        cps = emu_setup.ld_instances(ld_con)
        c = emu_setup.link_for(id, cps, app_cfg.get("emulator_links", {}) or {})
        if not ld_con: add("ld_found", "bad", "")
        elif c is None: add("bs_instance", "bad", ", ".join(x["title"] for x in cps) or "-")
        else:
            port = str(5555 + 2 * int(c["index"]))
            add("bs_instance", "ok", f"{id} → {c['title']}, ADB 127.0.0.1:{port}")
            if c.get("width"):
                tw, th, td = emu_setup.target(app_cfg)
                ok = emu_setup.good_res(app_cfg, c["width"], c["height"], c.get("dpi"))
                add("resolution", "ok" if ok else "bad", f"{c['width']}×{c['height']} · {c.get('dpi')} DPI")
            if not c["running"]: add("emu_running", "bad", c["title"])
            else: emu_setup.adb_state(adb, f"127.0.0.1:{port}") # connect so the state below is real

    # Device state
    if adb and port:
        try:
            r = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=10, **kw)
            state = next((l.split()[1] for l in r.stdout.splitlines() if l.startswith(f"127.0.0.1:{port}") and len(l.split()) > 1), None)
            add("device", "ok" if state == "device" else ("warn" if state is None else "bad"), state or "-")
        except Exception as e:
            add("device", "bad", e)

    # Bot running
    add("bot_running", "ok" if id in instances else "warn", "")

    # OCR
    add("tesseract", "ok" if _find_tesseract() else "warn", _find_tesseract() or "")
    add("easyocr", "ok" if importlib.util.find_spec("easyocr") else "bad", "")

    # Learned items
    try:
        import teach
        meta = teach.load_meta()
        add("learned", "ok" if meta else "warn", f"{len(meta)} ({sum(1 for e in meta.values() if e.get('auto'))} auto)")
    except Exception as e:
        add("learned", "warn", e)

    # Internet + GitHub token
    try:
        import requests
        from version import UPDATE_REPO
        token = app_cfg.get("github_token", "")
        headers = {"Accept": "application/vnd.github+json"}
        if token: headers["Authorization"] = f"Bearer {token}"
        r = requests.get(f"https://api.github.com/repos/{UPDATE_REPO}", headers=headers, timeout=10)
        add("internet", "ok", "")
        if not token:
            add("gh_token", "warn", "")
        elif r.status_code == 401:
            add("gh_token", "bad", "401")
        elif r.status_code != 200:
            add("gh_token", "bad", r.status_code)
        else:
            add("gh_token", "ok", "")
            add("gh_issues", "ok" if r.json().get("has_issues") else "bad", "")
            r2 = requests.get(f"https://api.github.com/repos/{UPDATE_REPO}/issues?per_page=1", headers=headers, timeout=10)
            add("gh_issues_perm", "ok" if r2.status_code == 200 else "bad", r2.status_code)
    except Exception as e:
        add("internet", "bad", e)
    return jsonify({"items": out})

# ---------------------------------------------------------------- GitHub error reports

def _sanitize(text):
    """Never publish personal paths or secrets."""
    import re
    home = str(Path.home())
    text = text.replace(home, "~").replace(home.replace("\\", "/"), "~")
    text = re.sub(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gsk_[A-Za-z0-9]{20,}|\d{6,}:[A-Za-z0-9_-]{30,})", "<secret>", text)
    return text

def github_report(id, since=0):
    import requests
    from version import UPDATE_REPO
    app_cfg = bot_settings.load_app()
    token = app_cfg.get("github_token", "")
    if not token: return {"ok": False, "error": "no_token"}
    groups = stats.error_groups(id, since)
    if not groups: return {"ok": True, "skipped": "no_errors"}
    lines = [f"**Version:** {VERSION}  ", f"**Account:** {id}  ", f"**Platform:** {sys.platform}  ",
             f"**Emulator:** {app_cfg.get('emulator')}", "", "| # | Type | Message | Steps | Where |", "|---|---|---|---|---|"]
    for g in groups[:25]:
        msg = g["message"].replace("|", "/")[:150]
        lines.append(f"| {g['count']} | {g['type']} | {msg} | {', '.join(g['phases'])} | `{g['where'][:80]}` |")
    details = [f"- **{g['message'][:120]}**: `{g['detail'][:200]}`" for g in groups[:25] if g["detail"]]
    if details: lines += ["", "### Details", *details]
    lp = log_path(id)
    if lp.exists():
        tail = lp.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]
        lines += ["", "<details><summary>Last log lines</summary>", "", "```", *tail, "```", "</details>"]
    body = _sanitize("\n".join(lines))[:60000]
    title = f"[Bot report] {id} v{VERSION} - {len(groups)} problem types - {time.strftime('%Y-%m-%d %H:%M')}"
    r = requests.post(f"https://api.github.com/repos/{UPDATE_REPO}/issues",
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                      json={"title": title, "body": body, "labels": ["bot-report"]}, timeout=20)
    if r.status_code == 422: # label may not exist -> retry without
        r = requests.post(f"https://api.github.com/repos/{UPDATE_REPO}/issues",
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                          json={"title": title, "body": body}, timeout=20)
    if r.status_code >= 300:
        reasons = {401: "bad_token", 403: "no_permission", 404: "no_permission", 410: "issues_disabled"}
        return {"ok": False, "error": reasons.get(r.status_code, f"GitHub {r.status_code}: {r.text[:200]}")}
    return {"ok": True, "url": r.json().get("html_url")}

@app.route("/api/github/report/<id>", methods=["POST"])
def api_github_report(id):
    if not valid_id(id): abort(404)
    try:
        res = github_report(id)
        if res.get("ok"):
            a = bot_settings.load_app(); a["last_report"] = time.time(); bot_settings.save_app(a)
        return jsonify(res)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def auto_report_loop():
    """Every 6 hours, upload new errors of every account if the user enabled it."""
    while True:
        time.sleep(600)
        try:
            a = bot_settings.load_app()
            if not a.get("auto_report") or not a.get("github_token"): continue
            if time.time() - float(a.get("last_report") or 0) < 6 * 3600: continue
            since = float(a.get("last_report") or 0)
            for i in a["accounts"]: github_report(i, since)
            a["last_report"] = time.time(); bot_settings.save_app(a)
        except Exception:
            pass

# ---------------------------------------------------------------- tesseract (fast number OCR)

def _find_tesseract():
    import shutil
    app_path = bot_settings.load_app().get("tesseract_path", "")
    candidates = [app_path, shutil.which("tesseract") or "",
                  r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                  str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
                  "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract"]
    return next((c for c in candidates if c and Path(c).exists()), None)

@app.route("/api/tesseract", methods=["GET"])
def api_tesseract():
    import subprocess
    exe = _find_tesseract()
    version = None
    if exe:
        try:
            kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, **kw)
            version = (out.stdout or out.stderr).splitlines()[0].strip()
        except Exception:
            pass
    return jsonify({"found": bool(exe), "path": exe, "version": version, "platform": sys.platform})

@app.route("/api/tesseract/install", methods=["POST"])
def api_tesseract_install():
    """Open a console running the official Windows installer through winget (user sees progress / UAC)."""
    import subprocess
    if sys.platform != "win32":
        return jsonify({"ok": False, "error": "windows_only"})
    try:
        cmd = ('winget install -e --id UB-Mannheim.TesseractOCR --accept-package-agreements '
               '--accept-source-agreements & echo. & echo Done - you can close this window & pause')
        subprocess.Popen(["cmd", "/c", cmd], creationflags=subprocess.CREATE_NEW_CONSOLE)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---------------------------------------------------------------- updates

@app.route("/api/update/check", methods=["GET"])
def api_update_check():
    try:
        import updater
        return jsonify({"ok": True, **updater.check()})
    except Exception as e:
        return jsonify({"ok": False, "current": VERSION, "error": str(e)})

@app.route("/api/update/apply", methods=["POST"])
def api_update_apply():
    try:
        import updater
        return jsonify({"ok": True, **updater.apply()})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

# ---------------------------------------------------------------- endpoints used by the bot processes

@app.route("/current_time", methods=["GET"])
def handle_current_time():
    return {"current_time": time.time()}

@app.route("/instances/<id>/end_time", methods=["GET", "POST"])
def handle_end_time(id):
    instance = instances.get(id)
    if not instance: abort(404)
    if request.method == "POST":
        data = request.json.get("time", 0)
        instance.end_time = int(data) * 60 + time.time()
    return {"end_time": instance.end_time}

@app.route("/instances/<id>/running", methods=["GET"])
def handle_running(id):
    instance = instances.get(id)
    if not instance: abort(404)
    return {"running": instance.end_time == 0 or instance.end_time < time.time()}

@app.route("/instances/<id>/status", methods=["GET", "POST"])
def handle_status(id):
    instance = instances.get(id)
    if not instance: abort(404)
    if request.method == "POST":
        data = request.json
        instance.run_status = data.get("status", "")
    return {"status": instance.run_status}

@app.route("/instances/<id>/exclude", methods=["GET", "POST"])
def handle_exclude(id):
    if not valid_id(id): abort(404)
    s = bot_settings.load(id)
    if request.method == "POST":
        data = request.json or {}
        item = data.get("item", "")
        if item in s["tasks"]:
            s["tasks"][item] = data.get("action", "") == "remove"
            s = bot_settings.save(id, s)
    return {"exclusions": bot_settings.exclusions(s)}

def start_server(pipe, port, id=None, debug=False):
    global bot_pipe
    bot_pipe = pipe

    if not debug:
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')

    bot_settings.apply_app_settings()
    import threading
    threading.Thread(target=auto_report_loop, daemon=True).start()
    for i in ([id] if isinstance(id, str) else (id or [])): # accounts launched together with the GUI
        instances[i] = Instance(i)

    app.run(port=port, debug=debug, threaded=True)

if __name__ == "__main__":
    from multiprocessing import Pipe
    parent_conn, child_conn = Pipe()
    start_server(child_conn, port=1234, debug=True)
