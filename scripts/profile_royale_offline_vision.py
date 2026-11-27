"""Profile the Royale vision pipeline on saved frames without an emulator."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", type=Path, nargs="+")
    parser.add_argument("--passes", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.passes < 1:
        parser.error("passes must be positive")

    import numpy as np
    from PIL import Image
    import trt_engine
    accelerated = trt_engine.activate()
    from royale.eyes import Eyes
    from royale import strong_eyes
    from royale.unit_tracker import UnitTracker

    frames = []
    for path in args.frames:
        with Image.open(path) as image:
            frames.append(np.array(image.convert("RGB")))
    # Use only locally available weights. Never start a download from a benchmark.
    if strong_eyes.ONNX.is_file() and strong_eyes.NAMES.is_file():
        strong_eyes.ensure()
    eyes = Eyes()
    for frame in frames:
        eyes.look(frame)
    samples = []
    for _ in range(args.passes):
        eyes.tracker = UnitTracker()
        eyes._side_cache.clear()
        for frame in frames:
            observation = eyes.look(frame)
            samples.append({"source": observation["vision_source"], **observation["vision_timing"]})

    stages = {}
    for field in samples[0]:
        if not field.endswith("_ms"):
            continue
        values = sorted(row[field] for row in samples)
        stages[field] = {f"p{q}": values[math.ceil(q / 100 * len(values)) - 1] for q in (50, 95, 99)}
    session = strong_eyes._S.get("sess")
    report = {
        "scope": "saved RGB image to observation; excludes capture, game inputs and decision",
        "frame_count": len(frames), "samples": len(samples),
        "runtime_accelerated": accelerated, "full_detector_runtime": getattr(session, "kind", None),
        "vision_sources": dict(Counter(row["source"] for row in samples)),
        "stages_ms": stages,
        "vision_target_p95_ms": 4.5, "vision_target_met": stages["total_ms"]["p95"] <= 4.5,
        "measurements": samples,
    }
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "measurements"}))


if __name__ == "__main__":
    main()
