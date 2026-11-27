"""Check local assets and a loopback FirstLight Zero resident engine."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
FIRSTLIGHT_CR = ROOT / "third_party" / "firstlight-cr"
FIRSTLIGHT_ZERO = ROOT / "third_party" / "firstlight-zero"
REQUIRED_SLOTS = 8


def check_hash(path, expected, errors):
    try:
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as error:
        errors.append(f"{path}: {error.strerror}")
        return
    if actual != expected:
        errors.append(f"{path}: SHA-256 mismatch\n  expected {expected}\n  found    {actual}")


def check_resident(port, release, errors):
    sys.path.insert(0, str(FIRSTLIGHT_ZERO))
    from native_runner.cr_native_env import ResidentNativeClashEnv

    engine = ResidentNativeClashEnv(0, host="127.0.0.1", port=port, timeout=3)
    try:
        status = engine.resident_status()
        if (
            not status.get("ok")
            or status.get("mode") != "resident-headless"
            or status.get("capacity", 0) < REQUIRED_SLOTS
        ):
            errors.append(f"Port {port} needs resident-headless mode with {REQUIRED_SLOTS} slots.")
            return

        attestation = engine.attest()
        expected = {
            "package_name": release["package"],
            "abi": release["abi"],
            "libg_sha256": release["libg_sha256"],
            "content_version": release["runtime_content_version"],
            "content_fingerprint_sha256": release["runtime_fingerprint_sha256"],
            "production_ready": True,
        }
        for field, value in expected.items():
            actual = getattr(attestation, field)
            if actual != value:
                errors.append(f"Port {port} {field}: expected {value!r}, got {actual!r}.")
    except (OSError, RuntimeError, ValueError) as error:
        errors.append(f"Port {port}: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True, help="FirstLight CR_WORKSPACE_ROOT")
    parser.add_argument("--apk", type=Path, help="Also verify the original APK for an engine build")
    parser.add_argument("--port", type=int, default=26789)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in the range 1–65535")

    metadata = FIRSTLIGHT_CR / "native_runner" / "supported_engine.json"
    if not metadata.is_file() or not (FIRSTLIGHT_ZERO / "native_runner" / "cr_native_env.py").is_file():
        parser.exit(1, "Initialize the firstlight-cr and firstlight-zero Git submodules.\n")
    release = json.loads(metadata.read_text(encoding="utf-8"))
    errors = []
    if args.apk is not None:
        check_hash(args.apk, release["apk_sha256"], errors)
    update = args.workspace / "runtime-update"
    check_hash(update / "fingerprint.json", release["runtime_fingerprint_sha256"], errors)
    if not (update / "assets.scdb").is_file():
        errors.append(f"Missing file: {update / 'assets.scdb'}")
    for path in (
        update / "csv_logic",
        args.workspace / release["resource_directory"],
        args.workspace / "captures" / "decompressed_assets",
    ):
        if not path.is_dir():
            errors.append(f"Missing directory: {path}")
    check_resident(args.port, release, errors)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print(f"FirstLight Zero asset layout and resident engine on 127.0.0.1:{args.port} passed.")


if __name__ == "__main__":
    main()
