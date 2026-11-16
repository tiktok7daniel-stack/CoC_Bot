"""
Bridge between the Qt window and the bot: the bot's local server (gui_server.py) already exposes
everything over HTTP, so the window is a client of it. Calls run on a thread pool and their results
come back on the GUI thread; a Poller keeps state / system / log / stats fresh for every screen.
"""
import json, threading, time, urllib.error, urllib.request

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot


class Api(QObject):
    online_changed = Signal(bool)

    def __init__(self, port):
        super().__init__()
        self.base = f"http://127.0.0.1:{port}"
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(8)
        self._emitter = _Emitter()
        self._emitter.done.connect(self._deliver)
        self.online = True

    # ---------------------------------------------------------------- blocking (worker threads only)
    def request(self, method, path, body=None, timeout=15, raw=False):
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
            self._set_online(True)
            if raw: return payload
            return json.loads(payload.decode("utf-8")) if payload else {}
        except urllib.error.HTTPError as e:
            self._set_online(True)
            if raw: return None
            try: return json.loads(e.read().decode("utf-8"))
            except Exception: return {"ok": False, "error": f"http_{e.code}"}
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._set_online(False)
            return None if raw else {"ok": False, "error": "offline", "detail": str(e)}

    def _set_online(self, value):
        if value != self.online:
            self.online = value
            self._emitter.online.emit(value)

    # ---------------------------------------------------------------- async (GUI thread)
    def call(self, method, path, body=None, done=None, raw=False, timeout=15):
        """Run the request on the pool; done(result) is called on the GUI thread."""
        job = _Job(self, method, path, body, done, raw, timeout)
        self.pool.start(job)

    def get(self, path, done=None, raw=False, timeout=15):
        self.call("GET", path, None, done, raw, timeout)

    def post(self, path, body=None, done=None, timeout=30):
        self.call("POST", path, body if body is not None else {}, done, False, timeout)

    @Slot(object, object)
    def _deliver(self, done, result):
        if done is None: return
        try: done(result)
        except RuntimeError: pass # the widget that asked was closed meanwhile

    def connect_online(self, fn):
        self._emitter.online.connect(fn)


class _Emitter(QObject):
    done = Signal(object, object)
    online = Signal(bool)


class _Job(QRunnable):
    def __init__(self, api, method, path, body, done, raw, timeout):
        super().__init__()
        self.api, self.method, self.path, self.body, self.done, self.raw, self.timeout = api, method, path, body, done, raw, timeout
        self.setAutoDelete(True)

    def run(self):
        result = self.api.request(self.method, self.path, self.body, self.timeout, self.raw)
        self.api._emitter.done.emit(self.done, result)


class Poller(QObject):
    """Refreshes the live data every screen shows; one request per kind in flight at a time."""
    state = Signal(dict)
    system = Signal(dict)
    log = Signal(list)
    stats = Signal(dict)
    errors = Signal(list)
    record_status = Signal(dict)

    def __init__(self, api, store):
        super().__init__()
        self.api, self.store = api, store
        self._busy = set()
        self.last = {}
        self.timers = []
        for kind, ms in (("state", 2500), ("system", 3000), ("log", 4000), ("stats", 6000), ("errors", 15000), ("record_status", 2500)):
            t = QTimer(self)
            t.timeout.connect(lambda k=kind: self.refresh(k))
            t.start(ms)
            self.timers.append(t)
        self.watch_recording = False

    def account(self):
        return self.store.account

    def refresh(self, kind):
        if kind in self._busy: return
        acc = self.account()
        if kind != "state" and not acc: return
        if kind == "record_status" and not self.watch_recording: return
        path = {"state": "/api/state", "system": f"/api/system/{acc}", "log": f"/api/log/{acc}?n=800",
                "stats": f"/api/stats/{acc}", "errors": f"/api/errors/{acc}", "record_status": f"/api/record_status/{acc}"}[kind]
        self._busy.add(kind)

        def done(r, kind=kind):
            self._busy.discard(kind)
            if not isinstance(r, dict) or r.get("error") == "offline": return
            self.last[kind] = r
            if kind == "log": self.log.emit(r.get("lines", []))
            elif kind == "errors": self.errors.emit(r.get("items", []))
            else: getattr(self, kind).emit(r)
        self.api.get(path, done)

    def refresh_all(self):
        for kind in ("state", "system", "log", "stats", "errors"): self.refresh(kind)

    def account_state(self, acc=None):
        st = self.last.get("state") or {}
        acc = acc or self.account()
        return next((a for a in st.get("accounts", []) if a.get("id") == acc), {})


def status_key(a, now=None):
    """Same status rules the bot always used: stopped / paused / scheduled / limit / break / error / running / starting / idle."""
    if not a or not a.get("running"): return "stopped"
    s = a.get("status")
    if s in ("paused", "scheduled", "limit", "break", "error"): return s
    if s == "now": return "running"
    if s in ("starting", "", None): return "starting"
    try:
        float(s)
        return "idle"
    except (TypeError, ValueError):
        return "running"


def fmt_num(n):
    if n is None: return "—"
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return str(n)


def fmt_dur(seconds):
    if seconds is None: return "—"
    s = int(max(0, seconds))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


def fmt_ago_ts(ts):
    try: return time.strftime("%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError): return "—"
