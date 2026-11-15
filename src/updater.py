"""Self-update from GitHub for source installs (keeps configs.py, .venv and user data)."""
import sys, re, io, shutil, zipfile
from pathlib import Path

from version import VERSION, UPDATE_REPO, UPDATE_BRANCH

ROOT = Path(__file__).resolve().parent.parent
KEEP = {".venv", ".git", "debug", "src/configs.py", "scripts/start.sh", "src/cache.json"}

def _ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)

def _current_version():
    """Read the version from disk (the running program may be older than the files after an update)."""
    try:
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', (ROOT / "src" / "version.py").read_text(encoding="utf-8"))
        return m.group(1) if m else VERSION
    except OSError:
        return VERSION

def check():
    import requests, time
    # GitHub API first (not cached for minutes like raw files), raw file with a cache-buster as fallback
    text = ""
    try:
        r = requests.get(f"https://api.github.com/repos/{UPDATE_REPO}/contents/src/version.py",
                         params={"ref": UPDATE_BRANCH}, headers={"Accept": "application/vnd.github.raw"}, timeout=10)
        if r.status_code == 200: text = r.text
    except Exception:
        pass
    if "VERSION" not in text:
        r = requests.get(f"https://raw.githubusercontent.com/{UPDATE_REPO}/{UPDATE_BRANCH}/src/version.py",
                         params={"t": int(time.time())}, headers={"Cache-Control": "no-cache"}, timeout=10)
        r.raise_for_status()
        text = r.text
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', text)
    current = _current_version()
    latest = m.group(1) if m else current
    return {"current": current, "latest": latest, "available": _ver_tuple(latest) > _ver_tuple(current)}

def apply():
    if getattr(sys, "frozen", False):
        raise RuntimeError("Prebuilt app: download the new release instead")
    import requests
    import time
    url = f"https://codeload.github.com/{UPDATE_REPO}/zip/refs/heads/{UPDATE_BRANCH}"
    r = requests.get(url, params={"t": int(time.time())}, headers={"Cache-Control": "no-cache"}, timeout=120)
    r.raise_for_status()
    changed = 0
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for info in z.infolist():
            parts = info.filename.split("/", 1)
            if len(parts) < 2 or not parts[1] or info.is_dir(): continue
            rel = parts[1]
            if rel in KEEP or rel.split("/", 1)[0] in KEEP: continue
            if ".." in Path(rel).parts: continue # never write outside the bot folder
            dest = ROOT / rel
            data = z.read(info)
            if dest.exists() and dest.read_bytes() == data: continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".new")
            tmp.write_bytes(data)
            tmp.replace(dest)
            changed += 1
    return {"changed": changed, "version": _current_version()}

STARTUP_DIR = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
STARTUP_FILE = STARTUP_DIR / "CoC_Bot.bat"

def set_autostart(enabled):
    if sys.platform != "win32":
        raise RuntimeError("Only supported on Windows")
    if not enabled:
        STARTUP_FILE.unlink(missing_ok=True)
        return False
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists(): pyw = Path(sys.executable).with_name("pythonw.exe")
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    STARTUP_FILE.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\nstart "" "{pyw}" src\\main.py\r\n', encoding="utf-8")
    return True

def autostart_enabled():
    return sys.platform == "win32" and STARTUP_FILE.exists()
