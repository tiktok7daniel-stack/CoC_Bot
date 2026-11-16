"""
Restart Clash Farmer after an update: wait until the old program has fully closed, then start it again
(windowless, detached). Started by the GUI server: restart_helper.py <old main pid> <bot folder> <python>
"""
import os, subprocess, sys, time


def main():
    pid, root, py = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    try:
        import psutil
        deadline = time.time() + 90
        while time.time() < deadline and psutil.pid_exists(pid):
            time.sleep(0.3)
    except ImportError:
        time.sleep(6)
    time.sleep(1.0)     # let the ports / files be released
    # an update may need new libraries (same check as the launcher: requirements.txt changed)
    try:
        req = os.path.join(root, "src", "requirements.txt")
        marker = os.path.join(root, ".venv", ".requirements_done")
        stamp = str(os.stat(req).st_mtime)
        old = open(marker, encoding="utf-8", errors="ignore").read() if os.path.exists(marker) else None
        if old is not None and old != stamp:
            pyc = py.replace("pythonw.exe", "python.exe")
            nw = 0x08000000 if sys.platform == "win32" else 0
            r = subprocess.run([pyc, "-m", "pip", "install", "-q", "-r", req], creationflags=nw)
            if r.returncode == 0: open(marker, "w", encoding="utf-8").write(stamp)
    except Exception:
        pass
    # NVIDIA card asked for: the CUDA build of torch, now while nothing uses torch (a few minutes, once)
    try:
        sys.path.insert(0, os.path.join(root, "src"))
        import gpu_setup
        gpu_setup.install(py)
    except Exception:
        pass
    flags = 0
    if sys.platform == "win32": flags = 0x08000000 | 0x00000008     # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen([py, os.path.join(root, "src", "main.py"), "--gui"], cwd=root, creationflags=flags,
                     close_fds=True, start_new_session=sys.platform != "win32")


if __name__ == "__main__":
    main()
