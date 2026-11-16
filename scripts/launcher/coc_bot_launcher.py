"""
CoC_Bot.exe - one double-click to install, update and start the bot.

Put CoC_Bot.exe anywhere (an empty folder for a fresh install, or the bot folder itself):
 1. first time: downloads the bot from GitHub into this folder
 2. every start: compares the version on GitHub with the local one and updates the files
    (settings, logs, .venv and configs are never touched)
 3. makes sure Python's virtual environment exists with every library (incl. the new interface)
 4. starts the bot window (python src/main.py --gui) and closes itself
Only the Python standard library is used, so the exe stays small.
"""
import io, os, re, shutil, subprocess, sys, time, urllib.request, zipfile
from pathlib import Path

REPO = "tiktok7daniel-stack/CoC_Bot"
BRANCH = "ccr-d344ab20-onpy71"
KEEP = {".venv", ".git", "debug", "src/configs.py", "scripts/start.sh", "src/cache.json"}
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def home():
    """Folder of the exe (or of this script while testing)."""
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    # running from scripts/launcher inside a checkout: the bot is two levels up
    if not (base / "src" / "main.py").exists() and (base.parent.parent / "src" / "main.py").exists():
        return base.parent.parent
    return base


def say(msg):
    print(msg, flush=True)


def http(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "CoC-Bot-Launcher", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local_version(root):
    try:
        m = re.search(r'VERSION\s*=\s*"([^"]+)"', (root / "src" / "version.py").read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def remote_version():
    raw = http(f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/src/version.py?t={int(time.time())}", 20).decode("utf-8")
    m = re.search(r'VERSION\s*=\s*"([^"]+)"', raw)
    return m.group(1) if m else ""


def download_and_extract(root):
    say("Downloading the latest version from GitHub ...")
    data = http(f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}?t={int(time.time())}", 300)
    changed = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            parts = info.filename.split("/", 1)
            if len(parts) < 2 or not parts[1] or info.is_dir(): continue
            rel = parts[1]
            if rel in KEEP or rel.split("/", 1)[0] in KEEP: continue
            if ".." in Path(rel).parts: continue
            dest = root / rel
            content = z.read(info)
            if dest.exists() and dest.read_bytes() == content: continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".new")
            tmp.write_bytes(content)
            try:
                tmp.replace(dest)
            except PermissionError: # a file in use (e.g. this exe itself): keep the old one
                tmp.unlink(missing_ok=True)
                continue
            changed += 1
    say(f"Updated {changed} file(s).")


def find_python():
    """A Python 3.11+ to create the virtual environment with."""
    for cmd in (["py", "-3.12"], ["py", "-3.11"], ["py", "-3"], ["python"], ["python3"]):
        try:
            out = subprocess.run(cmd + ["-c", "import sys; print(sys.version_info[:2] >= (3, 11))"],
                                 capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
            if out.stdout.strip() == "True": return cmd
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def venv_python(root, windowless=False):
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / ("pythonw.exe" if windowless else "python.exe")
    return root / ".venv" / "bin" / "python"


def ensure_env(root):
    py = venv_python(root)
    if not py.exists():
        base = find_python()
        if base is None:
            say("Python 3.11 or newer is needed: install it from https://www.python.org/downloads/ (tick 'Add to PATH') and run again.")
            input("Press Enter to close ...")
            sys.exit(1)
        say("Creating the Python environment (first time only) ...")
        subprocess.run(base + ["-m", "venv", str(root / ".venv")], check=True)
    marker = root / ".venv" / ".requirements_done"
    req = root / "src" / "requirements.txt"
    stamp = str(req.stat().st_mtime) if req.exists() else ""
    if not marker.exists() or marker.read_text(errors="ignore") != stamp:
        say("Installing / updating the libraries (a few minutes the first time) ...")
        subprocess.run([str(py), "-m", "pip", "install", "-q", "--upgrade", "pip"])
        r = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r", str(req)])
        if r.returncode == 0: marker.write_text(stamp)
    cfg = root / "src" / "configs.py"
    if not cfg.exists() and (root / "src" / "configs.template.py").exists():
        shutil.copyfile(root / "src" / "configs.template.py", cfg)


def main():
    root = home()
    say(f"CoC Bot - {root}")
    try:
        if not (root / "src" / "main.py").exists():
            download_and_extract(root)
        else:
            mine, latest = local_version(root), remote_version()
            say(f"Version here: {mine or '?'}   on GitHub: {latest or '?'}")
            if latest and latest != mine: download_and_extract(root)
    except Exception as e: # offline / GitHub down: start what we have
        say(f"Update check skipped ({e}).")
        if not (root / "src" / "main.py").exists():
            input("The bot could not be downloaded. Check the internet and press Enter ...")
            sys.exit(1)
    ensure_env(root)
    py = venv_python(root, windowless=True)
    if not py.exists(): py = venv_python(root)
    say("Starting the bot ...")
    subprocess.Popen([str(py), str(root / "src" / "main.py"), "--gui"], cwd=str(root),
                     creationflags=NO_WINDOW if sys.platform == "win32" else 0)
    time.sleep(1.5)


if __name__ == "__main__":
    main()
