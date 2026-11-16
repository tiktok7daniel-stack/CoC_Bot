"""
NVIDIA graphics card for the text reader (easyocr / torch).

On the processor a reading takes ~0.5-1.5 s; on an NVIDIA card ~0.05-0.15 s (10x faster). The normal torch package
has no CUDA in it, so with an NVIDIA card the bot downloads the CUDA build of torch (~2.5 GB) once.

How it is installed (the program stays open, nothing it uses is touched):
 1. find    which torch / torchvision files fit this PC (pip --dry-run --report, nothing downloaded)
 2. download them ourselves into ~/.CoC_Bot/cuda_dl: real progress, continues where it stopped
 3. install them into their own folder ~/.CoC_Bot/cuda_torch (pip --target, from the downloaded files)
 4. check   that torch from that folder sees the card; only then it is marked ready
From the next start every part of the program loads torch from that folder (activate(), first thing in main.py).
The work runs in its own process (python gpu_setup.py --install): closing the program doesn't stop it.

~/.CoC_Bot/gpu_install.json  stage / progress / result of the install (read by the app)
~/.CoC_Bot/gpu_install.log   everything that happened (pip's output too)
"""
import json, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
STATE = HOME / "gpu.json"
JOB = HOME / "gpu_install.json"
LOG = HOME / "gpu_install.log"
TARGET = HOME / "cuda_torch"
READY = TARGET / ".ready"
TMP = HOME / "cuda_torch.part"
DL = HOME / "cuda_dl"
OLD_FLAG = HOME / "gpu_install.flag"
NW = 0x08000000 if sys.platform == "win32" else 0            # CREATE_NO_WINDOW
GROUP = 0x00000200 if sys.platform == "win32" else 0         # CREATE_NEW_PROCESS_GROUP (survives the program closing)


def activate():
    """Use the CUDA torch if it is installed and checked (must run before anything imports torch)."""
    try:
        if READY.exists() and str(TARGET) not in sys.path:
            sys.path.insert(0, str(TARGET))
            os.environ["PYTHONPATH"] = str(TARGET) + os.pathsep + os.environ.get("PYTHONPATH", "")
    except Exception:
        pass


# ---------------------------------------------------------------- finding the card
def _smi():
    exe = shutil.which("nvidia-smi")
    if exe: return exe
    if sys.platform != "win32": return None
    for p in (r"C:\Windows\System32\nvidia-smi.exe", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
        if os.path.exists(p): return p
    # newer (DCH) drivers keep it only in the driver store
    store = Path(r"C:\Windows\System32\DriverStore\FileRepository")
    try:
        for d in store.glob("nv*"):
            p = d / "nvidia-smi.exe"
            if p.exists(): return str(p)
    except OSError:
        pass
    return None


def _windows_cards():
    """Graphics cards Windows knows about (works even without nvidia-smi)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name + '|' + $_.DriverVersion + '|' + $_.AdapterRAM }"],
                           capture_output=True, text=True, timeout=20, creationflags=NW)
        out = []
        for line in r.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) >= 2 and parts[0]: out.append(parts)
        return out
    except Exception:
        return []


def _nv_driver(win_version):
    """Windows driver version 32.0.15.6603 -> NVIDIA version 566.03."""
    digits = "".join(win_version.split(".")[-2:])
    return f"{digits[-5:-2]}.{digits[-2:]}" if len(digits) >= 5 else win_version


def nvidia():
    """{"name", "driver", "memory_mb"} of the first NVIDIA card, or None."""
    exe = _smi()
    if exe:
        try:
            r = subprocess.run([exe, "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=15, creationflags=NW)
            name, driver, mem = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")[:3]]
            return {"name": name, "driver": driver, "memory_mb": int(float(mem))}
        except Exception:
            pass
    if sys.platform == "win32":
        for name, ver, *rest in _windows_cards():
            if "nvidia" in name.lower():
                try: mem = int(rest[0]) // (1024 * 1024) if rest and rest[0].strip().isdigit() else 0
                except ValueError: mem = 0
                return {"name": name.strip(), "driver": _nv_driver(ver.strip()), "memory_mb": mem}
    return None


# ---------------------------------------------------------------- state
def _python(py=None):
    return (py or sys.executable).replace("pythonw.exe", "python.exe")


def _pythonw(py=None):
    """The windowless python (no black window); python.exe where there is none."""
    exe = py or sys.executable
    w = exe.replace("python.exe", "pythonw.exe") if exe.lower().endswith("python.exe") else exe
    return w if os.path.exists(w) else exe


def torch_info(path=None, py=None):
    """(torch version, CUDA usable, CUDA version) checked in a separate python (with `path` first, if given)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(path) if path else ""
    try:
        r = subprocess.run([_python(py), "-c", "import torch,json;print(json.dumps([torch.__version__, torch.cuda.is_available(), "
                            "torch.version.cuda]))"], capture_output=True, text=True, timeout=300, creationflags=NW, env=env)
        v, cuda, cv = json.loads(r.stdout.strip().splitlines()[-1])
        return v, bool(cuda), cv
    except Exception:
        return None, False, None


def _job():
    try: return json.loads(JOB.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def _set_job(**kw):
    j = _job()
    j.update(kw, t=time.time())
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = JOB.with_suffix(".tmp")
    tmp.write_text(json.dumps(j), encoding="utf-8")
    os.replace(tmp, JOB)


def _log(msg):
    HOME.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


def _alive(pid):
    try:
        import psutil
        return psutil.pid_exists(int(pid)) and psutil.Process(int(pid)).status() != "zombie"
    except Exception:
        return False


def installing():
    j = _job()
    return bool(j.get("running")) and _alive(j.get("pid", 0))


def status(refresh=False):
    try: st = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError): st = {}
    if refresh or not st or time.time() - st.get("t", 0) > 6 * 3600 or (st.get("card") is None and time.time() - st.get("t", 0) > 60):
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
    if j.get("running") and not _alive(j.get("pid", 0)):       # the worker stopped without finishing (PC off…)
        _set_job(running=False, result="interrupted")
        j = _job()
    st["installing"] = bool(j.get("running"))
    st["ready"] = READY.exists()
    st["active"] = st["ready"] and str(TARGET) in sys.path      # this program started with the card's torch
    st["pending"] = False
    st["result"] = j.get("result", "")
    st["error"] = j.get("error", "")
    st["files"] = j.get("files", [])
    if st["installing"]:
        done, total = j.get("done", 0), j.get("total", 0)
        st["progress"] = {"stage": j.get("stage", "start"), "mb": done // 1048576, "of_mb": total // 1048576,
                          "pct": int(done * 100 / total) if total else 0, "speed": j.get("speed", 0),
                          "minutes": int((time.time() - j.get("start", time.time())) / 60)}
    try: st["log"] = LOG.read_text(encoding="utf-8", errors="ignore")[-1500:]
    except OSError: st["log"] = ""
    return st


def _index_url(driver):
    """
    CUDA 12.8 (driver 570+): also built for the newest cards (RTX 50 / Blackwell) — with an older build those compile
    for minutes on the first start. CUDA 12.6 for drivers 525+, else CUDA 11.8.
    """
    try: major = int(str(driver).split(".")[0])
    except ValueError: major = 0
    if major >= 570: return "https://download.pytorch.org/whl/cu128"
    return "https://download.pytorch.org/whl/cu126" if major >= 525 else "https://download.pytorch.org/whl/cu118"


# ---------------------------------------------------------------- start (from the app)
def start_install(py=None):
    """Start the worker process (the program stays open). -> (ok, error)."""
    if installing(): return True, ""
    card = nvidia()
    if not card: return False, "no_nvidia"
    HOME.mkdir(parents=True, exist_ok=True)
    LOG.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {card['name']} (driver {card['driver']})\n", encoding="utf-8")
    try:
        kw = {"creationflags": NW | GROUP} if sys.platform == "win32" else {"start_new_session": True}
        p = subprocess.Popen([_pythonw(py), os.path.abspath(__file__), "--install"], cwd=str(HOME), close_fds=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except Exception as e:
        _log(f"could not start: {type(e).__name__}: {e}")
        return False, f"{type(e).__name__}: {e}"
    _set_job(running=True, pid=p.pid, start=time.time(), stage="start", done=0, total=0, result="", error="",
             card=card["name"], driver=card["driver"])
    return True, ""


# ---------------------------------------------------------------- the worker (its own process)
def _pip(args, timeout=None):
    r = subprocess.run([_python(), "-m", "pip"] + args, capture_output=True, text=True, timeout=timeout, creationflags=NW)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write((r.stdout or "")[-3000:] + (r.stderr or "")[-3000:])
    return r


def _download(files):
    """[(url, name)] -> local paths; real progress in the job file; continues partial files."""
    import requests
    DL.mkdir(parents=True, exist_ok=True)
    sizes = []
    for url, name in files:
        try: sizes.append(int(requests.head(url, allow_redirects=True, timeout=30).headers.get("content-length", 0)))
        except Exception: sizes.append(0)
    total = sum(sizes)
    before = 0
    out = []
    t0, last, last_done = time.time(), 0.0, 0
    for (url, name), size in zip(files, sizes):
        path = DL / name
        have = path.stat().st_size if path.exists() else 0
        if size and have == size:
            before += size
            out.append(path)
            continue
        if size and have > size: path.unlink(); have = 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        _log(f"download {name} ({size // 1048576} MB){' from ' + str(have // 1048576) + ' MB' if have else ''}")
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            if r.status_code == 200 and have: have = 0               # server ignored the range: start again
            elif r.status_code not in (200, 206): raise RuntimeError(f"download failed: HTTP {r.status_code}")
            with open(path, "ab" if have else "wb") as f:
                got = have
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    if time.time() - last > 0.7:
                        done = before + got
                        speed = (done - last_done) / max(0.001, time.time() - last) if last else 0
                        _set_job(stage="download", done=done, total=total or done, speed=round(speed / 1048576, 1), file=name)
                        last, last_done = time.time(), done
        before += size or path.stat().st_size
        out.append(path)
    _set_job(stage="download", done=total, total=total)
    return out


def _platform_tag():
    if sys.platform == "win32": return "win_amd64"
    if sys.platform == "darwin": return "macosx"
    return "linux_x86_64"


def _ver(v):
    out = []
    for p in re.split(r"[.+]", v.split("+")[0]):
        out.append(int(p) if p.isdigit() else 0)
    return tuple(out)


def find_files(url):
    """The torch + torchvision wheels on the PyTorch index that fit this python / Windows -> [(url, name)]."""
    import requests
    from urllib.parse import unquote, urljoin
    cp = f"cp{sys.version_info.major}{sys.version_info.minor}"
    plat = _platform_tag()
    picked = []
    want = None
    for pkg in ("torch", "torchvision"):
        page = f"{url}/{pkg}/"
        html = requests.get(page, timeout=60).text
        cands = []
        for href in re.findall(r'href="([^"]+?\.whl)[^"]*"', html):
            name = unquote(href.split("/")[-1])
            m = re.match(rf"{pkg}-([^-]+)-{cp}-{cp}t?-(.+)\.whl$", name)
            if not m or plat not in m.group(2) or m.group(0).count("-") < 4: continue
            if f"-{cp}t-" in name: continue                                      # free-threaded build: no
            v = m.group(1)
            if pkg == "torchvision" and want and _ver(v)[:2] != want: continue   # must match the torch picked
            cands.append((_ver(v), v, urljoin(page, href.split("#")[0]), name))
        if not cands:
            raise RuntimeError(f"no {pkg} for python {sys.version_info.major}.{sys.version_info.minor} ({plat}) on {url}")
        best = max(cands)
        picked.append((best[2], best[3]))
        if pkg == "torch":                     # torchvision 0.(torch minor + 15) goes with torch 2.x
            tv = best[0]
            want = (0, tv[1] + 15) if tv[0] == 2 else None
    return picked


def _unpack(paths):
    """A wheel is a zip: unpack it into its own folder (what pip --target does), with real progress."""
    import zipfile
    shutil.rmtree(TMP, ignore_errors=True)
    TMP.mkdir(parents=True, exist_ok=True)
    zips = [zipfile.ZipFile(p) for p in paths]
    total = sum(i.file_size for z in zips for i in z.infolist())
    done, last = 0, 0.0
    _set_job(stage="install", done=0, total=total)
    _log(f"unpacking {total // 1048576} MB")
    for z in zips:
        for info in z.infolist():
            name = info.filename
            if name.split("/", 1)[0].endswith(".data"): continue          # scripts / headers: not needed
            z.extract(info, TMP)
            done += info.file_size
            if time.time() - last > 0.5:
                _set_job(stage="install", done=done, total=total)
                last = time.time()
        z.close()
    _set_job(stage="install", done=total, total=total)
    _log("unpacked")


def worker(files_given=None):
    _set_job(running=True, pid=os.getpid(), stage="find")
    try:
        card = nvidia()
        if not card: raise RuntimeError("no NVIDIA card found")
        if files_given:
            # files the user downloaded himself (from the links in the app)
            paths = [Path(p) for p in files_given if str(p).endswith(".whl") and os.path.exists(p)]
            if not any("torch-" in p.name for p in paths): raise RuntimeError("the torch file (torch-…whl) is missing")
            _log("your files: " + ", ".join(p.name for p in paths))
        else:
            url = _index_url(card["driver"])
            _log(f"index {url}, python {sys.version.split()[0]}")
            # 1. which files fit this PC (read from the index page: seconds)
            files = find_files(url)
            _set_job(files=[{"url": u, "name": n} for u, n in files])
            _log("files: " + ", ".join(n for _, n in files))
            # 2. download
            paths = _download(files)
        # 3. install into its own folder
        _unpack(paths)
        # 4. check
        _set_job(stage="check")
        v, cuda, cv = torch_info(TMP)
        _log(f"check: torch {v}, CUDA {'ON' if cuda else 'off'} ({cv})")
        if not cuda: raise RuntimeError(f"torch {v} doesn't see the card (driver {card['driver']} too old?)")
        shutil.rmtree(TARGET, ignore_errors=True)
        TMP.rename(TARGET)
        READY.write_text(json.dumps({"t": time.time(), "torch": v, "cuda": cv}), encoding="utf-8")
        shutil.rmtree(DL, ignore_errors=True)
        _set_job(running=False, stage="done", result="ready")
        _log("ready")
    except Exception as e:
        _log(f"FAILED: {type(e).__name__}: {e}")
        shutil.rmtree(TMP, ignore_errors=True)
        _set_job(running=False, result="failed", error=str(e)[:300])
    try: status(refresh=True)
    except Exception: pass


def remove():
    """Back to the processor."""
    shutil.rmtree(TARGET, ignore_errors=True)
    status(refresh=True)


def start_install_files(paths, py=None):
    """Install wheels the user downloaded himself. -> (ok, error)"""
    if installing(): return False, "busy"
    paths = [str(p) for p in paths if str(p).lower().endswith(".whl")]
    if not paths: return False, "no .whl files chosen"
    HOME.mkdir(parents=True, exist_ok=True)
    LOG.write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} installing your files\n", encoding="utf-8")
    try:
        kw = {"creationflags": NW | GROUP} if sys.platform == "win32" else {"start_new_session": True}
        p = subprocess.Popen([_pythonw(py), os.path.abspath(__file__), "--install", "--files"] + paths, cwd=str(HOME),
                             close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    _set_job(running=True, pid=p.pid, start=time.time(), stage="install", done=0, total=0, result="", error="")
    return True, ""


def links():
    """Direct download links for this PC (for downloading by hand). -> [(url, name)]"""
    card = nvidia()
    return find_files(_index_url(card["driver"] if card else "999"))


if __name__ == "__main__" and "--install" in sys.argv:
    worker(sys.argv[sys.argv.index("--files") + 1:] if "--files" in sys.argv else None)
