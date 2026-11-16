"""
Render the CoC Bot crest (icons.CREST) into a multi-resolution Windows icon (16..256 px) and a PNG.
Usage: python -m qt_ui.generate_ico [output_dir]   (default: src/qt_ui/assets)
The .ico is written by hand (PNG frames inside an ICONDIR), so no extra library is needed.
"""
import os, struct, sys
from pathlib import Path

SIZES = (16, 24, 32, 48, 64, 128, 256)


def build_ico(frames):
    """frames: [(size, png_bytes)] -> .ico bytes."""
    header = struct.pack("<HHH", 0, 1, len(frames))
    entries, data = b"", b""
    offset = 6 + 16 * len(frames)
    for size, png in frames:
        w = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", w, w, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    return header + entries + data


def main(out_dir=None):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from . import icons
    out = Path(out_dir) if out_dir else Path(__file__).resolve().parent / "assets"
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for s in SIZES:
        pm = icons.pixmap("crest", s, dpr=1.0)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        frames.append((s, bytes(ba)))
    (out / "app_icon.ico").write_bytes(build_ico(frames))
    icons.pixmap("crest", 512, dpr=1.0).save(str(out / "app_icon.png"), "PNG")
    print(f"wrote {out / 'app_icon.ico'} ({len(frames)} sizes) and app_icon.png")
    return out / "app_icon.ico"


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main(sys.argv[1] if len(sys.argv) > 1 else None)
