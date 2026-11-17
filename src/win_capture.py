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
                    (u.GetClassNameW, [H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                    (u.GetWindowTextW, [H, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                    (u.IsWindowVisible, [H], wintypes.BOOL),
                    (g.CreateCompatibleDC, [H], H), (g.CreateCompatibleBitmap, [H, ctypes.c_int, ctypes.c_int], H),
                    (g.SelectObject, [H, H], H), (g.DeleteObject, [H], wintypes.BOOL), (g.DeleteDC, [H], wintypes.BOOL),
                    (g.BitBlt, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, H, ctypes.c_int, ctypes.c_int, wintypes.DWORD], wintypes.BOOL),
                    (g.GetDIBits, [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT], ctypes.c_int)):
        f.argtypes, f.restype = a, r
    return u, g


def _from_ldconsole():
    """LDPlayer's render window from 'ldconsole list2' (bind window / child of the main window), or None."""
    try:
        import utils
        idx = utils.LDPlayer.index
        for line in utils.LDPlayer._run("list2").splitlines():
            c = line.strip().split(",")
            if len(c) < 4 or not c[0].strip().isdigit() or idx is None or int(c[0]) != int(idx): continue
            top, bind = int(c[2] or 0), int(c[3] or 0)
            if bind: return bind
            if top: return _render_child(top) or top
    except Exception:
        pass
    return None


def _render_child(top):
    """The game's render window inside an LDPlayer main window (class RenderWindow / title TheRender), the biggest."""
    import ctypes
    from ctypes import wintypes
    u, _g = _api()
    found = []
    buf = ctypes.create_unicode_buffer(256)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p)
    def each(h, _l):
        u.GetClassNameW(h, buf, 256)
        cls = buf.value
        u.GetWindowTextW(h, buf, 256)
        if cls == "RenderWindow" or buf.value in ("TheRender", "RenderWindow"):
            r = wintypes.RECT()
            u.GetClientRect(h, ctypes.byref(r))
            found.append(((r.right - r.left) * (r.bottom - r.top), h))
        return True
    u.EnumChildWindows(ctypes.c_void_p(top), each, 0)
    return max(found)[1] if found else None


def _scan():
    """Every LDPlayer window open on the PC -> [render window or main window], the bot's own instance first.
    Works whatever ldconsole says (another LDPlayer version installed, renamed instance…)."""
    import ctypes
    from ctypes import wintypes
    u, _g = _api()
    tops = []
    buf = ctypes.create_unicode_buffer(256)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p)
    def each(h, _l):
        if not u.IsWindowVisible(h): return True
        u.GetClassNameW(h, buf, 256)
        cls = buf.value
        u.GetWindowTextW(h, buf, 256)
        title = buf.value
        if cls in ("LDPlayerMainFrame", "LDMultiPlayerMainFrame") or title.lower().startswith(("ldplayer", "雷电")):
            if "multi" not in cls.lower(): tops.append((title, h))
        return True
    u.EnumWindows(each, 0)
    try:
        import utils
        want = str(getattr(utils, "INSTANCE_ID", "") or "").lower()
    except Exception:
        want = ""
    tops.sort(key=lambda t: 0 if want and want in t[0].lower() else 1)
    return [(_render_child(h) or h) for _t, h in tops]


def _candidates():
    out = []
    for h in [_from_ldconsole()] + (_scan() if sys.platform == "win32" else []):
        if h and h not in out: out.append(h)
    return out


def _find_hwnd():
    """The window that was checked to show the game (pinned), else the best guess."""
    if _S["hwnd"] and time.time() - _S["hwnd_t"] < 600:
        try:
            u, _g = _api()
            if u.IsWindow(_S["hwnd"]): return _S["hwnd"]
        except Exception:
            pass
    c = _candidates()
    _S["hwnd"], _S["hwnd_t"] = (c[0] if c else None), time.time()
    return _S["hwnd"]


def grab(hwnd, method=None):
    """RGB picture of the window's inside, or None. method: "pw2" / "pw3" (PrintWindow), "screen" (copy from the screen)."""
    method = method or _S.get("method") or "pw3"
    if method == "screen": return _grab_screen(hwnd)
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
        if not u.PrintWindow(hwnd, mdc, 2 if method == "pw2" else 3):  # PW_RENDERFULLCONTENT (| PW_CLIENTONLY)
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


def _grab_screen(hwnd):
    """Copy the window's area from the screen (works for any drawing, needs the window visible on top)."""
    import ctypes, numpy as np
    from ctypes import wintypes
    u, g = _api()
    if not hwnd or not u.IsWindow(hwnd) or u.IsIconic(hwnd): return None
    r = wintypes.RECT()
    u.GetClientRect(hwnd, ctypes.byref(r))
    pt = wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(pt))
    w, h = r.right, r.bottom
    if w < 200 or h < 100: return None
    sdc = u.GetDC(None)
    mdc = g.CreateCompatibleDC(sdc)
    bmp = g.CreateCompatibleBitmap(sdc, w, h)
    old = g.SelectObject(mdc, bmp)
    try:
        g.BitBlt(mdc, 0, 0, w, h, sdc, pt.x, pt.y, 0x00CC0020)
        class BMI(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        bmi = BMI(ctypes.sizeof(BMI), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = (ctypes.c_ubyte * (w * h * 4))()
        if not g.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0): return None
        return np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)[..., 2::-1].copy()
    finally:
        g.SelectObject(mdc, old)
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(None, sdc)


def _trim(img):
    """Cut black bars around the game (window wider / taller than the game)."""
    import numpy as np
    if img is None: return None
    g = img.max(axis=2)
    rows = np.where(g.max(axis=1) > 12)[0]
    cols = np.where(g.max(axis=0) > 12)[0]
    if len(rows) < 50 or len(cols) < 50: return img
    return img[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


# ---------------------------------------------------------------- checked against ADB
def _small(img):
    import cv2
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(int)


def _agrees(adb_frame):
    """Try every way of copying the window; keep the first that shows what ADB shows. Sets _S["why"] otherwise."""
    import numpy as np
    cands = _candidates()
    if not cands:
        _S["why"] = "LDPlayer window not found"
        return False
    reasons = []
    u, _g = _api()
    for hwnd in cands[:6]:                       # every LDPlayer window: the one showing the game wins
        try:
            if u.IsIconic(hwnd) or u.IsIconic(u.GetParent(hwnd) or hwnd):
                reasons.append("minimized")
                continue
        except Exception:
            pass
        for method in ("pw3", "pw2", "screen"):
            win = _trim(grab(hwnd, method))
            if win is None:
                reasons.append(f"{method}: nothing")
                continue
            if float(win[::8, ::8].std()) < 3:
                reasons.append(f"{method}: black")
                continue
            d = float(np.abs(_small(win) - _small(adb_frame)).mean())
            if d < 18:
                _S["method"], _S["why"] = method, ""
                _S["hwnd"], _S["hwnd_t"] = hwnd, time.time()      # pinned: this window shows the game
                return True
            reasons.append(f"{method}: different ({d:.0f})")
    _S["why"] = ("LDPlayer window is minimized" if reasons and all(r == "minimized" for r in reasons)
                 else f"{len(cands)} window(s): " + "; ".join(reasons[:4]))
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
                _S["fails_n"] = _S.get("fails_n", 0) + 1
                _S["off_until"] = now + min(1800, REST * 2 ** (_S["fails_n"] - 1))
                _S["hwnd"] = None
                if _S["logged"] is not False:
                    _log(f"Fast screen capture not available: {_S.get('why') or '?'}")
                    _S["logged"] = False
                return None
            _S["ok_until"] = now + RECHECK
            _S["fails_n"] = 0
            if _S["logged"] is not True:
                _log("Fast screen capture on: reading the LDPlayer window directly (20-50x faster than ADB)")
                _S["logged"] = True
        img = _trim(grab(_find_hwnd()))
        if img is None or float(img[::8, ::8].std()) < 3:
            _S["fails"] += 1
            if _S["fails"] >= 5:
                _S["fails"], _S["off_until"], _S["ok_until"] = 0, now + REST, 0
            return None
        _S["fails"] = 0
        if (img.shape[1], img.shape[0]) != tuple(dims):
            img = cv2.resize(img, tuple(dims), interpolation=cv2.INTER_LINEAR)
        return img
    except Exception as e:
        _S["off_until"] = now + REST
        _S["why"] = f"{type(e).__name__}: {e}"[:160]
        return None
