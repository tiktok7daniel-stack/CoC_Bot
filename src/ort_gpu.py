"""
The eyes' neural networks (onnxruntime) on the graphics card (5.83).

The bot's onnxruntime runs on the processor only; the Clash Royale eyes then take 30-80 ms a look and the big model
answers a picture late. On Windows the DirectML build of onnxruntime runs the same models on ANY graphics card
(NVIDIA, AMD, Intel) with nothing else to install (no CUDA / cuDNN versions to match). It is put in its own folder
(~/.CoC_Bot/ort_dml, pip --target, like the CUDA torch of gpu_setup) so the program's own copy is never touched, checked
in a separate process, and used from the next start (activate() runs before anything imports onnxruntime).
"""
import os, subprocess, sys, threading
from pathlib import Path

TARGET = Path.home() / ".CoC_Bot" / "ort_dml"
READY = TARGET / "READY"
LOG = Path.home() / ".CoC_Bot" / "ort_dml_install.log"
_S = {"busy": False}


def activate():
    """Use the graphics-card onnxruntime if it is installed and checked (before anything imports onnxruntime)."""
    try:
        if os.name == "nt" and READY.exists() and str(TARGET) not in sys.path:
            sys.path.insert(0, str(TARGET))
            os.environ["PYTHONPATH"] = str(TARGET) + os.pathsep + os.environ.get("PYTHONPATH", "")
    except Exception:
        pass


def on_gpu():
    try:
        import onnxruntime as ort
        return any(p in ort.get_available_providers() for p in ("CUDAExecutionProvider", "DmlExecutionProvider"))
    except Exception:
        return False


def needed():
    return os.name == "nt" and not READY.exists() and not on_gpu()


def _py():
    """A real Python to run pip with (the app may be a packed .exe): the one gpu_setup uses."""
    try:
        import gpu_setup
        return gpu_setup._python()
    except Exception:
        return sys.executable


def _log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(msg.rstrip() + "\n")
    except OSError:
        pass


def _install(log=None):
    NW = 0x08000000 if os.name == "nt" else 0
    try:
        TARGET.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([_py(), "-m", "pip", "install", "--upgrade", "--no-deps", "--target", str(TARGET),
                            "onnxruntime-directml"], capture_output=True, text=True, timeout=1800, creationflags=NW)
        _log(r.stdout[-3000:] + r.stderr[-3000:])
        chk = subprocess.run([_py(), "-c", "import sys; sys.path.insert(0, sys.argv[1]); import onnxruntime as o; "
                              "print(','.join(o.get_available_providers()))", str(TARGET)],
                             capture_output=True, text=True, timeout=120, creationflags=NW)
        _log("providers: " + chk.stdout + chk.stderr[-500:])
        if "DmlExecutionProvider" in chk.stdout:
            READY.write_text("ok", encoding="utf-8")
            if log: log.info("Clash Royale: the eyes will run on the graphics card from the next start (DirectML)")
        elif log:
            log.info("Clash Royale: the graphics-card eyes could not be set up — they stay on the processor")
    except Exception as e:
        _log(f"failed: {e}")
    finally:
        _S["busy"] = False


def install_in_background(log=None):
    """Once, in the background (a few minutes, ~20 MB)."""
    if _S["busy"] or not needed(): return False
    _S["busy"] = True
    if log: log.info("Clash Royale: setting up the eyes on the graphics card (DirectML) in the background")
    threading.Thread(target=_install, args=(log,), daemon=True, name="ort-dml").start()
    return True


def session_options(ort, providers):
    """DirectML wants sequential runs and no memory patterns."""
    so = ort.SessionOptions()
    if "DmlExecutionProvider" in providers:
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return so
