"""
The app's own copy of the game screen (5.91): the emulator's compressed video, relayed by the bot as it arrives
(stream_capture, 127.0.0.1:27199), decoded HERE on its own thread — on the graphics card when PyAV can (D3D11 /
CUDA) — so the picture runs at the emulator's own rate (up to 120 a second) and never waits for the bot's work.

Only the newest picture is turned into an image (a slow moment skips pictures instead of falling behind).
"""
import socket, struct, sys, threading, time
from collections import deque

PORT = 27199


class LiveVideo:
    def __init__(self):
        self.img = None              # newest QImage
        self.seq = 0
        self.size = None
        self.hw = False
        self.fps = 0.0
        self.error = ""
        self._want = False
        self._thread = None
        self._taken = 0
        self.arr, self.arr_seq, self.arr_t, self._arr_taken = None, 0, 0.0, 0
        # 6.9.17: the last ~0.6 s of decoded pictures with the time each arrived — the screen can show the picture the
        # bot's eyes looked at, so every box sits on its unit (take_at)
        self.buf = deque(maxlen=160)
        self._bseq = 0

    def start(self):
        self._want = True
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, daemon=True, name="live-video")
            self._thread.start()

    def stop(self):
        self._want = False

    def take(self, last_seq):
        """(seq, QImage) when newer than last_seq, else None."""
        if self.seq == last_seq or self.img is None: return None
        self._taken = self.seq
        return self.seq, self.img

    def take_at(self, t, last_key):
        """The newest picture that arrived at or before wall-clock time t -> (key, QImage, its time) or None when it is
        the one already shown / none is buffered (hardware decoding keeps no buffer: take() is used then)."""
        from PySide6.QtGui import QImage
        pick = None
        for item in reversed(list(self.buf)):
            if item[0] <= t:
                pick = item; break
        if pick is None: return None
        ts, key, fr = pick
        if key == last_key: return None
        try:
            arr = fr.to_ndarray(format="rgb24")
        except Exception:
            return None
        h, w = arr.shape[:2]
        return key, QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy(), ts

    def latest_array(self):
        """(seq, RGB array, monotonic time it was decoded) of the newest picture — for the screen's own eyes."""
        if self.arr is None: return None
        self._arr_taken = self.arr_seq
        return self.arr_seq, self.arr, self.arr_t

    def _codec(self):
        import av
        try:
            from av.codec.hwaccel import HWAccel
            for dev in (("d3d11va", "cuda") if sys.platform == "win32" else ("cuda", "vaapi")):
                try:
                    c = av.CodecContext.create("h264", "r", hwaccel=HWAccel(device_type=dev, allow_software_fallback=True))
                    self.hw = dev
                    return c
                except Exception:
                    pass
        except Exception:
            pass
        c = av.CodecContext.create("h264", "r")
        try: c.thread_type = "SLICE"
        except Exception: pass
        self.hw = False
        return c

    def _run(self):
        from PySide6.QtGui import QImage
        while self._want:
            sock = None
            try:
                import av
                sock = socket.create_connection(("127.0.0.1", PORT), timeout=2.0)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
                sock.settimeout(3.0)
                codec = self._codec()
                config, n, t0 = b"", 0, time.monotonic()

                def recv(k):
                    buf = bytearray()
                    while len(buf) < k:
                        ch = sock.recv(k - len(buf))
                        if not ch: raise ConnectionError("closed")
                        buf += ch
                    return bytes(buf)
                while self._want:
                    pts, size = struct.unpack(">QI", recv(12))
                    data = recv(size)
                    if pts & (1 << 63):
                        config = data
                        continue
                    if config: data, config = config + data, b""
                    try:
                        frames = codec.decode(av.Packet(data))
                        bad = 0
                    except Exception:
                        # joined in the middle of the video: pictures before the next key picture (at most 1 s)
                        # cannot be decoded — skipped, not a reason to drop the connection (5.94)
                        bad = locals().get("bad", 0) + 1
                        if bad > 400: raise
                        if self.hw and bad > 200:
                            codec = av.CodecContext.create("h264", "r"); self.hw = False
                        continue
                    for fr in frames:
                        n += 1
                        if not self.hw:                     # 6.9.17: kept for the synced screen (software frames only)
                            now_w = time.time()
                            self._bseq += 1
                            self.buf.append((now_w, self._bseq, fr))
                            while self.buf and now_w - self.buf[0][0] > 0.6: self.buf.popleft()
                        if self._taken != self.seq and self.img is not None:
                            continue                # the screen has not shown the last one yet: skip converting
                        tc = time.perf_counter()
                        arr = fr.to_ndarray(format="rgb24")
                        if self.hw:              # bringing a picture back from the card can cost more than
                            ms = (time.perf_counter() - tc) * 1000          # decoding it here (720p is light):
                            self._ema = 0.9 * getattr(self, "_ema", ms) + 0.1 * ms      # measured, then chosen
                            self._hw_n = getattr(self, "_hw_n", 0) + 1
                            if self._hw_n > 60 and self._ema > 4.0:
                                codec = av.CodecContext.create("h264", "r")
                                try: codec.thread_type = "SLICE"
                                except Exception: pass
                                self.hw = False
                        h, w = arr.shape[:2]
                        self.arr, self.arr_t = arr, time.monotonic()
                        self.arr_seq += 1
                        self.img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
                        self.size = (w, h)
                        self.seq += 1
                    if time.monotonic() - t0 >= 1.0:
                        self.fps, n, t0 = n / (time.monotonic() - t0), 0, time.monotonic()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"[:120]
                time.sleep(1.0)
            finally:
                if sock is not None:
                    try: sock.close()
                    except Exception: pass
