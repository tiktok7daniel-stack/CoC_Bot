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
        return jsonify(bot_settings.save(id, request.json or {}))
    return jsonify(bot_settings.load(id))

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
    for i in ([id] if isinstance(id, str) else (id or [])): # accounts launched together with the GUI
        instances[i] = Instance(i)

    app.run(port=port, debug=debug, threaded=True)

if __name__ == "__main__":
    from multiprocessing import Pipe
    parent_conn, child_conn = Pipe()
    start_server(child_conn, port=1234, debug=True)
