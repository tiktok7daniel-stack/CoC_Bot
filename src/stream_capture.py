"""
Live screen: a video stream from the emulator, like scrcpy.

ADB screenshots cost 300-1500 ms each (the phone encodes a PNG, sends it, Python decodes it). Here the emulator
sends a continuous H.264 video (hardware encoded) over one adb socket and a background thread decodes it: the bot
always has the newest picture ready (~30-60 ms old) and looking at the screen costs nothing.
Works with any emulator, also when its window is minimized.

scrcpy-server v1.24 (Apache 2.0, Genymobile) is pushed to /data/local/tmp and started with app_process.
Safe: checked against a real ADB screenshot first and every few minutes; any problem -> the next way (window / ADB).
"""
import socket, struct, sys, threading, time
from pathlib import Path

JAR = "scrcpy-server-v1.24.jar"
REMOTE = f"/data/local/tmp/{JAR}"
RECHECK = 60              # seconds between checks against a real screenshot
REST = 90
STALE = 1.5               # seconds without a new stream picture -> use a real screenshot

_S = {"client": None, "ok_until": 0.0, "off_until": 0.0, "logged": None, "setting_t": 0.0, "setting": True, "starts": 0}
_LOCK = threading.Lock()


def _log(msg, level="info"):
    try:
        from utils import logger
        getattr(logger, level)(msg)
    except Exception:
        pass


JAR_SHA256 = "ae74a81ea79c0dc7250e586627c278c0a9a8c5de46c9fb5c38c167fb1a36f056"
JAR_URLS = ("https://github.com/Genymobile/scrcpy/releases/download/v1.24/scrcpy-server-v1.24",
            "https://raw.githubusercontent.com/tiktok7daniel-stack/CoC_Bot/ccr-d344ab20-onpy71/assets/scrcpy/" + JAR)
OWN_JAR = Path.home() / ".CoC_Bot" / "scrcpy" / JAR


def _good(p):
    import hashlib
    try: return p.exists() and hashlib.sha256(p.read_bytes()).hexdigest() == JAR_SHA256
    except OSError: return False


def _jar_path():
    """The stream server file: shipped with the program, else the bot's own copy (downloaded once when missing:
    an antivirus can remove a .jar file, an update can miss it). Checked by its fingerprint."""
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        p = base / "assets" / "scrcpy" / JAR
        if _good(p): return p
    if _good(OWN_JAR): return OWN_JAR
    try:
        import requests
        OWN_JAR.parent.mkdir(parents=True, exist_ok=True)
        for url in JAR_URLS:
            try:
                r = requests.get(url, timeout=30)
                if r.status_code != 200: continue
                tmp = OWN_JAR.with_suffix(".part")
                tmp.write_bytes(r.content)
                import os
                os.replace(tmp, OWN_JAR)
                if _good(OWN_JAR):
                    _S.update(fails_n=0, off_until=0.0)      # don't keep waiting from the earlier failures
                    _log("Live screen: its server file was missing — downloaded it again")
                    return OWN_JAR
            except Exception:
                continue
    except Exception:
        pass
    return None


def _enabled():
    if time.time() - _S["setting_t"] > 30:
        _S["setting_t"] = time.time()
        try:
            import settings
            _S["setting"] = settings.load_app().get("live_stream", True) is not False
        except Exception:
            _S["setting"] = True
    return _S["setting"]


class Stream:
    """One running scrcpy video stream; .latest() -> newest RGB picture."""

    def __init__(self, device, bitrate=12_000_000, max_fps=60):
        self.device, self.bitrate, self.max_fps = device, bitrate, max_fps
        self.sock, self.shell = None, None
        self.alive = False
        self.frame = None            # newest decoded av.VideoFrame (converted to an array only when asked)
        self.frame_t = 0.0
        self.frames = 0
        self.size = None
        self.error = None
        self._arr, self._arr_of = None, None

    def start(self, timeout=6.0):
        try:
            import av  # noqa: F401  (the video decoder: fail here, clearly, when it isn't installed)
        except ImportError:
            import deps                          # not installed (an update can't bring it): installs itself now
            deps.ensure("av", ["av"], on_done=lambda: _S.update(off_until=0.0, fails_n=0))
            raise
        from adbutils import Network
        jar = _jar_path()
        if jar is None: raise FileNotFoundError("scrcpy-server jar missing")
        try: self.device.shell("pkill -f com.genymobile.scrcpy.Server", timeout=5)
        except Exception: pass
        self.device.sync.push(str(jar), REMOTE)
        cmd = (f"CLASSPATH={REMOTE} app_process / com.genymobile.scrcpy.Server 1.24 log_level=error "
               f"bit_rate={self.bitrate} max_size=0 max_fps={self.max_fps} lock_video_orientation=-1 tunnel_forward=true "
               "control=false display_id=0 show_touches=false stay_awake=false clipboard_autosync=false "
               "power_off_on_close=false downsize_on_error=true cleanup=true send_device_meta=true send_frame_meta=true "
               "send_dummy_byte=true")
        self.shell = self.device.shell(cmd, stream=True)
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = self.device.create_connection(Network.LOCAL_ABSTRACT, "scrcpy")
                break
            except Exception:
                if time.time() > deadline: raise ConnectionError("scrcpy server did not answer")
                time.sleep(0.1)
        self.sock.settimeout(timeout)
        if self._recv(1) != b"\x00": raise ConnectionError("no dummy byte")
        self._recv(64)                                            # device name
        w, h = struct.unpack(">HH", self._recv(4))
        self.size = (w, h)
        self.sock.settimeout(1.0)
        self.alive = True
        threading.Thread(target=self._loop, daemon=True, name="live-screen").start()
        return self

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk: raise ConnectionError("stream closed")
            buf += chunk
        return buf

    def _loop(self):
        """Every packet comes with a 12-byte header (pts + size): decoded the moment it arrives, no waiting for the next."""
        import av
        codec = av.CodecContext.create("h264", "r")
        try: codec.thread_type = "SLICE"         # slice threads add no delay (frame threads hold pictures back)
        except Exception: pass
        config = b""
        self.sock.settimeout(None)
        while self.alive:
            try:
                head = self._recv(12)
                pts, size = struct.unpack(">QI", head)
                data = self._recv(size)
                if pts & (1 << 63):              # SPS/PPS: goes in front of the next picture
                    config = data
                    continue
                if config:
                    data, config = config + data, b""
                for fr in codec.decode(av.Packet(data)):
                    self.frame, self.frame_t = fr, time.monotonic()
                    self.frames += 1
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                self.alive = False
        self.close()

    def latest(self):
        """Newest picture as RGB array (None before the first frame)."""
        fr = self.frame
        if fr is None: return None
        if self._arr_of is not fr:
            self._arr, self._arr_of = fr.to_ndarray(format="rgb24"), fr
        return self._arr

    def close(self):
        self.alive = False
        for x in (self.sock, self.shell):
            try: x.close()
            except Exception: pass


# ---------------------------------------------------------------- used by Frame_Handler.get_frame
def _small(img):
    import cv2
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(int)


def _client(device):
    c = _S["client"]
    if c is not None and c.alive: return c

    _S["client"] = None
    _S["starts"] += 1
    c = Stream(device).start()
    for _ in range(80):                       # the first picture comes within ~1 s
        if c.frame is not None or not c.alive: break
        time.sleep(0.05)
    if c.frame is None:
        why = c.error or "the emulator sent no picture"
        c.close()
        raise RuntimeError(why)
    _S["client"] = c
    return c


def frame(dims, adb_grab, device):
    """The screen (RGB, size dims) from the live stream, or None -> the caller uses the next way."""
    if not _enabled(): return None
    now = time.time()
    if now < _S["off_until"]: return None
    try:
        import cv2, numpy as np
        with _LOCK:
            c = _client(device)
        img = c.latest()
        if img is None: return None
        # no new picture for a while: the stream may be holding back the last one (a still screen, like the battle
        # results, sends nothing new) -> a real screenshot this time, so the bot never acts on an old picture
        if c.frame_t and time.monotonic() - c.frame_t > STALE:
            _S["stale"] = _S.get("stale", 0) + 1
            return None
        if now > _S["ok_until"]:              # check the stream shows the same as a real screenshot
            # the screenshot takes a moment: compare it with the stream pictures from just before and just after it.
            # While the screen moves (end of battle, loading) the two moments differ anyway: then nothing is decided
            # and the check is done again a few seconds later (a moving screen made it switch the stream off wrongly)
            before = c.latest()
            ref = adb_grab()
            sref = _small(ref)
            near = lambda im: float(np.abs(_small(cv2.resize(im, (ref.shape[1], ref.shape[0]))) - sref).mean())
            ok, moving = False, False
            for _ in range(3):
                img = c.latest()
                if img is None: break
                d = min(near(img), near(before) if before is not None else 999)
                if d < 18:
                    ok = True
                    break
                if before is not None and float(np.abs(_small(cv2.resize(img, (ref.shape[1], ref.shape[0]))) -
                                                       _small(cv2.resize(before, (ref.shape[1], ref.shape[0])))).mean()) > 8:
                    moving = True
                time.sleep(0.15)
            if not ok and moving:
                _S["ok_until"] = now + 5                 # the screen is moving: look again in a moment, keep streaming
            elif not ok:
                _S["mismatch"] = _S.get("mismatch", 0) + 1
                if _S["mismatch"] < 2:                   # once can be a moment of bad luck: check again soon
                    _S["ok_until"] = now + 3
                else:
                    _S["mismatch"] = 0
                    _S["off_until"] = now + REST
                    _S["why"] = "the stream shows something else than the game"
                    if _S["logged"] is not False:
                        _log("Live screen not matching the game right now, using screenshots")
                        _S["logged"] = False
                    return None
            else:
                _S["mismatch"] = 0
            if ok: _S["ok_until"] = now + RECHECK
            _S["why"] = ""
            _S["fails_n"] = 0
            if ok and _S["logged"] is not True:
                _log(f"Live screen on: the emulator streams its screen ({c.size[0]}x{c.size[1]}), every look is instant")
                _S["logged"] = True
        if (img.shape[1], img.shape[0]) != tuple(dims):
            img = cv2.resize(img, tuple(dims), interpolation=cv2.INTER_LINEAR)
        else:
            img = img.copy()
        return img
    except Exception as e:
        _S["fails_n"] = _S.get("fails_n", 0) + 1                # each failure in a row waits longer (max 30 min)
        _S["off_until"] = now + min(1800, REST * 2 ** (_S["fails_n"] - 1))
        _S["why"] = _why(e)
        if _S["logged"] is not False:
            _log(f"Live screen not available: {_why(e)}")
            _S["logged"] = False
        try:
            if _S["client"] is not None: _S["client"].close()
        except Exception:
            pass
        _S["client"] = None
        return None


def _why(e):
    """Short reason in plain words (shown in the app)."""
    t = f"{type(e).__name__}: {e}"
    if isinstance(e, ImportError) or "No module named 'av'" in t: return "the video library (av) is not installed"
    if "jar missing" in t: return "the stream server file is missing"
    if "did not answer" in t: return "the emulator did not start the stream"
    return t[:160]


def stats():
    c = _S["client"]
    return {"on": bool(c and c.alive), "why": _S.get("why", ""), "frames": c.frames if c else 0, "size": c.size if c else None,
            "age_ms": int((time.monotonic() - c.frame_t) * 1000) if c and c.frame_t else None}


def stop():
    c = _S["client"]
    if c is not None: c.close()
    _S["client"] = None
