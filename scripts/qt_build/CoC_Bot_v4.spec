# PyInstaller spec for CoC Bot v4 (Windows, one folder build).
# Build with scripts\qt_build\build_exe.bat  ->  dist\CoC_Bot_v4\CoC_Bot_v4.exe
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
SRC = os.path.join(ROOT, "src")

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "army_training"), "army_training"),
    (os.path.join(SRC, "gui_server"), "gui_server"),
    (os.path.join(SRC, "qt_ui", "fonts"), os.path.join("qt_ui", "fonts")),
    (os.path.join(SRC, "qt_ui", "i18n_data.json"), "qt_ui"),
]
datas += collect_data_files("easyocr", include_py_files=False)
# PaddleOCR PP-OCRv6 (via RapidOCR + onnxruntime): its models / config ship inside the rapidocr package
datas += collect_data_files("rapidocr", include_py_files=False)
_skip = ("pytorch", "paddle", "openvino", "mnn", "tensorrt", "cli")
rapid = [m for m in collect_submodules("rapidocr") if not any(k in m for k in _skip)]
hidden = collect_submodules("qt_ui") + collect_submodules("gui_server") + [
    "PySide6.QtSvg", "flask", "webview", "adbutils", "uiautomator2", "pyminitouch", "cv2", "numpy", "scipy.signal",
    "psutil", "requests", "loguru", "settings", "stats", "teach", "recorder", "unit_icons", "updater", "version",
    "learn_sync", "capture_session", "today_plan", "army_learn", "village", "screen_memory", "win_capture", "nowindow", "stream_capture", "av", "gpu_setup", "screen_model", "game_digits", "builder_menu", "daily_rewards", "gui_server.telegram_remote", "vision", "paddle_ocr", "screen_cnn", "deploy_zone", "navigator", "clash_api", "deps", "net_check", "spell_brain", "card_bar", "royale", "royale.game", "royale.brain", "royale.eyes", "royale.learn", "royale.strong_eyes", "royale.vision", "royale.vision.constants", "royale.vision.namespaces", "royale.vision.namespaces.cards", "royale.vision.namespaces.units", "royale.vision.namespaces.numbers", "royale.vision.detectors.onnx_detector", "royale.vision.detectors.unit_detector", "royale.vision.detectors.side_detector", "royale.vision.detectors.card_detector", "royale.vision.detectors.number_detector", "scipy.optimize",
    "onnxruntime", "yaml", "omegaconf", "pyclipper", "shapely",
] + rapid

a = Analysis(
    [os.path.join(SPECPATH, "coc_bot_v4_entry.py")],
    pathex=[SRC],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[os.path.join(ROOT, "hooks")],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="CoC_Bot_v4",
    icon=os.path.join(SRC, "qt_ui", "assets", "app_icon.ico"),
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="CoC_Bot_v4")
