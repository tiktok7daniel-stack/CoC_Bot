"""
Start-up checks for the setup screen: which emulator copies exist, which bot account is linked
to which copy, and for each account whether the emulator is running, ADB is connected, the
resolution is 1920x1080 and the game is open. Also the actions behind the screen's buttons.
Light-weight on purpose (runs in the GUI server process, no utils import).
"""
import os, re, sys, time, shutil, subprocess
from pathlib import Path

GAME = "com.supercell.clashofclans"
KW = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

LD_DIRS = [r"C:\LDPlayer\LDPlayer9", r"D:\LDPlayer\LDPlayer9", r"E:\LDPlayer\LDPlayer9",
           r"C:\LDPlayer\LDPlayer4.0", r"D:\LDPlayer\LDPlayer4.0",
           r"C:\Program Files\LDPlayer\LDPlayer9", r"C:\Program Files\ldplayer9box", r"D:\LDPlayer", r"C:\LDPlayer"]

def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **KW)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"error: {e}"

# ---------------------------------------------------------------- LDPlayer

def ld_console(app):
    custom = str(app.get("ldplayer_path", "") or "").strip().strip('"')
    cands = []
    if custom:
        p = Path(custom)
        cands += ([p] if p.suffix.lower() == ".exe" else []) + [p / "ldconsole.exe", p / "dnconsole.exe", p.parent / "ldconsole.exe"]
    for d in LD_DIRS: cands += [Path(d) / "ldconsole.exe", Path(d) / "dnconsole.exe"]
    for c in cands:
        try:
            if c.is_file(): return str(c)
        except OSError:
            continue
    return None

def parse_list2(text):
    """ldconsole list2 -> [{index, title, running, pid, width, height}]"""
    out = []
    for line in text.splitlines():
        c = line.strip().split(",")
        if len(c) < 6 or not c[0].strip().isdigit(): continue
        num = lambda i: int(c[i]) if len(c) > i and c[i].strip().lstrip("-").isdigit() else None
        out.append({"index": int(c[0]), "title": c[1], "running": c[4].strip() == "1", "pid": num(5),
                    "width": num(7), "height": num(8), "dpi": num(9)})
    return out

def ld_instances(console):
    return parse_list2(_run([console, "list2"])) if console else []

def link_for(account, copies, links):
    """Which emulator copy an account uses: chosen link, else same name, else the only copy."""
    if str(links.get(account, "")) != "":
        return next((c for c in copies if str(c["index"]) == str(links[account])), None)
    same = [c for c in copies if c["title"] == account]
    if same: return same[0]
    return copies[0] if len(copies) == 1 else None

# ---------------------------------------------------------------- BlueStacks

def bs_conf():
    for c in (r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf", "/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf"):
        if Path(c).exists(): return Path(c)
    return None

def bs_instances():
    conf = bs_conf()
    if conf is None: return []
    text = conf.read_text(errors="ignore")
    out = []
    for m in re.finditer(r'^bst\.instance\.([^.]+)\.display_name="?(.*?)"?$', text, re.M):
        inst = m.group(1)
        get = lambda k: (re.search(rf'^bst\.instance\.{re.escape(inst)}\.{k}="?(.*?)"?$', text, re.M) or [None, None])[1]
        w, h = get("fb_width"), get("fb_height")
        out.append({"index": inst, "title": m.group(2), "port": get("adb_port"),
                    "width": int(w) if w and w.isdigit() else None, "height": int(h) if h and h.isdigit() else None})
    return out

def bs_dir():
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BlueStacks_nxt"

# ---------------------------------------------------------------- ADB

def adb_exe(app, console=None):
    emu = app.get("emulator")
    if emu == "ldplayer" and console:
        p = Path(console).parent / "adb.exe"
        if p.exists(): return str(p)
    if emu == "bluestacks" and sys.platform == "win32":
        p = bs_dir() / "HD-Adb.exe"
        if p.exists(): return str(p)
    return shutil.which("adb")

def adb_state(adb, addr):
    if not adb or not addr: return None
    _run([adb, "connect", addr], timeout=8)
    out = _run([adb, "-s", addr, "get-state"], timeout=8).strip()
    return out if out in ("device", "offline", "unauthorized") else None

def shell(adb, addr, cmd, timeout=10):
    return _run([adb, "-s", addr, "shell", cmd], timeout=timeout)

def game_open(adb, addr):
    return bool(shell(adb, addr, f"pidof {GAME}").strip().split()) if adb else False

def wm_size(adb, addr):
    out = shell(adb, addr, "wm size")
    sizes = re.findall(r"(\d+)x(\d+)", out)
    return tuple(map(int, sizes[-1])) if sizes else None # override size is listed last

def target(app):
    """The display size / DPI chosen on the setup screen (default 1920x1080 240 DPI)."""
    return int(app.get("display_w", 1920)), int(app.get("display_h", 1080)), int(app.get("display_dpi", 240))

def good_res(app, w, h, dpi):
    tw, th, td = target(app)
    return w is not None and h is not None and {w, h} == {tw, th} and dpi == td

def wm_density(adb, addr):
    d = re.findall(r"(\d+)", shell(adb, addr, "wm density"))
    return int(d[-1]) if d else None

# ---------------------------------------------------------------- status of everything

def copies(app):
    emu = app.get("emulator")
    if emu == "ldplayer":
        con = ld_console(app)
        return con, ld_instances(con)
    if emu == "bluestacks":
        return None, bs_instances()
    return None, []

def address(app, copy):
    if copy is None: return None
    if app.get("emulator") == "ldplayer": return f"127.0.0.1:{5555 + 2 * int(copy['index'])}"
    if app.get("emulator") == "bluestacks" and copy.get("port"): return f"127.0.0.1:{copy['port']}"
    return None

def status(app, running_accounts=()):
    emu = app.get("emulator")
    con, cps = copies(app)
    adb = adb_exe(app, con)
    links = app.get("emulator_links", {}) or {}
    res = {"emulator": emu, "found": bool(con) if emu == "ldplayer" else bool(cps) if emu == "bluestacks" else True,
           "console": con, "adb": adb, "copies": [{k: c.get(k) for k in ("index", "title", "running")} for c in cps],
           "accounts": [], "platform": sys.platform, "target": list(target(app))}
    for acc in app.get("accounts", []):
        c = link_for(acc, cps, links) if emu in ("ldplayer", "bluestacks") else None
        a = {"id": acc, "copy": c["title"] if c else None, "copy_index": c["index"] if c else None,
             "address": address(app, c), "bot": acc in running_accounts}
        addr = a["address"]
        state = adb_state(adb, addr) if addr else None
        a["adb"] = state
        if emu == "ldplayer": a["emu_running"] = bool(c and c["running"])
        else: a["emu_running"] = state == "device"
        if state == "device":
            a["boot"] = shell(adb, addr, "getprop sys.boot_completed").strip() == "1"
            size, dpi = wm_size(adb, addr), wm_density(adb, addr)
            a["resolution"] = f"{size[0]}x{size[1]} · {dpi} DPI" if size else None
            a["res_ok"] = bool(size and good_res(app, *size, dpi))
            a["game"] = game_open(adb, addr)
        else:
            a["boot"] = False
            a["resolution"] = f"{c['width']}x{c['height']} · {c.get('dpi')} DPI" if c and c.get("width") else None
            a["res_ok"] = bool(good_res(app, c.get("width"), c.get("height"), c.get("dpi"))) if c and c.get("width") and c.get("dpi") else None
            a["game"] = False
        a["progress"] = PROGRESS.get(acc)
        res["accounts"].append(a)
    return res

# ---------------------------------------------------------------- actions

def _account_copy(app, acc):
    con, cps = copies(app)
    return con, link_for(acc, cps, app.get("emulator_links", {}) or {})

def launch(app, acc):
    emu = app.get("emulator")
    con, c = _account_copy(app, acc)
    if c is None: return "no_copy"
    if emu == "ldplayer":
        _run([con, "launch", "--index", str(c["index"])], timeout=60)
        return "ok"
    if emu == "bluestacks":
        player = bs_dir() / "HD-Player.exe"
        if not player.exists(): return "no_emulator"
        subprocess.Popen([str(player), "--instance", c["index"]], **KW)
        return "ok"
    return "manual"

def fix_resolution(app, acc):
    """LDPlayer: change the copy's size + DPI (it is closed, changed and opened again).
    Other emulators: change them live with wm size / wm density."""
    tw, th, td = target(app)
    con, c = _account_copy(app, acc)
    if app.get("emulator") != "ldplayer":
        addr, adb = address(app, c) if c else None, adb_exe(app, con)
        if app.get("emulator") == "mumu" and not addr: addr = "127.0.0.1:16384"
        if not addr or adb_state(adb, addr) != "device": return "no_adb"
        shell(adb, addr, f"wm size {tw}x{th}")
        shell(adb, addr, f"wm density {td}")
        return "ok"
    if c is None: return "no_copy"
    idx = str(c["index"])
    if c["running"]:
        _run([con, "quit", "--index", idx], timeout=60)
        for _ in range(30):
            time.sleep(1)
            if not any(x["index"] == c["index"] and x["running"] for x in ld_instances(con)): break
    _run([con, "modify", "--index", idx, "--resolution", f"{tw},{th},{td}"], timeout=60)
    _run([con, "launch", "--index", idx], timeout=60)
    return "ok"

# ---------------------------------------------------------------- one button: do everything

PROGRESS = {} # account -> text key shown on the setup screen while auto setup runs

def auto_setup(app, acc):
    """Size + DPI, start the emulator, wait until it is connected, open the game. Runs in a thread."""
    import threading
    if PROGRESS.get(acc) not in (None, "done", "failed"): return "busy"
    def work():
        try:
            con, c = _account_copy(app, acc)
            if app.get("emulator") in ("ldplayer", "bluestacks") and c is None:
                PROGRESS[acc] = "failed_link"; return
            addr, adb = address(app, c) if c else "127.0.0.1:16384", adb_exe(app, con)
            tw, th, td = target(app)
            if app.get("emulator") == "ldplayer":
                fresh = {x["index"]: x for x in ld_instances(con)}.get(c["index"], c)
                if not good_res(app, fresh.get("width"), fresh.get("height"), fresh.get("dpi")):
                    PROGRESS[acc] = "p_res"; fix_resolution(app, acc)
                elif not fresh["running"]:
                    PROGRESS[acc] = "p_launch"; launch(app, acc)
            elif adb_state(adb, addr) != "device":
                PROGRESS[acc] = "p_launch"; launch(app, acc)
            PROGRESS[acc] = "p_wait"
            for _ in range(90): # up to ~3 minutes for the emulator to boot
                if adb_state(adb, addr) == "device" and shell(adb, addr, "getprop sys.boot_completed").strip() == "1": break
                time.sleep(2)
            else:
                PROGRESS[acc] = "failed_adb"; return
            size, dpi = wm_size(adb, addr), wm_density(adb, addr)
            if not (size and good_res(app, *size, dpi)):
                PROGRESS[acc] = "p_res"
                shell(adb, addr, f"wm size {tw}x{th}"); shell(adb, addr, f"wm density {td}")
            if not game_open(adb, addr):
                PROGRESS[acc] = "p_game"; open_game(app, acc)
                for _ in range(30):
                    if game_open(adb, addr): break
                    time.sleep(2)
            PROGRESS[acc] = "done"
        except Exception:
            PROGRESS[acc] = "failed"
    PROGRESS[acc] = "p_start"
    threading.Thread(target=work, daemon=True).start()
    return "ok"

def open_game(app, acc):
    con, c = _account_copy(app, acc)
    addr, adb = address(app, c), adb_exe(app, con)
    if not addr or adb_state(adb, addr) != "device": return "no_adb"
    shell(adb, addr, f"monkey -p {GAME} -c android.intent.category.LAUNCHER 1")
    return "ok"
