"""
The eyes on NVIDIA TensorRT (6.6): every vision model (the arena detector, the BuildABot units / side models, the
hand-card model) compiled for THIS graphics card (an RTX 4060 = Ada, FP16 tensor cores) instead of DirectML's
generic path.

How (no CUDA toolkit to install, nothing of the program's own copy touched):
  install   onnxruntime-gpu (its TensorRT + CUDA providers) and NVIDIA's TensorRT 10 libraries from pip into their own
            folder ~/.CoC_Bot/ort_trt (pip --target, --no-deps: no second numpy). CUDA / cuDNN: the ones already on
            this PC with the CUDA torch (~/.CoC_Bot/cuda_torch/torch/lib: cudart, cublas, cudnn 9), else NVIDIA's pip
            packages into the same folder.
  check     in a separate process: a TensorRT session on a real model of the bot is made and run — only then READY
            (mode "trt"; or "cuda" when TensorRT itself fails but CUDA works: still faster than DirectML). The same
            process builds every model's FP16 engine once (1-3 min each), so a battle never waits for a build
  activate  main.py, before anything imports onnxruntime: this folder first on the path (instead of DirectML) and
            its DLL folders known to Windows
  sessions  make_session(path) -> a drop-in for onnxruntime.InferenceSession:
              TensorRT (FP16, engine + timing cache in ~/.CoC_Bot/trt_cache)  ->  CUDA  ->  DirectML  ->  processor
            an engine not built yet: CUDA answers at once while TensorRT builds in the background, then takes over
            (warmed up first: no slow first picture); a model changed (the trainer put better eyes in place): its
            engine is rebuilt the same way. The input stays on the card between runs (one buffer, updated in place,
            IOBinding); only the answer comes back.
FP32 instead of FP16: CF_TRT_FP32=1 (if a model ever reads worse in FP16).

`python -m trt_engine --check` = install check + engine build (what the app runs), `--build` = engines only.
"""
import hashlib, json, os, subprocess, sys, threading, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
TARGET = HOME / "ort_trt"
READY = TARGET / "READY"
CACHE = HOME / "trt_cache"
LOG = HOME / "ort_trt_install.log"
TORCH_LIB = HOME / "cuda_torch" / "torch" / "lib"
# (onnxruntime-gpu, tensorrt-cu12-libs) pairs tried in order: each onnxruntime-gpu release is built on one TensorRT 10.x
PAIRS = [("1.22.0", "10.9.0.34"), ("1.23.2", "10.13.3.9"), ("1.20.2", "10.4.0")]
CUDA_PKGS = ["nvidia-cuda-runtime-cu12", "nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cufft-cu12",
             "nvidia-curand-cu12", "nvidia-cuda-nvrtc-cu12"]
NW = 0x08000000 if os.name == "nt" else 0
_S = {"busy": False, "active": False}


def _log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f: f.write(time.strftime("%H:%M:%S ") + msg.rstrip() + "\n")
    except OSError:
        pass


def info():
    try: return json.loads(READY.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


def nvidia():
    """An NVIDIA card on this PC (nvidia-smi answers)."""
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10, creationflags=NW)
        return r.returncode == 0 and "GPU" in r.stdout
    except Exception:
        return False


def dll_dirs():
    """Every folder whose DLLs the TensorRT / CUDA providers load."""
    out = [TARGET / "tensorrt_libs", TARGET / "onnxruntime" / "capi"]
    nv = TARGET / "nvidia"
    if nv.exists():
        out += [p / "bin" for p in nv.iterdir() if (p / "bin").exists()]
    if TORCH_LIB.exists(): out.append(TORCH_LIB)
    return [p for p in out if p.exists()]


def activate():
    """Before anything imports onnxruntime (main.py): this onnxruntime first, its DLL folders known. -> True when on."""
    try:
        if not READY.exists() or str(TARGET) in sys.path: return _S["active"]
        if info().get("mode") not in ("trt", "cuda"): return False
        sys.path.insert(0, str(TARGET))
        os.environ["PYTHONPATH"] = str(TARGET) + os.pathsep + os.environ.get("PYTHONPATH", "")
        dirs = [str(p) for p in dll_dirs()]
        os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])
        for d in dirs:
            try: os.add_dll_directory(d)
            except (OSError, AttributeError): pass
        _S["active"] = True
        return True
    except Exception:
        return False


def active():
    return _S["active"]


# ------------------------------------------------------------------ install + check (background, once)
def needed():
    return os.name == "nt" and not READY.exists() and nvidia()


def _pip(args, timeout=3600):
    r = subprocess.run([_py(), "-m", "pip", "install", "--upgrade", "--no-deps", "--target", str(TARGET), *args],
                       capture_output=True, text=True, timeout=timeout, creationflags=NW)
    _log(" ".join(args) + "\n" + r.stdout[-1500:] + r.stderr[-1500:])
    return r.returncode == 0


def _py():
    try:
        import gpu_setup
        return gpu_setup._python()
    except Exception:
        return sys.executable


def _install(log=None):
    try:
        TARGET.mkdir(parents=True, exist_ok=True)
        torch_cuda = (TORCH_LIB / "cudnn64_9.dll").exists() and any(TORCH_LIB.glob("cublas64_12*.dll"))
        if not torch_cuda:
            if log: log.info("Clash Royale: TensorRT setup — downloading NVIDIA's CUDA / cuDNN libraries (~1.5 GB)")
            _pip(CUDA_PKGS)
        for ort_v, trt_v in PAIRS:
            if log: log.info(f"Clash Royale: TensorRT setup — onnxruntime-gpu {ort_v} + TensorRT {trt_v} (~1.5 GB, once)")
            if not _pip([f"onnxruntime-gpu=={ort_v}", f"tensorrt-cu12-libs=={trt_v}"]): continue
            chk = subprocess.run([_py(), str(Path(__file__).resolve()), "--check"], capture_output=True, text=True,
                                 timeout=3600, creationflags=NW, cwd=str(Path(__file__).resolve().parent))
            _log("check: " + chk.stdout[-3000:] + chk.stderr[-2000:])
            m = info().get("mode")
            if m == "trt":
                if log: log.info("Clash Royale: the eyes run on TensorRT from the next start " + str(info().get("bench", "")))
                return
            if m == "cuda": break                       # CUDA works, TensorRT not with this pair: try the next pair
        if info().get("mode") == "cuda" and log:
            log.info("Clash Royale: TensorRT could not start on this card — the eyes run on CUDA from the next start")
        elif log:
            log.info("Clash Royale: TensorRT / CUDA could not be set up — the eyes stay on DirectML (see ort_trt_install.log)")
    except Exception as e:
        _log(f"failed: {e}")
    finally:
        _S["busy"] = False


def install_in_background(log=None):
    if _S["busy"] or not needed(): return False
    _S["busy"] = True
    if log: log.info("Clash Royale: setting up TensorRT for the NVIDIA card in the background (the bot keeps playing)")
    threading.Thread(target=_install, args=(log,), daemon=True, name="ort-trt").start()
    return True


# ------------------------------------------------------------------ sessions
def _fp16():
    return os.environ.get("CF_TRT_FP32", "") not in ("1", "true", "yes")


def _key(path):
    """A model's engine name: its content (a new model = a new engine)."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return f"{Path(path).stem}_{h.hexdigest()[:12]}_{'fp16' if _fp16() else 'fp32'}"


def trt_options(path):
    CACHE.mkdir(parents=True, exist_ok=True)
    return {"device_id": 0, "trt_fp16_enable": _fp16(), "trt_engine_cache_enable": True,
            "trt_engine_cache_path": str(CACHE), "trt_engine_cache_prefix": _key(path),
            "trt_timing_cache_enable": True, "trt_timing_cache_path": str(CACHE),
            "trt_max_workspace_size": 2 << 30, "trt_builder_optimization_level": 3}


CUDA_OPTS = {"device_id": 0, "cudnn_conv_algo_search": "EXHAUSTIVE", "do_copy_in_default_stream": True}


def _built(path):
    return (CACHE / (_key(path) + ".built")).exists()


def _dummy(sess):
    import numpy as np
    feed = {}
    for i in sess.get_inputs():
        shape = [d if isinstance(d, int) and d > 0 else 1 for d in i.shape]
        dt = np.float16 if "float16" in i.type else np.float32
        feed[i.name] = np.random.rand(*shape).astype(dt)
    return feed


class VisionSession:
    """onnxruntime.InferenceSession's get_inputs / get_outputs / get_providers / run, on the fastest provider this PC
    has (see the module doc). `kind` names what runs it now: trt / cuda / dml / cpu."""

    def __init__(self, path, threads=None, build_now=False):
        import onnxruntime as ort
        self.path, self._ort = str(path), ort
        self.threads = threads
        av = ort.get_available_providers()
        self.sess, self.kind = None, "cpu"
        if "TensorrtExecutionProvider" in av and (build_now or _built(self.path)):
            self._try("trt")
        if self.sess is None and "CUDAExecutionProvider" in av: self._try("cuda")
        if self.sess is None and "DmlExecutionProvider" in av: self._try("dml")
        if self.sess is None: self._try("cpu")
        self._in = {}
        if "TensorrtExecutionProvider" in av and self.kind != "trt" and not (CACHE / (_key(self.path) + ".failed")).exists():
            threading.Thread(target=self._build_trt, daemon=True, name="trt-build").start()

    def _make(self, kind):
        ort = self._ort
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if self.threads: so.intra_op_num_threads = int(self.threads)
        if kind == "trt":
            opts = trt_options(self.path)
            try:
                return self._check(ort.InferenceSession(self.path, sess_options=so, providers=[
                    ("TensorrtExecutionProvider", opts), ("CUDAExecutionProvider", CUDA_OPTS), "CPUExecutionProvider"]), kind)
            except Exception as e:                         # an older onnxruntime without some option: the basic ones
                _log(f"{Path(self.path).name}: TensorRT options cut down ({e})"[:300])
                opts = {k: opts[k] for k in ("device_id", "trt_fp16_enable", "trt_engine_cache_enable",
                                             "trt_engine_cache_path")}
            prov = [("TensorrtExecutionProvider", opts), ("CUDAExecutionProvider", CUDA_OPTS), "CPUExecutionProvider"]
        elif kind == "cuda":
            prov = [("CUDAExecutionProvider", CUDA_OPTS), "CPUExecutionProvider"]
        elif kind == "dml":
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            prov = ["DmlExecutionProvider", "CPUExecutionProvider"]
        else:
            prov = ["CPUExecutionProvider"]
        return self._check(ort.InferenceSession(self.path, sess_options=so, providers=prov), kind)

    @staticmethod
    def _check(s, kind):
        want = {"trt": "TensorrtExecutionProvider", "cuda": "CUDAExecutionProvider", "dml": "DmlExecutionProvider"}.get(kind)
        if want and s.get_providers()[0] != want: raise RuntimeError(f"{want} not used")
        return s

    def _try(self, kind):
        try:
            self.sess, self.kind = self._make(kind), kind
            return True
        except Exception as e:
            _log(f"{Path(self.path).name}: {kind} failed: {e}"[:400])
            return False

    def _build_trt(self):
        """The TensorRT engine built and warmed up beside the running session, then swapped in."""
        try:
            s = self._make("trt")
            feed = _dummy(s)
            for _ in range(3): s.run(None, feed)              # the build happens in the first run; then warm
            (CACHE / (_key(self.path) + ".built")).write_text(str(time.time()), encoding="utf-8")
            self.sess, self.kind, self._in = s, "trt", {}
            _log(f"{Path(self.path).name}: TensorRT engine ready ({'FP16' if _fp16() else 'FP32'})")
        except Exception as e:
            CACHE.mkdir(parents=True, exist_ok=True)
            (CACHE / (_key(self.path) + ".failed")).write_text(str(e)[:500], encoding="utf-8")
            _log(f"{Path(self.path).name}: TensorRT build failed, CUDA keeps it: {e}"[:400])

    # ---- the InferenceSession surface
    def get_inputs(self): return self.sess.get_inputs()

    def get_outputs(self): return self.sess.get_outputs()

    def get_providers(self): return self.sess.get_providers()

    def run(self, names, feed, run_options=None):
        s = self.sess
        if self.kind not in ("trt", "cuda"):
            return s.run(names, feed, run_options)
        # the input kept on the card (updated in place: no new buffer every picture), the answer copied back once
        try:
            io = s.io_binding()
            for k, x in feed.items():
                key = (id(s), k)
                v = self._in.get(key)
                if v is None or tuple(v.shape()) != tuple(x.shape):
                    v = self._ort.OrtValue.ortvalue_from_numpy(x, "cuda", 0)
                    self._in[key] = v
                else:
                    v.update_inplace(x)
                io.bind_ortvalue_input(k, v)
            outs = names or [o.name for o in s.get_outputs()]
            for o in outs: io.bind_output(o, "cpu")
            s.run_with_iobinding(io, run_options)
            return io.copy_outputs_to_cpu()
        except Exception:
            return s.run(names, feed, run_options)


def make_session(path, threads=None):
    """The fastest session for this model on this PC (the trainer's models, BuildABot's, the hand model)."""
    return VisionSession(path, threads=threads)


# ------------------------------------------------------------------ the check / build process
def _models():
    root = Path(__file__).resolve().parent.parent
    out = [root / "assets" / "royale" / "models" / "units_M_480x352.onnx", root / "assets" / "royale" / "models" / "side.onnx",
           HOME / "models" / "cr_detector_v8.onnx", HOME / "models" / "cr_hand_cls.onnx"]
    return [p for p in out if p.exists()]


def bench(path, kind, n=60):
    """ms a run of `path` on `kind` (warmed up)."""
    s = VisionSession.__new__(VisionSession)
    import onnxruntime as ort
    s.path, s._ort, s.threads, s._in = str(path), ort, None, {}
    s.sess, s.kind = s._make(kind), kind
    feed = _dummy(s.sess)
    for _ in range(5): s.run(None, feed)
    t = time.perf_counter()
    for _ in range(n): s.run(None, feed)
    return (time.perf_counter() - t) * 1000 / n


def check():
    """Run in its own process with this folder first: can TensorRT (else CUDA) run the bot's models? Builds each
    model's engine (FP16) and writes READY {mode, providers, bench} — the engine cache stays for the bot."""
    sys.path.insert(0, str(TARGET))
    for d in dll_dirs():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        try: os.add_dll_directory(str(d))
        except (OSError, AttributeError): pass
    import onnxruntime as ort
    av = ort.get_available_providers()
    print("providers:", av, flush=True)
    models = _models()
    if not models: print("no model to check", flush=True); return
    mode, res = None, {}
    if "TensorrtExecutionProvider" in av:
        try:
            for m in models:
                t0 = time.time()
                s = VisionSession(m, build_now=True)
                if s.kind != "trt": raise RuntimeError(f"{m.name}: {s.kind}")
                feed = _dummy(s.sess)
                for _ in range(3): s.run(None, feed)
                (CACHE / (_key(m) + ".built")).write_text(str(time.time()), encoding="utf-8")
                print(f"{m.name}: TensorRT engine built in {time.time() - t0:.0f} s", flush=True)
                res[m.name] = {"trt_ms": round(bench(m, "trt"), 2)}
            mode = "trt"
        except Exception as e:
            print("TensorRT failed:", e, flush=True)
    if mode is None and "CUDAExecutionProvider" in av:
        try:
            for m in models: res.setdefault(m.name, {})["cuda_ms"] = round(bench(m, "cuda"), 2)
            mode = "cuda"
        except Exception as e:
            print("CUDA failed:", e, flush=True)
    if mode and mode == "trt":
        for m in models:
            try: res[m.name]["cuda_ms"] = round(bench(m, "cuda"), 2)
            except Exception: pass
    print("result:", mode, json.dumps(res), flush=True)
    if mode:
        READY.write_text(json.dumps({"mode": mode, "providers": av, "bench": res, "ort": ort.__version__,
                                     "t": time.time()}), encoding="utf-8")


if __name__ == "__main__":
    if "--check" in sys.argv or "--build" in sys.argv:
        check()
