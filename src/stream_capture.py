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

_S = {"client": None, "ok_until": 0.0, "off_until": 0.0, "logged": None, "setting_t": 0.0, "setting": True, "starts": 0}
_LOCK = threading.Lock()


def _log(msg, level="info"):
    try:
        from utils import logger
        getattr(logger, level)(msg)
    except Exception:
        pass


def _jar_path():
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        p = base / "assets" / "scrcpy" / JAR
        if p.exists(): return p
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
        import av  # noqa: F401  (the video decoder: fail here, clearly, when it isn't installed)
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
        if now > _S["ok_until"]:              # check the stream shows the same as a real screenshot
            ref = adb_grab()
            ok = False
            for _ in range(3):
                img = c.latest()
                if img is not None and float(np.abs(_small(cv2.resize(img, (ref.shape[1], ref.shape[0]))) - _small(ref)).mean()) < 18:
                    ok = True
                    break
                time.sleep(0.15)
            if not ok:
                _S["off_until"] = now + REST
                _S["why"] = "the stream shows something else than the game"
                if _S["logged"] is not False:
                    _log("Live screen not matching the game right now, using screenshots")
                    _S["logged"] = False
                return None
            _S["ok_until"] = now + RECHECK
            _S["why"] = ""
            _S["fails_n"] = 0
            if _S["logged"] is not True:
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
