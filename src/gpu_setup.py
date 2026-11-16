"""
NVIDIA graphics card for the text reader (easyocr / torch).

On the processor a reading takes ~0.5-1.5 s; on an NVIDIA card ~0.05-0.15 s (10x faster). The normal torch package
has no CUDA in it, so with an NVIDIA card the bot downloads the CUDA build of torch (~2.5 GB) once.

It is installed WHILE THE PROGRAM IS OPEN, into its own folder (~/.CoC_Bot/cuda_torch), never over the files the
program is using: nothing closes, nothing can break. When it is complete and checked (torch sees the card), the
folder is marked ready and every part of the program started from then on loads torch from it (activate(), called
first thing in main.py). Delete the folder to go back to the processor.

~/.CoC_Bot/gpu.json          what was found (card, driver, torch, CUDA on/off)
~/.CoC_Bot/gpu_install.json  the running / last install (pid, start, result)
~/.CoC_Bot/gpu_install.log   pip's output
"""
import json, os, shutil, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
STATE = HOME / "gpu.json"
JOB = HOME / "gpu_install.json"
LOG = HOME / "gpu_install.log"
TARGET = HOME / "cuda_torch"
READY = TARGET / ".ready"
TMP = HOME / "cuda_torch.part"
OLD_FLAG = HOME / "gpu_install.flag"            # from 5.15.0 (installed during a restart): no longer used
EXPECTED_MB = 4500                              # unpacked size, for the progress bar
NW = 0x08000000 if sys.platform == "win32" else 0


def activate():
    """Use the CUDA torch if it is installed and checked (must run before anything imports torch)."""
    try:
        if READY.exists() and str(TARGET) not in sys.path:
            sys.path.insert(0, str(TARGET))
            os.environ["PYTHONPATH"] = str(TARGET) + os.pathsep + os.environ.get("PYTHONPATH", "")   # child processes too
    except Exception:
        pass


def _smi():
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform == "win32":
        for p in (r"C:\Windows\System32\nvidia-smi.exe", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
            if os.path.exists(p): exe = p; break
    return exe


def nvidia():
    """{"name", "driver", "memory_mb"} of the first NVIDIA card, or None."""
    exe = _smi()
    if not exe: return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, creationflags=NW)
        name, driver, mem = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")[:3]]
        return {"name": name, "driver": driver, "memory_mb": int(float(mem))}
    except Exception:
        return None


def _python(py=None):
    return (py or sys.executable).replace("pythonw.exe", "python.exe")


def torch_info(path=None, py=None):
    """(torch version, CUDA usable, CUDA version) checked in a separate python (with `path` first, if given)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(path) if path else ""
    try:
        r = subprocess.run([_python(py), "-c", "import torch,json;print(json.dumps([torch.__version__, torch.cuda.is_available(), "
                            "torch.version.cuda]))"], capture_output=True, text=True, timeout=180, creationflags=NW, env=env)
        v, cuda, cv = json.loads(r.stdout.strip().splitlines()[-1])
        return v, bool(cuda), cv
    except Exception:
        return None, False, None


def _job():
    try: return json.loads(JOB.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _alive(pid):
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:
        return False


def _size_mb(p):
    total = 0
    for dp, _, fs in os.walk(p):
        for f in fs:
            try: total += os.path.getsize(os.path.join(dp, f))
            except OSError: pass
    return total // (1024 * 1024)


def installing():
    j = _job()
    return bool(j.get("running")) and _alive(j.get("pid", 0))


def status(refresh=False):
    try: st = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    if refresh or not st or time.time() - st.get("t", 0) > 6 * 3600:
        card = nvidia()
        v, cuda, cv = torch_info(TARGET if READY.exists() else None) if card else (None, False, None)
        st = {"t": time.time(), "card": card, "torch": v, "cuda": cuda, "cuda_version": cv}
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(st), encoding="utf-8")
        except OSError:
            pass
    try: OLD_FLAG.unlink()
    except OSError: pass
    j = _job()
    if j.get("running") and not _alive(j.get("pid", 0)):      # the program was closed while it downloaded
        threading.Thread(target=_finalize, args=(None,), daemon=True).start()
    st["installing"] = installing()
    st["ready"] = READY.exists()
    st["pending"] = False
    st["result"] = j.get("result", "")
    if st["installing"]:
        mb = _size_mb(TMP) if TMP.exists() else 0
        st["progress"] = {"mb": mb, "of_mb": EXPECTED_MB, "pct": min(99, int(mb * 100 / EXPECTED_MB)),
                          "minutes": int((time.time() - j.get("start", time.time())) / 60)}
    try: st["log"] = LOG.read_text(encoding="utf-8", errors="ignore")[-1500:]
    except OSError: st["log"] = ""
    return st


def _index_url(driver):
    """CUDA 12.6 needs driver 525+ (12.x minor-version compatibility); older drivers: CUDA 11.8."""
    try: major = int(str(driver).split(".")[0])
    except ValueError: major = 0
    return "https://download.pytorch.org/whl/cu126" if major >= 525 else "https://download.pytorch.org/whl/cu118"


def start_install(py=None):
    """Start the download in the background (the program stays open). -> (ok, error)."""
    if installing(): return True, ""
    card = nvidia()
    if not card: return False, "no_nvidia"
    HOME.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(TMP, ignore_errors=True)
    url = _index_url(card["driver"])
    log = open(LOG, "w", encoding="utf-8")
    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {card['name']} (driver {card['driver']}) -> {url}\n")
    log.flush()
    proc = subprocess.Popen([_python(py), "-m", "pip", "install", "--no-deps", "--upgrade", "--target", str(TMP),
                             "--progress-bar", "off", "torch", "torchvision", "--index-url", url],
                            stdout=log, stderr=subprocess.STDOUT, creationflags=NW)
    JOB.write_text(json.dumps({"running": True, "pid": proc.pid, "start": time.time(), "url": url}), encoding="utf-8")

    def finish():
        code = proc.wait()
        log.close()
        _finalize(code, py)

    threading.Thread(target=finish, daemon=True, name="gpu-install").start()
    return True, ""


_FIN = threading.Lock()


def _finalize(code, py=None):
    """pip finished (exit code, or None = unknown because the program was closed meanwhile): check and switch on."""
    with _FIN:
        if not _job().get("running"): return
        result = "failed"
        if code in (0, None) and TMP.exists():
            v, cuda, cv = torch_info(TMP, py)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"\ncheck: torch {v}, CUDA {'ON' if cuda else 'off'} ({cv})\n")
            if cuda:
                shutil.rmtree(TARGET, ignore_errors=True)
                try:
                    TMP.rename(TARGET)
                    READY.write_text(json.dumps({"t": time.time(), "torch": v, "cuda": cv}), encoding="utf-8")
                    result = "ready"
                except OSError as e:
                    result = f"failed: {e}"
            else:
                result = "no_cuda"
        if result != "ready": shutil.rmtree(TMP, ignore_errors=True)
        JOB.write_text(json.dumps({"running": False, "end": time.time(), "result": result, "code": code}), encoding="utf-8")
        try: status(refresh=True)
        except Exception: pass


def remove():
    """Back to the processor."""
    shutil.rmtree(TARGET, ignore_errors=True)
    status(refresh=True)
