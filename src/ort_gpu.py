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


def healthy(folder):
    """6.9.13: does the onnxruntime in `folder` import cleanly? Checked in a separate Python (nothing loaded here),
    remembered until the folder's onnxruntime changes. The user's PC had a BROKEN one in the app's folder ("No module
    named onnxruntime.capi.onnxruntime_inference_collection": two versions mixed) — and every part of the bot that
    uses onnxruntime (the eyes, PaddleOCR) loaded it from there."""
    import json, subprocess
    folder = Path(folder)
    init = folder / "onnxruntime" / "__init__.py"
    if not init.exists(): return False
    key = init.stat().st_mtime
    mark = folder / "HEALTH"
    try:
        h = json.loads(mark.read_text(encoding="utf-8"))
        if h.get("mtime") == key: return bool(h.get("ok"))
    except (OSError, ValueError):
        pass
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    code = "import sys; sys.path.insert(0, sys.argv[1]); import onnxruntime as o; o.InferenceSession; print(o.__file__)"
    try:
        r = subprocess.run([_py(), "-c", code, str(folder)], capture_output=True, text=True, timeout=120, env=env,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        ok = r.returncode == 0 and str(folder) in r.stdout
        _log(f"health of {folder}: {'ok' if ok else 'BROKEN'} {(r.stdout + r.stderr)[-300:]}")
    except Exception as e:
        ok = False
        _log(f"health of {folder}: check failed {e}")
    try: mark.write_text(json.dumps({"mtime": key, "ok": ok}), encoding="utf-8")
    except OSError: pass
    return ok


def clean_folder(folder):
    """Remove every onnxruntime copy from the app's folder (a clean install follows) — nothing else of the PC."""
    import shutil
    folder = Path(folder)
    if not folder.exists(): return
    for p in list(folder.iterdir()):
        if p.name.lower().startswith(("onnxruntime", "onnxruntime_")) or p.name in ("READY", "HEALTH"):
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
            except OSError:
                pass


def sanitize():
    """6.9.14: every process of the bot runs this FIRST (the app, the bot, the trainings): an app-folder onnxruntime it
    inherited (PYTHONPATH from a parent started before a fix) is checked; a broken one is taken off the path — this
    process and every child — and its onnxruntime removed (installed clean again later). -> folders taken off."""
    folders = [TARGET]
    try:
        import trt_engine
        folders.insert(0, trt_engine.TARGET)
    except Exception:
        pass
    off = []
    pp = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    for f in folders:
        fs = str(f)
        if (fs in sys.path or fs in pp) and not healthy(f):
            sys.path[:] = [p for p in sys.path if p != fs]
            pp = [p for p in pp if p != fs]
            clean_folder(f)
            off.append(fs)
            _log(f"{fs}: a broken onnxruntime — taken off the path and removed (installed clean again later)")
    if off:
        if pp: os.environ["PYTHONPATH"] = os.pathsep.join(pp)
        else: os.environ.pop("PYTHONPATH", None)
    return off


def activate():
    """Use the graphics-card onnxruntime if it is installed and checked (before anything imports onnxruntime).
    6.6: NVIDIA TensorRT / CUDA first (trt_engine) when it was set up and checked on this PC, else DirectML."""
    try: sanitize()
    except Exception: pass
    try:
        import trt_engine
        if trt_engine.activate(): return
    except Exception:
        pass
    try:
        if os.name == "nt" and not READY.exists():
            # 6.9.15: no graphics-card onnxruntime at all (TensorRT broken / not set up): the DirectML one (~25 MB) is set up
            # at once in the background — the eyes on the processor took 1.2 s a look and drew no boxes
            install_in_background()
        if os.name == "nt" and READY.exists() and str(TARGET) not in sys.path:
            if not healthy(TARGET):                 # 6.9.13: a broken copy is never used; installed clean again
                _log("DirectML onnxruntime is broken — not used; it is installed clean again in the background")
                clean_folder(TARGET)
                install_in_background()
                return
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
    try:
        import trt_engine
        if trt_engine.active(): return False              # TensorRT / CUDA already runs the eyes
    except Exception:
        pass
    # 6.9.15: always kept as the backup of TensorRT (its folder broke once and nothing was left on the card);
    # not decided by importing onnxruntime here (that would load it before the GPU copy is chosen)
    return os.name == "nt" and not READY.exists()


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
        clean_folder(TARGET)                          # 6.9.13: never on top of an older copy
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


def providers():
    """Every provider this onnxruntime has, fastest first."""
    import onnxruntime as ort
    av = ort.get_available_providers()
    return [p for p in ("TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider") if p in av] + \
        ["CPUExecutionProvider"]


def session_options(ort, providers):
    """DirectML wants sequential runs and no memory patterns."""
    so = ort.SessionOptions()
    if "DmlExecutionProvider" in providers:
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return so
