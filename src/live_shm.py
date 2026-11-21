"""
The live game picture shared between the bot and the app at the stream's own speed (5.90): no files, no JPEG, no
copy through the disk — the bot's video thread (stream_capture) writes every decoded picture into one block of
shared memory, the app's Live AI screen reads the newest one up to 60 times a second.

Only while someone watches: the app touches WATCH every second while the screen is open; the bot skips the work
otherwise. A sequence number around each write (odd while writing) keeps a half-written picture from being shown.
"""
import struct, time
from pathlib import Path

NAME = "clashfarmer_live_screen"
MAX_W, MAX_H = 1280, 1280
HEAD = struct.Struct("<QIId")             # seq, width, height, time of the picture
SIZE = HEAD.size + MAX_W * MAX_H * 3
WATCH = Path.home() / ".CoC_Bot" / "learn" / "live_watch"
_S = {"shm": None, "seq": 0, "watch_t": 0.0, "watching": False}


def watching():
    """Is the app's Live AI screen open? (checked at most twice a second)"""
    now = time.monotonic()
    if now - _S["watch_t"] > 0.5:
        _S["watch_t"] = now
        try: _S["watching"] = time.time() - WATCH.stat().st_mtime < 3.0
        except OSError: _S["watching"] = False
    return _S["watching"]


def touch():
    """The app: "I am watching" (call every second while the screen is open)."""
    try:
        WATCH.parent.mkdir(parents=True, exist_ok=True)
        WATCH.write_bytes(b"1")
    except OSError:
        pass


def _block(create):
    from multiprocessing import shared_memory
    if _S["shm"] is not None: return _S["shm"]
    kw = {"track": False} if "track" in shared_memory.SharedMemory.__init__.__code__.co_varnames else {}
    try:
        _S["shm"] = shared_memory.SharedMemory(name=NAME, create=False, **kw)
    except FileNotFoundError:
        if not create: return None
        _S["shm"] = shared_memory.SharedMemory(name=NAME, create=True, size=SIZE, **kw)
    return _S["shm"]


def publish(rgb):
    """The bot: one RGB picture (h, w, 3 uint8) into the shared block."""
    try:
        h, w = rgb.shape[:2]
        if w > MAX_W or h > MAX_H: return False
        shm = _block(True)
        buf = shm.buf
        _S["seq"] += 1
        seq = _S["seq"] * 2
        HEAD.pack_into(buf, 0, seq + 1, w, h, time.time())        # odd: being written
        n = w * h * 3
        buf[HEAD.size:HEAD.size + n] = rgb.reshape(-1).tobytes() if not rgb.flags["C_CONTIGUOUS"] else rgb.data.cast("B")
        HEAD.pack_into(buf, 0, seq, w, h, time.time())
        return True
    except Exception:
        return False


def read(last_seq=0):
    """The app: (seq, width, height, bytes) of the newest picture when newer than last_seq, else None."""
    try:
        shm = _block(False)
        if shm is None: return None
        buf = shm.buf
        seq, w, h, _t = HEAD.unpack_from(buf, 0)
        if seq == last_seq or seq & 1 or not w or not h: return None
        data = bytes(buf[HEAD.size:HEAD.size + w * h * 3])
        if HEAD.unpack_from(buf, 0)[0] != seq: return None          # written over while copying: next time
        return seq, w, h, data
    except Exception:
        _S["shm"] = None
        return None
