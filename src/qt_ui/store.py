"""
Settings store: the selected account's settings (S) and the app settings (APP), loaded from and saved
to the bot. Widgets bind to a dotted path ("attack.loot_filter.min_gold"); any change marks the store
dirty and, with auto-save on, saves it shortly after. The bot re-reads its settings every cycle.
"""
import copy, json

from PySide6.QtCore import QObject, QSettings, QTimer, Signal


def get_path(d, path, default=None):
    cur = d
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur: return default
        cur = cur[k]
    return cur


def set_path(d, path, value):
    keys = path.split(".")
    cur = d
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


class Store(QObject):
    loaded = Signal()           # S and APP (re)loaded -> widgets refill
    dirty_changed = Signal(bool)
    saved = Signal(bool, str)   # ok, message
    account_changed = Signal(str)
    accounts_changed = Signal(list)

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.qs = QSettings("CoC_Bot", "CoC_Bot_v4")
        self.S, self.APP = {}, {}
        self._saved_S, self._saved_APP = "", ""
        self.account = str(self.qs.value("account", "") or "")
        self.bindings = []      # (scope, path, setter)
        self._filling = False
        self.dirty = False
        self.autosave = str(self.qs.value("autosave", "true")).lower() == "true"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.save(silent=True))
        self._listeners = []

    # ---------------------------------------------------------------- load
    def load_all(self, done=None):
        def got_app(app):
            if not isinstance(app, dict) or app.get("error") == "offline":
                if done: done(False)
                return
            app.pop("platform", None); app.pop("platform_hint", None); app.pop("warning", None)
            self.APP = app
            self._saved_APP = json.dumps(app, sort_keys=True)
            accounts = app.get("accounts", []) or ["main"]
            if self.account not in accounts: self.account = accounts[0]
            self.accounts_changed.emit(list(accounts))
            self._load_settings(done)
        self.api.get("/api/app_settings", got_app)

    def _load_settings(self, done=None):
        acc = self.account

        def got(s):
            if not isinstance(s, dict) or s.get("error"):
                if done: done(False)
                return
            self.S = s
            self._saved_S = json.dumps(s, sort_keys=True)
            self._set_dirty(False)
            self.fill()
            self.loaded.emit()
            if done: done(True)
        self.api.get(f"/api/settings/{acc}", got)

    def switch_account(self, acc):
        if acc == self.account: return
        if self.dirty: self.save(silent=True)
        self.account = acc
        self.qs.setValue("account", acc)
        self.account_changed.emit(acc)
        self._load_settings()

    def reload(self):
        self.load_all()

    # ---------------------------------------------------------------- values
    def data(self, scope):
        return self.APP if scope == "app" else self.S

    def get(self, path, default=None, scope="s"):
        return get_path(self.data(scope), path, default)

    def set(self, path, value, scope="s"):
        if self._filling: return
        set_path(self.data(scope), path, value)
        self.changed()

    def changed(self):
        """Something in S / APP was edited in place."""
        if self._filling: return
        now = json.dumps(self.S, sort_keys=True) != self._saved_S or json.dumps(self.APP, sort_keys=True) != self._saved_APP
        self._set_dirty(now)
        for fn in list(self._listeners):
            try: fn()
            except RuntimeError: self._listeners.remove(fn)
        if now and self.autosave: self._timer.start(1200)

    def on_change(self, fn):
        self._listeners.append(fn)

    def _set_dirty(self, v):
        if v != self.dirty:
            self.dirty = v
            self.dirty_changed.emit(v)

    def set_autosave(self, v):
        self.autosave = bool(v)
        self.qs.setValue("autosave", "true" if v else "false")
        if v and self.dirty: self._timer.start(300)

    # ---------------------------------------------------------------- bindings
    def bind(self, scope, path, setter):
        """setter(value) puts a value into the widget; returns nothing. Called on every (re)load."""
        self.bindings.append((scope, path, setter))
        if self.data(scope):
            self._filling = True
            try: setter(get_path(self.data(scope), path))
            finally: self._filling = False

    def fill(self):
        self._filling = True
        try:
            alive = []
            for scope, path, setter in self.bindings:
                try:
                    setter(get_path(self.data(scope), path))
                    alive.append((scope, path, setter))
                except RuntimeError: # widget deleted
                    pass
            self.bindings = alive
        finally:
            self._filling = False

    @property
    def filling(self):
        return self._filling

    # ---------------------------------------------------------------- save
    def save(self, silent=False, done=None):
        self._timer.stop()
        acc = self.account
        S = copy.deepcopy(self.S)
        APP = copy.deepcopy(self.APP)

        def got_app(app):
            if not isinstance(app, dict) or app.get("error") == "offline":
                self.saved.emit(False, "save_err")
                if done: done(False)
                return
            warn = app.pop("warning", None)
            app.pop("platform", None)
            self.APP.update(app)
            self._saved_APP = json.dumps(self.APP, sort_keys=True)
            self._set_dirty(json.dumps(self.S, sort_keys=True) != self._saved_S)
            self.accounts_changed.emit(list(self.APP.get("accounts", [])))
            self.saved.emit(True, warn or ("" if silent else "saved"))
            if done: done(True)

        def got_s(s):
            if not isinstance(s, dict) or s.get("error"):
                self.saved.emit(False, "save_err")
                if done: done(False)
                return
            self._saved_S = json.dumps(S, sort_keys=True)
            lead = s.get("follow") or ""
            if lead and json.dumps({k: v for k, v in S.items() if k not in ("follow", "clash_tag")}, sort_keys=True) != \
                    json.dumps({k: v for k, v in s.items() if k not in ("follow", "clash_tag")}, sort_keys=True):
                # this account plays like another: its settings are that account's (shown again, nothing lost there)
                self.S = s
                self._saved_S = json.dumps(s, sort_keys=True)
                self.saved.emit(True, "follow_note")
                self._load_settings()                       # the screens show what the account really plays
            self.api.post("/api/app_settings", APP, got_app)
        if not acc:
            self.api.post("/api/app_settings", APP, got_app)
        else:
            self.api.post(f"/api/settings/{acc}", S, got_s)

    def save_blocking(self):
        """Save right now on the calling thread (window closing: the process ends right after)."""
        self._timer.stop()
        if self.account: self.api.request("POST", f"/api/settings/{self.account}", self.S, timeout=10)
        self.api.request("POST", "/api/app_settings", self.APP, timeout=10)
        self._saved_S = json.dumps(self.S, sort_keys=True)
        self._saved_APP = json.dumps(self.APP, sort_keys=True)
        self._set_dirty(False)

    def discard(self):
        self.load_all()
