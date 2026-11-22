"""
The eyes' speed and accuracy on THIS PC (6.6) — run it on the gaming PC:

    .venv\\Scripts\\python scripts\\bench_royale_vision.py [--frame a_battle_screenshot.jpg]

  speed      every vision model (arena detector, units, side, hand cards) on every runtime this PC has —
             processor, DirectML (~/.CoC_Bot/ort_dml), CUDA and TensorRT FP16 (~/.CoC_Bot/ort_trt) — each in its own
             process (they are different onnxruntime builds): ms a run, runs a second, TensorRT vs DirectML speed-up
  one look   the whole eyes on a battle picture (--frame): the card matcher + hand model + both detectors + colours +
             tracker, in each runtime — the bot's real ms a look
  hand       the hand-card model's accuracy on its test pictures (real Roboflow hand screenshots / made ones)
  team+track the colour / tracker checks (scripts/test_royale_vision.py)
The table is printed and saved to ~/.CoC_Bot/vision_bench.json.
"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
HOME = Path.home() / ".CoC_Bot"
RUNTIMES = {"default": None, "directml": HOME / "ort_dml", "tensorrt": HOME / "ort_trt"}


def worker(runtime, frame):
    """In its own process: this runtime's onnxruntime first on the path, then every model on every provider it has."""
    sys.path.insert(0, str(SRC))
    target = RUNTIMES.get(runtime)
    if target:
        sys.path.insert(0, str(target))
        import trt_engine
        if runtime == "tensorrt":
            for d in trt_engine.dll_dirs():
                os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
                try: os.add_dll_directory(str(d))
                except (OSError, AttributeError): pass
            trt_engine._S["active"] = True
    import onnxruntime as ort
    import trt_engine
    av = ort.get_available_providers()
    kinds = [k for k, p in (("cpu", "CPUExecutionProvider"), ("dml", "DmlExecutionProvider"), ("cuda", "CUDAExecutionProvider"),
                            ("trt", "TensorrtExecutionProvider")) if p in av]
    if runtime != "default": kinds = [k for k in kinds if k != "cpu"]
    out = {"runtime": runtime, "providers": av, "ort": ort.__version__, "models": {}}
    for m in trt_engine._models():
        r = {}
        for k in kinds:
            try: r[k] = round(trt_engine.bench(m, k), 2)
            except Exception as e: r[k] = f"failed: {str(e)[:80]}"
        out["models"][m.name] = r
    if frame:
        try:
            import numpy as np
            from PIL import Image
            from royale.eyes import Eyes
            im = np.array(Image.open(frame).convert("RGB"))
            e = Eyes()
            for _ in range(5): e.look(im)                 # warm (a TensorRT engine not built yet builds meanwhile)
            t = time.perf_counter()
            for _ in range(30): e.look(im)
            out["look_ms"] = round((time.perf_counter() - t) * 1000 / 30, 1)
            t = time.perf_counter()
            for _ in range(200): e.colors.prepare(im)
            out["team_ms"] = round((time.perf_counter() - t) * 1000 / 200, 2)
        except Exception as ex:
            out["look_ms"] = f"failed: {ex}"[:120]
    print("RESULT " + json.dumps(out), flush=True)


def main():
    frame = None
    if "--frame" in sys.argv: frame = sys.argv[sys.argv.index("--frame") + 1]
    results = []
    for rt, target in RUNTIMES.items():
        if target is not None and not target.exists():
            print(f"[{rt}] not installed on this PC — skipped"); continue
        print(f"[{rt}] measuring…", flush=True)
        args = [sys.executable, str(Path(__file__).resolve()), "--worker", rt] + (["--frame", frame] if frame else [])
        r = subprocess.run(args, capture_output=True, text=True, timeout=3600, cwd=str(SRC))
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT ")), None)
        if not line:
            print(f"[{rt}] failed:\n{(r.stdout + r.stderr)[-1500:]}"); continue
        results.append(json.loads(line[7:]))
    # the table: one row per model, ms per runtime/provider
    cols, rows = [], {}
    for res in results:
        for m, r in res["models"].items():
            for k, v in r.items():
                col = f"{res['runtime']}:{k}"
                if col not in cols: cols.append(col)
                rows.setdefault(m, {})[col] = v
    print("\nms a run (lower is better)")
    print("model".ljust(26) + "".join(c.rjust(18) for c in cols) + "  TensorRT vs DirectML")
    for m, r in rows.items():
        dml = r.get("directml:dml")
        trt = r.get("tensorrt:trt")
        sp = f"{dml / trt:.1f}x faster" if isinstance(dml, (int, float)) and isinstance(trt, (int, float)) and trt else "—"
        print(m.ljust(26) + "".join(str(r.get(c, "—")).rjust(18) for c in cols) + "  " + sp)
    for res in results:
        if "look_ms" in res:
            print(f"one whole look ({res['runtime']}): {res['look_ms']} ms · team colours {res.get('team_ms')} ms")
    # the hand model's accuracy
    hand = None
    try:
        sys.path.insert(0, str(SRC))
        from royale.hand_classifier import META, ONNX
        meta = json.loads(META.read_text(encoding="utf-8"))
        hand = {"score": meta.get("score"), "real": meta.get("real"), "made": meta.get("made")}
        print(f"hand cards: right card {100 * meta['score']:.1f}% — real pictures {meta.get('real')} / made {meta.get('made')}")
    except Exception:
        print("hand cards: not trained yet (Training page → Train the eyes)")
    t = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_royale_vision.py")], capture_output=True, text=True,
                       timeout=600, cwd=str(ROOT))
    print("\nteam colours + tracker checks:\n" + "\n".join(l for l in t.stdout.splitlines()
                                                         if l.startswith(("PASS", "FAIL")) and ("tracker" in l or "team" in l or "brain" in l)))
    HOME.mkdir(parents=True, exist_ok=True)
    (HOME / "vision_bench.json").write_text(json.dumps({"t": time.time(), "results": results, "hand": hand},
                                                       indent=1), encoding="utf-8")


if __name__ == "__main__":
    if "--worker" in sys.argv:
        i = sys.argv.index("--worker")
        fr = sys.argv[sys.argv.index("--frame") + 1] if "--frame" in sys.argv else None
        worker(sys.argv[i + 1], fr)
    else:
        main()
