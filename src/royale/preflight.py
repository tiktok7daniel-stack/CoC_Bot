"""Lightweight pre-flight check before Clash Royale bot startup."""
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List


@dataclass
class PreflightResult:
    ok: bool
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _find_root() -> Path:
    """Find project root from this file."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def _check_assets(root: Path) -> PreflightResult:
    """Verify required assets exist."""
    result = PreflightResult(ok=True)

    assets = {
        "cards.json": root / "assets" / "royale" / "cards.json",
        "units_M_480x352.onnx": root / "assets" / "royale" / "models" / "units_M_480x352.onnx",
        "side.onnx": root / "assets" / "royale" / "models" / "side.onnx",
    }

    for name, path in assets.items():
        if not path.exists():
            result.errors.append(f"Missing required asset: {name} at {path}")
            result.ok = False

    # Check ONNX models directory
    models_dir = root / "assets" / "royale" / "models"
    if not models_dir.exists():
        result.warnings.append(f"Models directory not found: {models_dir}")

    return result


def _check_adb() -> PreflightResult:
    """Verify ADB is available and can connect."""
    result = PreflightResult(ok=True)

    from utils import emulator_adb

    adb_path = emulator_adb() or shutil.which("adb")
    if not adb_path:
        result.warnings.append("ADB executable not found; the connection manager will try to connect")
        return result

    try:
        # Quick check: list devices
        proc = subprocess.run([adb_path, "devices"], capture_output=True, text=True, timeout=5)
        if proc.returncode != 0:
            result.warnings.append(f"ADB devices failed: {proc.stderr.strip()}")
        else:
            # Check if any device is connected
            lines = proc.stdout.strip().split('\n')
            devices = [l for l in lines[1:] if l.strip() and 'device' in l and 'unauthorized' not in l]
            if not devices:
                result.warnings.append("No ADB devices connected (emulator not running?)")
    except subprocess.TimeoutExpired:
        result.warnings.append("ADB command timed out")
    except Exception as e:
        result.warnings.append(f"ADB check failed: {e}")

    return result


def _check_resources() -> PreflightResult:
    """Basic RAM/disk sanity check."""
    result = PreflightResult(ok=True)

    try:
        import psutil
        # RAM: warn if less than 2GB free
        mem = psutil.virtual_memory()
        free_gb = mem.available / (1024**3)
        if free_gb < 2.0:
            result.warnings.append(f"Low free RAM: {free_gb:.1f} GB (recommend 2+ GB)")
    except ImportError:
        result.warnings.append("psutil not installed — skipping RAM check")
    except Exception as e:
        result.warnings.append(f"RAM check failed: {e}")

    try:
        # Disk: warn if less than 1GB free
        total, used, free = shutil.disk_usage(Path.home())
        free_gb = free / (1024**3)
        if free_gb < 1.0:
            result.warnings.append(f"Low disk space: {free_gb:.1f} GB free")
    except Exception as e:
        result.warnings.append(f"Disk check failed: {e}")

    return result


def run_preflight() -> PreflightResult:
    """Run all pre-flight checks and return combined result."""
    root = _find_root()

    result = PreflightResult(ok=True)

    # Run all checks
    for check, args in ((_check_assets, (root,)), (_check_adb, ()), (_check_resources, ())):
        try:
            r = check(*args)
            result.errors.extend(r.errors)
            result.warnings.extend(r.warnings)
            if not r.ok:
                result.ok = False
        except Exception as e:
            result.errors.append(f"Pre-flight check failed: {e}")
            result.ok = False

    return result


def log_preflight(log):
    """Run pre-flight and log results."""
    result = run_preflight()
    if result.ok and not result.warnings:
        log.info("Clash Royale: pre-flight checks passed")
    if result.warnings:
        for w in result.warnings:
            log.warning(f"Clash Royale pre-flight: {w}")
    if result.errors:
        for e in result.errors:
            log.error(f"Clash Royale pre-flight: {e}")
    return result


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    log = logging.getLogger(__name__)
    r = log_preflight(log)
    sys.exit(0 if r.ok else 1)