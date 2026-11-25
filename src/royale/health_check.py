"""
The bot checks itself (6.9.16): every part the play depends on, measured — not assumed — with a clear verdict and
what to do, in Egyptian Arabic. It runs:
  * by itself at every Clash Royale start, before the first battle (the log + the phone get the summary)
  * from the app: Training page -> "Check everything now" (`python -m royale.health_check`, its own process)
Saved to ~/.CoC_Bot/health.json and sent to the learning repo (inbox/health/<account>.json) so it can be read from
outside the PC.

Checks
  onnxruntime     which copy is loaded (the app's TensorRT / DirectML folder or Python's) and that it imports
  eyes_device     what runs the eyes: TensorRT / CUDA / DirectML (graphics card) or the processor
  big_eyes        the arena detector (174 kinds): loaded, inference time and the installed training mAP50
  small_eyes      BuildABot's units model + side model: loaded, their time
  hand_model      the hand-card model: loaded, its accuracy, its time for the 5 slots
  one_look        a whole look of the eyes on a battle-sized picture (both models, colours, tracker): the time the
                  bot needs per moment — the number that decides whether the boxes keep up
  tensorrt        TensorRT ready / being set up / a new setup waiting for a restart
  card            NVIDIA card: busy, memory, temperature
  stream          the live screen stream: pictures a second actually arriving (inside the bot only)
  disk            free space for the models and the training
Each: ok / warn / bad + value + `fix_ar` (what to do).
"""
import json, os, sys, time
from pathlib import Path

HOME = Path.home() / ".CoC_Bot"
OUT = HOME / "health.json"


def _item(name, state, value, fix_ar="", detail=""):
    return {"name": name, "state": state, "value": value, "fix_ar": fix_ar, "detail": str(detail)[:300]}


def _bench(fn, n=10):
    fn()                                   # warm
    t = time.perf_counter()
    for _ in range(n): fn()
    return (time.perf_counter() - t) * 1000 / n


def run(frame_fn=None, stream=None, log=None):
    """-> {"t", "ok", "items": [...], "summary_ar"}. frame_fn: the bot's screen grabber (inside the bot)."""
    import numpy as np
    items = []
    say = (log.info if log else print)

    # ---- onnxruntime
    try:
        import onnxruntime as ort
        f = os.path.dirname(ort.__file__)
        where = "TensorRT folder" if "ort_trt" in f else ("DirectML folder" if "ort_dml" in f else "Python's own")
        prov = ort.get_available_providers()
        items.append(_item("onnxruntime", "ok", f"{ort.__version__} · {where}", detail=", ".join(prov)))
    except Exception as e:
        prov = []
        items.append(_item("onnxruntime", "bad", "does not load", "onnxruntime مش بيتحمّل — اقفل البرنامج وافتحه تاني "
                           "(بيصلّح نفسه أول ما يفتح)", e))

    # ---- the eyes' device
    gpu = any(p in prov for p in ("TensorrtExecutionProvider", "CUDAExecutionProvider", "DmlExecutionProvider"))
    items.append(_item("eyes_device", "ok" if gpu else "bad",
                       ("graphics card: " + ", ".join(p.replace("ExecutionProvider", "") for p in prov if p != "CPUExecutionProvider"))
                       if gpu else "the PROCESSOR",
                       "" if gpu else "العيون شغالة على المعالج (بطيء جدًا: المربعات بتتأخر أو مش بتظهر). البرنامج بيجهّز نسخة "
                                      "كارت الشاشة في الخلفية — استنى دقيقتين واقفله وافتحه تاني"))

    # ---- the big eyes
    big_ms = None
    try:
        from royale import strong_eyes
        for _ in range(60):
            if strong_eyes.ensure(log): break
            time.sleep(1)
        s = strong_eyes._S.get("sess")
        if s is None:
            items.append(_item("big_eyes", "bad", "not loaded", "العيون الكبيرة ما اتحمّلتش — شوف السجل",
                               strong_eyes._S.get("error")))
        else:
            kind = getattr(s, "kind", "?")
            try: S = int(s.get_inputs()[0].shape[2])
            except Exception: S = 800
            x = np.random.rand(1, 3, S, S).astype(np.float32)
            name = s.get_inputs()[0].name
            big_ms = _bench(lambda: s.run(None, {name: x}), 8)
            st = {}
            try:
                from royale import trainer
                st = trainer.read_status()
            except Exception:
                pass
            acc = f" · mAP50 {100 * st['new_map50']:.1f}%" if st.get("used") and st.get("new_map50") else ""
            state = "ok" if big_ms <= 60 else ("warn" if big_ms <= 150 else "bad")
            items.append(_item("big_eyes", state, f"{big_ms:.0f} ms a picture on {kind}{acc}",
                               "" if state == "ok" else "العيون الكبيرة بطيئة — لو مكتوب cpu يبقى كارت الشاشة مش متشغّل "
                               "(اقفل البرنامج وافتحه)، ولو dml يبقى TensorRT لسه بيتجهّز"))
    except Exception as e:
        items.append(_item("big_eyes", "bad", "error", "حصل خطأ في العيون الكبيرة", e))

    # ---- the fast eyes (6.9.18: YOLO26s at 640, the same-moment look when the big eyes are slow)
    try:
        from royale import strong_eyes
        if strong_eyes.fast_ready():
            fs = strong_eyes._F["sess"]
            xf = np.random.rand(1, 3, 640, 640).astype(np.float32)
            nf = fs.get_inputs()[0].name
            ms = _bench(lambda: fs.run(None, {nf: xf}), 8)
            items.append(_item("fast_eyes", "ok" if ms <= 25 else "warn", f"{ms:.0f} ms a picture on {getattr(fs, 'kind', '?')}"))
        else:
            items.append(_item("fast_eyes", "warn", "not trained yet",
                               "العيون السريعة (YOLO26) لسه ما اتدربتش — صفحة التدريب ← «درّب العيون» (بيكمّل من مكانه)"))
    except Exception as e:
        items.append(_item("fast_eyes", "warn", "error", "", e))

    # ---- the small eyes
    try:
        from royale.vision.detectors.unit_detector import UnitDetector
        from royale.vision import constants as C
        u = UnitDetector(os.path.join(C.MODELS_DIR, "units_M_480x352.onnx"), [])
        x = np.random.rand(1, 3, 480, 352).astype(np.float16)
        ms = _bench(lambda: u._infer(x), 8)
        state = "ok" if ms <= 40 else ("warn" if ms <= 100 else "bad")
        items.append(_item("small_eyes", state, f"{ms:.0f} ms a picture on {getattr(u.sess, 'kind', '?')}"))
    except Exception as e:
        items.append(_item("small_eyes", "bad", "error", "العيون الصغيرة ما اتحمّلتش", e))

    # ---- the hand-card model
    try:
        from royale import hand_classifier
        hc = hand_classifier.HandClassifier.load() if hand_classifier.ONNX.exists() else None
        if hc is None:
            items.append(_item("hand_model", "warn", "not trained / not loaded",
                               "موديل قراءة الكروت مش موجود — صفحة التدريب ← «درّب العيون»"))
        else:
            meta = json.loads(hand_classifier.META.read_text(encoding="utf-8"))
            fr = np.zeros((1280, 720, 3), np.uint8)
            ms = _bench(lambda: hc.probs(fr), 5)
            items.append(_item("hand_model", "ok", f"accuracy {100 * meta.get('score', 0):.1f}% · {ms:.0f} ms for 5 cards"))
    except Exception as e:
        items.append(_item("hand_model", "warn", "error", "موديل الكروت فيه مشكلة (البوت بيقرا الكروت بالطريقة القديمة)", e))

    # ---- one whole look
    look_ms = None
    try:
        from royale.eyes import Eyes
        if frame_fn is not None:
            try: fr = frame_fn()
            except Exception: fr = None
        else:
            fr = None
        if fr is None:
            pic = Path(__file__).resolve().parent.parent.parent / "assets" / "royale" / "health_frame.jpg"
            if pic.exists():
                from PIL import Image
                fr = np.array(Image.open(pic).convert("RGB"))
            else:
                fr = (np.random.rand(1280, 720, 3) * 255).astype(np.uint8)
        e = Eyes()
        for _ in range(3): e.look(fr)
        t = time.perf_counter()
        for _ in range(10): e.look(fr)
        look_ms = (time.perf_counter() - t) * 100
        state = "ok" if look_ms <= 150 else ("warn" if look_ms <= 300 else "bad")
        stages = getattr(e, "last_timings", {})
        stage_detail = " · ".join(f"{k.removesuffix('_ms')} {v:g} ms" for k, v in stages.items())
        items.append(_item("one_look", state, f"{look_ms:.0f} ms a moment ({1000 / max(1, look_ms):.1f} looks a second)",
                           "" if state == "ok" else "النظرة الكاملة بطيئة — السبب غالبًا العيون على المعالج أو الكارت "
                           "مشغول بحاجة تانية (تدريب / برنامج تاني)", detail=stage_detail))
    except Exception as e:
        items.append(_item("one_look", "bad", "error", "النظرة الكاملة ما اشتغلتش", e))

    # ---- TensorRT
    try:
        import trt_engine
        ti = trt_engine.info()
        if ti.get("mode"):
            items.append(_item("tensorrt", "ok", f"ready ({ti['mode']})" + (" — in use" if trt_engine.active() else "")))
        elif (trt_engine.STAGE / "READY").exists():
            items.append(_item("tensorrt", "warn", "set up, waiting for a restart", "TensorRT جاهز — اقفل البرنامج وافتحه عشان يشتغل"))
        elif trt_engine.nvidia():
            items.append(_item("tensorrt", "warn", "being set up / not yet", "TensorRT بيتجهّز في الخلفية (تحميل كبير) — مش لازم تعمل حاجة"))
        else:
            items.append(_item("tensorrt", "ok", "no NVIDIA card (not needed)"))
    except Exception as e:
        items.append(_item("tensorrt", "warn", "error", "", e))

    # ---- the graphics card
    try:
        from royale import trainer
        c = trainer._card_now()
        if c:
            state = "ok" if c["temp_c"] < 80 and c["mem_mb"] < 0.92 * c["mem_total_mb"] else "warn"
            items.append(_item("card", state, f"busy {c['busy']}% · memory {c['mem_mb']}/{c['mem_total_mb']} MB · {c['temp_c']}°C",
                               "" if state == "ok" else "الكارت سخن أو ذاكرته مليانة — اقفل التدريب / البرامج التانية"))
    except Exception:
        pass

    # ---- the stream
    if stream is not None:
        try:
            n0 = stream.frames; time.sleep(2.0); fps = (stream.frames - n0) / 2.0
            state = "ok" if fps >= 20 else ("warn" if fps >= 8 else "bad")
            items.append(_item("stream", state, f"{fps:.0f} pictures a second arriving (asked {stream.max_fps})",
                               "" if state == "ok" else "صورة المحاكي بتوصل بطيء — اتأكد إن LDPlayer شغال ومش متصغّر"))
        except Exception:
            pass

    # ---- disk
    try:
        import shutil
        free = shutil.disk_usage(str(HOME if HOME.exists() else Path.home())).free / 1e9
        items.append(_item("disk", "ok" if free > 10 else "warn", f"{free:.0f} GB free",
                           "" if free > 10 else "المساحة قليلة — امسح حاجات مش محتاجها"))
    except Exception:
        pass

    bad = [i for i in items if i["state"] == "bad"]
    warn = [i for i in items if i["state"] == "warn"]
    res = {"t": time.time(), "time": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": not bad, "items": items,
           "big_ms": big_ms, "look_ms": look_ms,
           "summary_ar": ("✅ كل حاجة شغالة صح" if not bad and not warn else
                          ("❌ فيه مشكلة: " + " · ".join(i["fix_ar"] or i["name"] for i in bad)) if bad else
                          ("⚠ شغال، بس: " + " · ".join(i["fix_ar"] or i["name"] for i in warn)))}
    try:
        from version import VERSION
        res["bot_version"] = VERSION
    except Exception:
        pass
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    for i in items:
        say(f"[check] {'✅' if i['state'] == 'ok' else ('⚠' if i['state'] == 'warn' else '❌')} {i['name']}: {i['value']}"
            + (f" — {i['fix_ar']}" if i["fix_ar"] else ""))
    say("[check] " + res["summary_ar"])
    try:
        import learn_sync
        if learn_sync.configured():
            acc = os.environ.get("CF_ACCOUNT") or "main"
            try:
                import utils
                acc = utils.INSTANCE_ID or acc
            except Exception:
                pass
            learn_sync._put(f"inbox/health/{acc}.json", json.dumps(res, ensure_ascii=False, indent=1).encode("utf-8"),
                            "health: " + ("ok" if res["ok"] else "problems"))
    except Exception:
        pass
    return res


def read():
    try: return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import ort_gpu
        ort_gpu.activate()                     # the same onnxruntime the bot uses
    except Exception:
        pass
    run()
