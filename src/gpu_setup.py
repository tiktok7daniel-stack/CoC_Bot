"""
NVIDIA graphics card for the text reader (easyocr / torch).

On the processor a reading takes ~0.5-1.5 s; on an NVIDIA card ~0.05-0.15 s (10x faster). The normal torch package
has no CUDA in it, so with an NVIDIA card the bot installs the CUDA build of torch (~2.5 GB) once, while the program
is closed (restart_helper, before it opens the program again) — files of a running torch can't be replaced on Windows.

~/.CoC_Bot/gpu.json         what was found (card, driver, torch, CUDA on/off), refreshed by status(refresh=True)
~/.CoC_Bot/gpu_install.flag install asked: done at the next restart
~/.CoC_Bot/gpu_install.log  pip's output of the last install
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
STATE = HOME / "gpu.json"
FLAG = HOME / "gpu_install.flag"
LOG = HOME / "gpu_install.log"
NW = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW


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
        line = r.stdout.strip().splitlines()[0]
        name, driver, mem = [x.strip() for x in line.split(",")[:3]]
        return {"name": name, "driver": driver, "memory_mb": int(float(mem))}
    except Exception:
        return None


def _python(py=None):
    py = py or sys.executable
    return py.replace("pythonw.exe", "python.exe")


def torch_info(py=None):
    """(torch version, CUDA usable) checked in a separate python (importing torch here would be slow)."""
    try:
        r = subprocess.run([_python(py), "-c", "import torch,json;print(json.dumps([torch.__version__, torch.cuda.is_available(), "
                            "torch.version.cuda]))"], capture_output=True, text=True, timeout=120, creationflags=NW)
        v, cuda, cv = json.loads(r.stdout.strip().splitlines()[-1])
        return v, bool(cuda), cv
    except Exception:
        return None, False, None


def status(refresh=False):
    try: st = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    if refresh or not st or time.time() - st.get("t", 0) > 6 * 3600:
        card = nvidia()
        v, cuda, cv = torch_info() if card else (None, False, None)
        st = {"t": time.time(), "card": card, "torch": v, "cuda": cuda, "cuda_version": cv}
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(st), encoding="utf-8")
        except OSError:
            pass
    st["pending"] = FLAG.exists()
    try: st["log"] = LOG.read_text(encoding="utf-8", errors="ignore")[-1500:]
    except OSError: st["log"] = ""
    return st


def request_install():
    HOME.mkdir(parents=True, exist_ok=True)
    FLAG.write_text(str(time.time()), encoding="utf-8")


def _index_url(driver):
    """CUDA 12.6 needs driver 525+ (12.x minor-version compatibility); older drivers: CUDA 11.8."""
    try: major = int(str(driver).split(".")[0])
    except ValueError: major = 0
    return "https://download.pytorch.org/whl/cu126" if major >= 525 else "https://download.pytorch.org/whl/cu118"


def install(py=None):
    """Run while the program is closed: CUDA torch from the PyTorch index. True when CUDA works afterwards."""
    if not FLAG.exists(): return False
    try: FLAG.unlink()
    except OSError: pass
    card = nvidia()
    if not card:
        LOG.write_text("No NVIDIA card found (nvidia-smi), nothing installed.\n", encoding="utf-8")
        return False
    url = _index_url(card["driver"])
    with open(LOG, "w", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} card {card['name']} driver {card['driver']} -> {url}\n")
        f.flush()
        r = subprocess.run([_python(py), "-m", "pip", "install", "--upgrade", "--force-reinstall", "--no-deps",
                            "torch", "torchvision", "--index-url", url], stdout=f, stderr=subprocess.STDOUT, creationflags=NW)
        # torch's own dependencies (from the normal index) in case the new torch needs newer ones
        subprocess.run([_python(py), "-m", "pip", "install", "torch", "torchvision", "--index-url", url,
                        "--extra-index-url", "https://pypi.org/simple"], stdout=f, stderr=subprocess.STDOUT, creationflags=NW)
        v, cuda, cv = torch_info(py)
        f.write(f"\nresult: pip exit {r.returncode}, torch {v}, CUDA {'ON' if cuda else 'off'} ({cv})\n")
    status(refresh=True)
    return cuda
