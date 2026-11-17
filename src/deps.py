"""
Libraries the program needs that an update can't bring by itself (source installs: an update only replaces the
files). Missing ones are installed in the background with the program's own Python, once per start.
"""
import importlib, subprocess, sys, threading

_S = {"running": set(), "done": set()}


def ensure(module, pip_names, on_done=None):
    """module missing -> `pip install pip_names` in the background (no window). -> True when it is there already."""
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        pass
    if getattr(sys, "frozen", False) or module in _S["running"] or module in _S["done"]: return False
    _S["running"].add(module)
    py = sys.executable
    if py.lower().endswith("pythonw.exe"): py = py[:-len("pythonw.exe")] + "python.exe"

    def work():
        try:
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            r = subprocess.run([py, "-m", "pip", "install", "-q", *pip_names], capture_output=True, timeout=1800, **kw)
            importlib.invalidate_caches()
            ok = r.returncode == 0
            try:
                from utils import logger
                if ok: logger.info(f"Installed {', '.join(pip_names)}")
                else: logger.error(f"Could not install {', '.join(pip_names)}: " + (r.stderr or b"").decode("utf-8", "ignore")[-300:])
            except Exception:
                pass
            if ok and on_done: on_done()
        except Exception:
            pass
        finally:
            _S["running"].discard(module)
            _S["done"].add(module)
    threading.Thread(target=work, daemon=True, name=f"install-{module}").start()
    return False
