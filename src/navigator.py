"""
The screen map navigator: the bot knows every screen Claude mapped (knowledge/map.json in the learning repo, a copy
ships in assets/screen_map.json), where it is now (the two screen brains + the colour checks), and goes anywhere by
the shortest path — checking after every tap that it arrived where it should.

  where()          -> the screen now ("village_home", "army_screen"…) or None
  go("army_screen") -> True when it got there

The map: every screen with its buttons (x, y fractions) and how to open it (["village_home.battle"] = from the
village tap "battle"). Close / return / continue / claim buttons lead back to the village. Buttons whose name says
NEVER (magic items, gems, paid offers) are never part of a path. A screen it doesn't know on the way: the picture
goes to Claude (automatic learning) and the bot tries the way home.
"""
import collections, json, sys, time
from pathlib import Path

LOCAL = Path.home() / ".CoC_Bot" / "learn" / "map.json"
HOME = "village_home"
# the screen brain's names (screens.json rules) -> the map's names
ALIAS = {"village_building_selected": "building_selected", "reward_item_continue": "reward_item",
         "battle_result_claim": "battle_result"}
BACK_WORDS = ("close", "return", "continue", "claim", "chest", "okay", "cancel")
_M = {"t": 0.0, "map": None}


def _files():
    out = [LOCAL]
    for base in ([Path(sys._MEIPASS)] if hasattr(sys, "_MEIPASS") else []) + [Path(__file__).resolve().parent.parent]:
        out.append(base / "assets" / "screen_map.json")
    return out


def load(force=False):
    if not force and _M["map"] is not None and time.time() - _M["t"] < 120: return _M["map"]
    for p in _files():
        try:
            _M.update(map=json.loads(p.read_text(encoding="utf-8")), t=time.time())
            return _M["map"]
        except (OSError, ValueError):
            continue
    _M.update(map={}, t=time.time())
    return _M["map"]


def _safe(name):
    n = name.lower()
    return "never" not in n and "gem" not in n and "buy" not in n and "€" not in n


def _button(screen, name):
    s = load().get(screen) or {}
    for group in ("buttons", "tabs"):
        b = (s.get(group) or {}).get(name)
        if isinstance(b, (list, tuple)) and len(b) >= 2: return float(b[0]), float(b[1])
    return None


def edges():
    """{screen: [(next screen, button name, (x, y))]} from the map."""
    m = load()
    out = collections.defaultdict(list)
    for target, s in m.items():
        if not isinstance(s, dict): continue
        steps = s.get("how_to_open") or []
        if steps:                                        # only the last step leads into it; earlier ones are a path
            prev = HOME
            for st in steps:
                if isinstance(st, str) and "." in st:
                    scr, btn = st.split(".", 1)
                    xy = _button(scr, btn)
                    nxt = target if st is steps[-1] else None
                    if xy and _safe(btn):
                        if nxt is None:                  # a middle step: which screen does it open? (the one opened by it)
                            nxt = next((k for k, v in m.items() if isinstance(v, dict) and
                                        (v.get("how_to_open") or [None])[-1] == st), None)
                        if nxt: out[scr].append((nxt, btn, xy))
                    prev = scr
                elif isinstance(st, (list, tuple)) and len(st) >= 3 and isinstance(st[1], (int, float)):
                    if _safe(str(st[0])) and st is steps[-1]: out[prev].append((target, str(st[0]), (float(st[1]), float(st[2]))))
        if target != HOME:                               # the way back
            for group in ("buttons",):
                for name, xy in (s.get(group) or {}).items():
                    if (isinstance(xy, (list, tuple)) and len(xy) >= 2 and _safe(name)
                            and any(w in name.lower() for w in BACK_WORDS)):
                        out[target].append((HOME, name, (float(xy[0]), float(xy[1]))))
            if s.get("close") and isinstance(s["close"], (list, tuple)):
                out[target].append((HOME, "close", (float(s["close"][0]), float(s["close"][1]))))
    return out


def path(frm, to):
    """Shortest list of (button, (x, y), next screen) from frm to to, or None."""
    if frm == to: return []
    E = edges()
    q = collections.deque([frm])
    prev = {frm: None}
    while q:
        cur = q.popleft()
        for nxt, btn, xy in E.get(cur, []):
            if nxt in prev: continue
            prev[nxt] = (cur, btn, xy)
            if nxt == to:
                out, k = [], to
                while prev[k] is not None:
                    c, b, p = prev[k]
                    out.append((b, p, k))
                    k = c
                return out[::-1]
            q.append(nxt)
    return None


def where(frame=None):
    """The screen now (map name) or None."""
    import utils
    try:
        if utils.in_home_base(): return HOME
    except Exception:
        pass
    try:
        import screen_model
        if frame is None: frame = utils.Frame_Handler.get_frame(grayscale=False)
        label, _d = screen_model.classify(frame, utils.INSTANCE_ID)
        if label: return ALIAS.get(label, label)
    except Exception:
        pass
    return None


def go(target, max_steps=8, logger=None):
    """Go to `target` by the map -> True when there. Unknown screens on the way: sent to Claude, then home first."""
    import utils
    log = logger or utils.logger
    for _ in range(max_steps):
        frame = utils.Frame_Handler.get_frame(grayscale=False)
        cur = where(frame)
        if cur == target: return True
        if cur is None:                                  # lost: Claude gets the picture, the old way home is tried
            try:
                import learn_sync
                learn_sync.report_unknown(utils.INSTANCE_ID, frame, f"navigate:{target}")
            except Exception:
                pass
            try: utils.Auto_Learn.handle_unknown_screen(f"navigate:{target}")
            except Exception: pass
            time.sleep(0.8)
            continue
        p = path(cur, target) if target != HOME or cur != HOME else []
        if p is None and cur != HOME: p = path(cur, HOME)       # no way from here: home first
        if not p:
            log.info(f"Map: no way from {cur} to {target}")
            return False
        btn, (x, y), nxt = p[0]
        log.debug(f"Map: {cur} -> {nxt} ({btn})")
        try:
            import screen_memory
            h = screen_memory.fingerprint(frame)
        except Exception:
            h = None
        utils.Input_Handler.click(x, y)
        try:                                             # wait until the screen changed (up to 3 s)
            if h is not None: screen_memory.changed(h, wait=3.0, tries=12)
            else: time.sleep(1.0)
        except Exception:
            time.sleep(1.0)
        time.sleep(0.3)
    return where() == target
