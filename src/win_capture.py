"""
Fast screen grab straight from the LDPlayer window (Windows only).

Over ADB a screenshot takes 300-1500 ms (the emulator encodes the picture, sends it through the adb socket, Python
decodes it). LDPlayer draws the game in its own render window on the PC: copying that window's pixels with
PrintWindow takes ~5-20 ms, so the bot can look at the screen 20-50x more often.

Safe by design:
 - checked against a real ADB screenshot first (and again every few minutes): only used while both agree
 - a black / empty picture (window minimized) -> that look goes over ADB, after a few in a row the fast way rests
 - any error -> ADB, as before
"""
import sys, time

_S = {"hwnd": None, "hwnd_t": 0.0, "ok_until": 0.0, "off_until": 0.0, "fails": 0, "logged": None, "setting_t": 0.0, "setting": True}
RECHECK = 300          # seconds between checks against ADB
REST = 120             # seconds to rest the fast way after it failed


def _log(msg):
    try:
        from utils import logger
        logger.info(msg)
    except Exception:
        pass


def _enabled():
    if time.time() - _S["setting_t"] > 30:
        _S["setting_t"] = time.time()
        try:
            import settings
            _S["setting"] = settings.load_app().get("fast_capture", True) is not False
        except Exception:
            _S["setting"] = True
    return _S["setting"]


# ---------------------------------------------------------------- the window
def _api():
    import ctypes
    from ctypes import wintypes
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    H = ctypes.c_void_p
    for f, a, r in ((u.GetDC, [H], H), (u.ReleaseDC, [H, H], ctypes.c_int), (u.GetClientRect, [H, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
                    (u.PrintWindow, [H, H, wintypes.UINT], wintypes.BOOL), (u.IsIconic, [H], wintypes.BOOL), (u.IsWindow, [H], wintypes.BOOL),
                    (u.GetParent, [H], H), (u.FindWindowExW, [H, H, wintypes.LPCWSTR, wintypes.LPCWSTR], H),
                    (g.CreateCompatibleDC, [H], H), (g.CreateCompatibleBitmap, [H, ctypes.c_int, ctypes.c_int], H),
                    (g.SelectObject, [H, H], H), (g.DeleteObject, [H], wintypes.BOOL), (g.DeleteDC, [H], wintypes.BOOL),
                    (g.BitBlt, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
                    (g.GetDIBits, [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT], ctypes.c_int)):
        f.argtypes, f.restype = a, r
    return u, g


def _find_hwnd():
    """LDPlayer's render window ("bind window" in 'ldconsole list2'), else the child of its main window."""
    if _S["hwnd"] and time.time() - _S["hwnd_t"] < 60: return _S["hwnd"]
    hwnd = None
    try:
        import utils
        idx = utils.LDPlayer.index
        for line in utils.LDPlayer._run("list2").splitlines():
            c = line.strip().split(",")
            if len(c) < 4 or not c[0].strip().isdigit() or int(c[0]) != int(idx): continue
            top, bind = int(c[2] or 0), int(c[3] or 0)
            hwnd = bind or None
            if not hwnd and top:
                u, _g = _api()
                for name in ("TheRender", "RenderWindow", None):
                    h = u.FindWindowExW(top, None, None, name) if name else u.FindWindowExW(top, None, "RenderWindow", None)
                    if h: hwnd = h; break
                hwnd = hwnd or top
            break
    except Exception:
        hwnd = None
    _S["hwnd"], _S["hwnd_t"] = hwnd, time.time()
    return hwnd


def grab(hwnd):
    """RGB picture of the window's inside, or None."""
    import ctypes, numpy as np
    from ctypes import wintypes
    u, g = _api()
    if not hwnd or not u.IsWindow(hwnd): return None
    top = u.GetParent(hwnd) or hwnd
    if u.IsIconic(hwnd) or u.IsIconic(top): return None          # minimized: nothing is drawn
    r = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w < 200 or h < 100: return None
    hdc = u.GetDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        if not u.PrintWindow(hwnd, mdc, 3):                            # PW_CLIENTONLY | PW_RENDERFULLCONTENT
            g.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020)
        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        if not g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0): return None
        img = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        return img[..., 2::-1].copy()                                  # BGRA -> RGB
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(hwnd, hdc)


# ---------------------------------------------------------------- checked against ADB
def _small(img):
    import cv2
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(int)


def _agrees(adb_frame):
    import numpy as np
    for _ in range(3):
        win = grab(_find_hwnd())
        if win is None: return False
        d = float(np.abs(_small(win) - _small(adb_frame)).mean())
        if d < 18: return True
        time.sleep(0.15)
    return False


def frame(dims, adb_grab):
    """
    The screen as an RGB picture of size dims (w, h) from the window, or None (then the caller uses ADB).
    adb_grab() -> RGB picture over ADB, used to check that the window shows the same thing.
    """
    if sys.platform != "win32" or not _enabled(): return None
    now = time.time()
    if now < _S["off_until"]: return None
    try:
        import cv2
        if now > _S["ok_until"]:
            ref = adb_grab()
            ref = cv2.resize(ref, tuple(dims), interpolation=cv2.INTER_AREA) if (ref.shape[1], ref.shape[0]) != tuple(dims) else ref
            if not _agrees(ref):
                _S["off_until"] = now + REST
                _S["hwnd"] = None
                if _S["logged"] is not False:
                    _log("Fast screen capture not available right now (LDPlayer window hidden or different), using ADB")
                    _S["logged"] = False
                return None
            _S["ok_until"] = now + RECHECK
            if _S["logged"] is not True:
                _log("Fast screen capture on: reading the LDPlayer window directly (20-50x faster than ADB)")
                _S["logged"] = True
        img = grab(_find_hwnd())
        if img is None or float(img[::8, ::8].std()) < 3:
            _S["fails"] += 1
            if _S["fails"] >= 5:
                _S["fails"], _S["off_until"], _S["ok_until"] = 0, now + REST, 0
            return None
        _S["fails"] = 0
        if (img.shape[1], img.shape[0]) != tuple(dims):
            img = cv2.resize(img, tuple(dims), interpolation=cv2.INTER_LINEAR)
        return img
    except Exception:
        _S["off_until"] = now + REST
        return None
