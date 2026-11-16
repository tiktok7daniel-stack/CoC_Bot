import sys, collections
from pathlib import Path
from functools import lru_cache
from tempfile import template
from log import logger
try:
    import configs
    from configs import *
except:
    import configs_build as configs
    from configs_build import *

if sys.platform == "win32":
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001

APP_DATA_DIR = Path.home() / ".CoC_Bot"
APP_DATA_DIR.mkdir(exist_ok=True)

if getattr(sys, "frozen", False):
    CACHE_PATH = APP_DATA_DIR / "cache.json"
    DEBUG_DIR = APP_DATA_DIR / "debug"
else:
    CACHE_PATH = Path(__file__).parent / "cache.json"
    DEBUG_DIR = Path(__file__).parent.parent / "debug"

INSTANCE_ID = ADB_ADDRESS = None
TEMP_CACHE = {}

def parse_args(debug=None, id=None, gui=None, gui_port=None):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", default=configs.DEBUG, help="Enable debug mode")
    parser.add_argument("--id", type=str, default=None, help="Instance ID")
    parser.add_argument("--gui", action="store_true", default=configs.LOCAL_GUI, help="Run with GUI")
    parser.add_argument("--gui-port", type=int, default=None, help="GUI port")
    parser.add_argument("--ids", type=str, nargs="+", default=None, help="Run several instances (accounts) in parallel")
    parser.add_argument("--all", action="store_true", help="Run every instance in INSTANCE_IDS in parallel")
    args = parser.parse_args()
    if args.all: args.ids = list(configs.INSTANCE_IDS)
    if args.ids is not None:
        for i in args.ids:
            assert i in configs.INSTANCE_IDS, f"Invalid instance ID {i}. Must be one of: {configs.INSTANCE_IDS}"
    configs.DEBUG = args.debug if debug is None else debug
    configs.LOCAL_GUI = args.gui if gui is None else gui
    TEMP_CACHE["gui_port"] = args.gui_port if gui_port is None else gui_port
    if id is not None:
        assert id in configs.INSTANCE_IDS, f"Invalid instance ID. Must be one of: {configs.INSTANCE_IDS}"
        args.id = id
    elif args.id is None and not configs.LOCAL_GUI:
        args.id = configs.DEFAULT_INSTANCE_ID
    return args

def init_instance(id):
    global INSTANCE_ID, ADB_ADDRESS
    import requests
    
    assert id in configs.INSTANCE_IDS, f"Invalid instance ID. Must be one of: {configs.INSTANCE_IDS}"
    INSTANCE_ID = id
    request_perms()
    ADB_ADDRESS = Emulator_Manager.adb_address
    if configs.AUTO_START_EMULATOR: Emulator_Manager.init()
    if WEB_APP_URL != "":
        if "pythonanywhere.com" in WEB_APP_URL:
            Scheduler.add_job(extend_pythonanywhere_hosting, args=(configs.PA_USERNAME, configs.PA_PASSWORD), trigger="interval", hours=24)
            Scheduler.add_job(get_vocab, trigger="interval", hours=24)
        
        try:
            requests.post(
                f"{WEB_APP_URL}/instances",
                json={"id": id},
                timeout=(10, 20)
            )
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("init_instance:")

def disable_sleep():
    import sys, subprocess, ctypes, os, shutil
    
    if sys.platform == "darwin":
        sleep_helper_temp = Path(__file__).parent / "sleep_helper.sh"
        sleep_helper_permanent = APP_DATA_DIR / "sleep_helper.sh"
        shutil.copyfile(sleep_helper_temp, sleep_helper_permanent)
        os.chmod(sleep_helper_permanent, 0o755)
        cmd = f'do shell script "{sleep_helper_permanent} {os.getpid()}" with administrator privileges'
        subprocess.Popen(
            ["osascript", "-e", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    elif sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    else:
        raise Exception("Unsupported OS")
    Exit_Handler.register(enable_sleep)

def enable_sleep():
    import sys, ctypes
    
    if sys.platform == "darwin":
        pass
    elif sys.platform == "win32":
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    else:
        raise Exception("Unsupported OS")

def request_perms():
    if sys.platform == "darwin":
        import time, subprocess, ApplicationServices

        def perms_granted():
            script = 'tell application "System Events" to return UI elements enabled'
            try:
                res = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True,
                    text=True,
                    check=True
                )
                return res.stdout.strip().lower() == "true"
            except subprocess.SubprocessError:
                return False

        if not perms_granted():
            logger.info("Requesting accessibility permissions...")
            ApplicationServices.AXIsProcessTrustedWithOptions({'AXTrustedCheckOptionPrompt': True})
            while not perms_granted(): time.sleep(0.5)
            logger.info("Accessibility permissions granted!")

    elif sys.platform == "win32":
        pass

def require_exit(x=0.99, y=0.99, n=4, delay=0.1):
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = None
            try: result = func(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit): raise
            except: pass
            Input_Handler.click_exit(x, y, n, delay)
            return result
        return wrapper
    return decorator

def to_system_home():
    ADB_Manager.adbutils_device.shell("input keyevent KEYCODE_HOME")

def file_search(root, target_name, keywords=[]):
    if (cached_path := Cache_Manager.get("file_search", {}).get(target_name, None)) is not None:
        return cached_path
    
    keywords = [kw.lower() for kw in keywords]
    root = Path(root).resolve()
    queue = collections.deque([root])
    visited = set([root.resolve()])
    while queue:
        current_dir = queue.popleft()
        
        try:
            for entries in current_dir.iterdir():
                if entries.is_file() and entries.name == target_name:
                    file_path = str(entries.resolve())
                    Cache_Manager.setdefault("file_search", {})[target_name] = file_path
                    return file_path
                
                if entries.is_dir():
                    real_path = entries.resolve()
                    if real_path not in visited:
                        visited.add(real_path)
                        if any(kw in entries.name.lower() for kw in keywords):
                            queue.appendleft(entries)
                        else:
                            queue.append(entries)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            continue
    return None

def online(timeout=1):
    if sys.platform == "darwin":
        try:
            from SystemConfiguration import SCNetworkReachabilityCreateWithName, SCNetworkReachabilityGetFlags
            target = SCNetworkReachabilityCreateWithName(None, b"8.8.8.8")
            flags = SCNetworkReachabilityGetFlags(target, None)[1]
            return bool(flags & 2)
        except Exception:
            return True
    elif sys.platform == "win32":
        try:
            import ctypes
            flags = ctypes.c_ulong()
            if ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0): return True
        except Exception:
            pass
        # Windows sometimes reports "offline" while the internet works (VPN, some adapters): ask the network itself
        import socket
        for host in (("8.8.8.8", 53), ("1.1.1.1", 53)):
            try:
                socket.create_connection(host, timeout=2).close()
                return True
            except OSError:
                continue
        return False
    return True

def running():
    import requests
    # the watchdog found the bot stuck: answer "not running" once so every loop lets go of the step
    if TEMP_CACHE.pop("stuck", False): return False
    
    if WEB_APP_URL == "":
        # desktop GUI: its pause timer lives in the local GUI server
        gui_port = TEMP_CACHE.get("gui_port")
        if gui_port is None: return True
        try:
            r = requests.get(f"http://127.0.0.1:{gui_port}/instances/{INSTANCE_ID}/running", timeout=(1, 2))
            return r.json().get("running", True) if r.status_code == 200 else True
        except Exception:
            return True # GUI unreachable -> don't block the bot
    try:
        response = requests.get(
            f"{WEB_APP_URL}/instances/{INSTANCE_ID}/running",
            timeout=(1, 2)
        )
        if response.status_code == 200:
            return response.json().get("running", False)
        return False
    except Exception as e:
        logger.error(f"running: {e}")
        return False

def click_with_timeout(locator_func, timeout=1, interval=0.1):
    import time
    x, y = locator_func()
    start = time.time()
    while (x is None or y is None) and time.time() - start < timeout:
        time.sleep(interval)
        x, y = locator_func()
    if x is not None and y is not None:
        Input_Handler.click(x, y)
        return True
    return False

def chunk_list(target_list, chunk_sizes):
    chunks = []
    start = 0
    for size in chunk_sizes:
        end = start + size
        chunks.append(target_list[start:end])
        start = end
    return chunks

def check_color(color, frame, tol=10):
    import numpy as np
    assert len(frame.shape) == 3 and frame.shape[2] == 3, "Frame must be a color image"
    diff = np.abs(frame - np.array(color).reshape((1, 1, 3))).sum(2) <= tol
    return np.any(diff)

def filter_color(color, frame, tol=10, return_mask=False):
    import numpy as np
    assert len(frame.shape) == 3 and frame.shape[2] == 3, "Frame must be a color image"
    mask = np.abs(frame - np.array(color).reshape((1, 1, 3))).sum(2) <= tol
    frame_filtered = frame.copy()
    frame_filtered[~mask] = [0, 0, 0]
    if return_mask:
        return frame_filtered, mask
    return frame_filtered

def get_vocab():
    from github import Github
    from pathlib import PurePosixPath

    target_dirs = [
        "buildings/builder-base",
        "buildings/home-village",
        "buildings/seasonal-defense",
        "traps/builder-base",
        "traps/home-village",
        "troops",
        "spells",
        "heroes",
        "guardians",
        "pets",
    ]

    g = Github(timeout=5, retry=None)

    try:
        repo = g.get_repo("ClashKingInc/ClashKingAssets")
    except (KeyboardInterrupt, SystemExit): raise
    except:
        return Cache_Manager.get("vocab", {})

    try:
        branch = repo.get_branch(repo.default_branch)
        tree = repo.get_git_tree(branch.commit.sha, recursive=True)
    except (KeyboardInterrupt, SystemExit): raise
    except Exception: # rate limit / offline: keep the saved list
        return Cache_Manager.get("vocab", {})

    file_structure = [element.path for element in tree.tree]

    parsed_paths = [PurePosixPath(p) for p in file_structure]

    def format_name(file_path):
        return file_path.stem.replace("_", " ").title()

    data = {
        d: [format_name(p) for p in parsed_paths if p.parent == PurePosixPath("assets") / d]
        for d in target_dirs
    }
    
    Cache_Manager["vocab"] = data
    
    return data

VOCAB_DIRS = ["buildings/builder-base", "buildings/home-village", "buildings/seasonal-defense", "traps/builder-base",
              "traps/home-village", "troops", "spells", "heroes", "guardians", "pets"]
_vocab_refreshing = {"busy": False}

def _refresh_vocab():
    import time
    try:
        data = get_vocab()
        if data and any(data.values()):
            Cache_Manager["vocab_time"] = time.time()
            return data
    except (KeyboardInterrupt, SystemExit): raise
    except Exception:
        pass
    finally:
        _vocab_refreshing["busy"] = False
    return None

def vocab():
    """
    Building / troop / hero names (kept up to date with new Town Halls from the ClashKing assets list).
    Uses the saved copy; refreshes from GitHub at most once a day, in the background.
    """
    import time, threading
    data = Cache_Manager.get("vocab")
    if not data:
        data = _refresh_vocab() or {}
    elif time.time() - Cache_Manager.get("vocab_time", 0) > 86400 and not _vocab_refreshing["busy"]:
        _vocab_refreshing["busy"] = True
        threading.Thread(target=_refresh_vocab, daemon=True).start()
    return {d: data.get(d, []) for d in VOCAB_DIRS} | {k: v for k, v in data.items() if k not in VOCAB_DIRS}

def get_vocab_in_categories(categories):
    names = vocab()
    if isinstance(categories, str):
        categories = [categories]
    out = []
    if "all" in categories:
        for cat in names: out.extend(names[cat])
    else:
        for cat in categories:
            if cat in names: out.extend(names[cat])
    return out

def spell_check(text, vocab_categories=["all"], phrase_level=False, cutoff=70):
    import re
    from rapidfuzz import process, distance
    
    def spell_scorer(a, b, score_cutoff=0):
        lev = distance.Levenshtein.distance(a, b)
        length_penalty = abs(len(a) - len(b)) * 0.5
        score = 100 - 10 * (lev + length_penalty)
        return score if score >= score_cutoff else 0
    
    vocab = get_vocab_in_categories(vocab_categories)
    for i in range(len(vocab)): vocab[i] = vocab[i].lower()
    
    keys = []
    if phrase_level:
        keys = [text.lower()]
    else:
        keys = re.split(r"[ _]+", text.lower())
        vocab = " ".join(vocab).split()

    results = []
    for key in keys:
        suggestion = key
        if key not in vocab:
            match = process.extractOne(key, vocab, scorer=spell_scorer, score_cutoff=cutoff)
            if match is not None: suggestion = match[0]
        results.append(suggestion)

    return " ".join(results)

def fix_digits(text):
    if type(text) is list:
        return [fix_digits(t) for t in text]
    return text.lower().replace('o', '0').replace('/', '1').replace('i', '1').replace('z', '2').replace('s', '5').replace('b', '6').replace('j', '7').replace('&', '8')

def parse_time(text):
    import re
    if type(text) is list:
        return [parse_time(t) for t in text]
    try:
        text = text.lower().replace(' ', '').replace('-', '')
        units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
        pattern = re.compile(r"(\d+)([dhms])")
        seconds = sum(int(v) * units[u] for v, u in pattern.findall(text))
        return seconds
    except (KeyboardInterrupt, SystemExit): raise
    except: return 0

def to_int_array(*args):
    import numpy as np
    return np.array(list(map(int, args)))

@lru_cache(maxsize=64)
def _get_font(font, font_size):
    from PIL import ImageFont
    return ImageFont.truetype(Asset_Manager.fonts.get(font), font_size)

_render_cache = {}

def render_text(text, font, font_size, color=(255, 255, 255)):
    """Text image used as a search template. Cached: the same templates are used constantly."""
    key = (text, font, font_size, tuple(color))
    hit = _render_cache.get(key)
    if hit is not None: return hit.copy()
    out = _render_text(text, font, font_size, color)
    if len(_render_cache) > 3000: _render_cache.clear()
    _render_cache[key] = out
    return out.copy()

def _render_text(text, font, font_size, color=(255, 255, 255)):
    import numpy as np
    from PIL import Image, ImageDraw
    
    font = _get_font(font, font_size)
    temp = Image.new("RGB", (1, 1))
    bbox = ImageDraw.Draw(temp).textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    render = Image.new("RGB", (w, h), (0, 0, 0))
    ImageDraw.Draw(render).text((-bbox[0], -bbox[1]), text, font=font, fill=color)
    render = np.array(render)
    return render

def get_telegram_chat_id():
    import requests
    
    telegram_chat_id = Cache_Manager.get("telegram_chat_id", None)
    if telegram_chat_id is not None:
        return telegram_chat_id

    res = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
        timeout=(10, 20)
    )
    if res.status_code == 200:
        res = res.json()
        if res["ok"] and len(res["result"]) > 0:
            chat_id = res["result"][-1]["message"]["chat"]["id"]
            Cache_Manager["telegram_chat_id"] = chat_id
            return chat_id

    raise Exception("Failed to get Telegram chat ID. Please send a message to your bot first.")

def send_notification(text):
    import requests
    
    if WEB_APP_URL != "":
        try:
            requests.post(
                f"{WEB_APP_URL}/instances/{INSTANCE_ID}/notify",
                json=text,
                timeout=(1, 2)
            )
        except (KeyboardInterrupt, SystemExit): raise
        except: pass

    if TELEGRAM_BOT_TOKEN != "":
        try:
            telegram_text = f"[{INSTANCE_ID}]\n{text}"
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": get_telegram_chat_id(),"text": telegram_text},
                timeout=(1, 2)
            )
        except (KeyboardInterrupt, SystemExit): raise
        except: pass

def update_status(status):
    import requests
    
    if WEB_APP_URL != "":
        try:
            requests.post(
                f"{WEB_APP_URL}/instances/{INSTANCE_ID}/status",
                json={"status": status},
                timeout=(1, 2)
            )
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            logger.error(f"update_status: {e}")
    if (gui_port := TEMP_CACHE.get("gui_port")) is not None:
        try:
            requests.post(
                f"http://127.0.0.1:{gui_port}/instances/{INSTANCE_ID}/status",
                json={"status": status},
                timeout=(1, 2)
            )
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            logger.error(f"update_status: {e}")

def extend_pythonanywhere_hosting(username, password):
    import requests
    
    assert "pythonanywhere.com" in WEB_APP_URL
    base_url = "https://www.pythonanywhere.com"
    login_url = f"{base_url}/login/"
    webapps_url = f"{base_url}/user/{username}/webapps/"
    extend_url = f"{base_url}/user/{username}/webapps/{username}.pythonanywhere.com/extend"
    
    headers = {"Referer": base_url}

    session = requests.Session()
    
    # Login
    session.get(login_url)
    session.post(
        login_url,
        data={
            "csrfmiddlewaretoken": session.cookies.get_dict().get("csrftoken"),
            "auth-username": username,
            "auth-password": password,
            "login_view-current_step": "auth",
        },
        headers=headers,
    )
    assert "Log out" in session.get(base_url).text
    
    # Extend hosting
    session.get(webapps_url)
    res = session.post(
        extend_url,
        headers=headers,
        data={"csrfmiddlewaretoken": session.cookies.get_dict().get("csrftoken")},
    )
    assert res.url == webapps_url

def in_home_base():
    import numpy as np

    # First check for resource colors
    section = Frame_Handler.get_frame_section(0.95, 0.02, 1.0, 0.3, grayscale=False)
    resource_sections = [
        Frame_Handler.crop(section, 0.0, 0.25*i, 1.0, 0.25*(i+1)) for i in range(4)
    ]
    target_colors = [
        (255, 242, 85), # gold
        (255, 73, 255), # elixir
        (63, 48, 66), # dark elixir
        (211, 236, 116), # gems
    ]
    # the resource icons (gold, elixir, dark, gems) at the top right; 3 of 4 is enough (an event banner or a
    # different color profile can hide / shift one of them)
    hits = 0
    gems = False
    for i, (sec, color) in enumerate(zip(resource_sections, target_colors)):
        diff = abs(sec.astype(int) - np.array(color).reshape((1, 1, 3))).sum(2)
        if min(diff.flatten()) <= 30:
            hits += 1
            if i == 3: gems = True
    # the gems bar is only shown in the village (a battle shows gold / elixir / dark too, but no gems)
    if hits >= 3 and gems: return True

    # Fallback to gold template matching
    if Frame_Handler.locate(
        Asset_Manager.upgrader_assets["home_gold"],
        grayscale=False,
        prefilter=True,
        thresh=0.80
    ) != (None, None):
        return True
    # last check: read the buttons at the bottom (cached a few seconds, OCR is slow)
    return _village_by_words(colours=hits)


_VILLAGE_WORDS = {"t": 0.0, "ok": False}

def _village_by_words(colours=0):
    import time
    if time.time() - _VILLAGE_WORDS["t"] < 4: return _VILLAGE_WORDS["ok"]
    ok = False
    try:
        # the game's buttons at the bottom corners: "Battle" (older versions "Attack!") on the left, "Build" on the right
        left = Frame_Handler.get_frame_section(0.0, 0.78, 0.18, 1.0, grayscale=False, use_cached=True)
        right = Frame_Handler.get_frame_section(0.84, 0.78, 1.0, 1.0, grayscale=False, use_cached=True)
        lw = [b[0] for b in ocr_boxes(left) if b[5] > 0.3]
        rw = [b[0] for b in ocr_boxes(right) if b[5] > 0.3]
        battle = any(_word_hit(w, "battle") or _word_hit(w, "attack") for w in lw)
        build = any(_word_hit(w, "build") for w in rw)
        # Battle + Build, or Battle + at least one resource colour at the top right (OCR misses small words sometimes)
        ok = battle and (build or colours >= 1)
        # a running battle has "Surrender" at the bottom left instead
        if ok and any(_word_hit(w, "surrender") for w in lw): ok = False
        if ok and not _VILLAGE_WORDS["ok"]: logger.info("Village recognised by the Battle / Build buttons")
    except Exception:
        ok = False
    _VILLAGE_WORDS.update(t=time.time(), ok=ok)
    return ok

def to_home_base(ref_cache=False):
    import cv2, time, numpy as np
    
    if ref_cache and TEMP_CACHE.get("location") == "home_base": return
    
    TEMP_CACHE["location"] = "home_base"
    
    if in_home_base(): return
    
    Input_Handler.zoom(dir="out")
    for _ in range(3):
        Input_Handler.swipe_down(duration=0)
    for _ in range(3):
        Input_Handler.swipe_left(duration=0)
    
    scale_templates = []
    for scale in np.arange(0.43, 0.47, 0.01):
        scale_templates.append(cv2.resize(Asset_Manager.misc_assets["boat_icon"], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST))
    
    for _ in range(5):
        xys = Frame_Handler.batch_locate(scale_templates, grayscale=True, thresh=0.7, ref="cc")
        for x, y in xys:
            if x is None or y is None: continue
            Input_Handler.click(x, y)
            time.sleep(2)
            return
    # couldn't find the way home: something unknown is on the screen
    Auto_Learn.handle_unknown_screen("to_home")

# Storage counters in the top-right corner (fractions of a 1920x1080 frame).
# Each band holds one number; dark elixir only exists in the home village (TH7+).
# Same bars that in_home_base() / in_builder_base() check by colour, minus the icon column.
RESOURCE_BANDS = {
    "gold":   (0.72, 0.020, 0.948, 0.0925),
    "elixir": (0.72, 0.0925, 0.948, 0.165),
    "dark":   (0.72, 0.165, 0.948, 0.2375),
}
BUILDER_RESOURCE_BANDS = {
    "gold":   (0.72, 0.020, 0.948, 0.088),
    "elixir": (0.72, 0.088, 0.948, 0.155),
}
RESOURCE_LIMITS = {"gold": 60_000_000, "elixir": 60_000_000, "dark": 600_000}

def _parse_resource(lines):
    import re
    for line in lines:
        if "max" in line.lower() or ":" in line: continue # "Max: ..." storage-capacity labels
        digits = re.sub(r"[^0-9]", "", fix_digits(line))
        if digits: return int(digits)
    return None

def read_resources(builder_base=False, save_debug=False, samples=3):
    """
    Read the storages several times and keep the value the readings agree on
    (stops after 2 readings when they already match).
    """
    import time
    reads = []
    for i in range(max(1, samples)):
        r = _read_resources_once(builder_base, save_debug)
        if r is not None: reads.append(r)
        if len(reads) >= 2 and reads[-1] == reads[-2]: return reads[-1]
        if i < samples - 1: time.sleep(0.25)
    if not reads: return None
    out = {}
    for k in ("gold", "elixir", "dark"):
        vals = [r[k] for r in reads if r.get(k) is not None]
        if not vals: out[k] = None; continue
        best = max(set(vals), key=vals.count)
        out[k] = best if vals.count(best) > 1 else sorted(vals)[len(vals) // 2] # majority, else median
    return out

def _read_number_robust(raw):
    """
    The storage numbers are white digits with a dark outline; one threshold sometimes loses a digit
    (2,264,765 read as 22,647). Read the number with a few thresholds / sizes and keep the value the
    readings agree on; with no agreement keep the longest reading (missing digits is the usual error).
    """
    import re, cv2
    from collections import Counter
    candidates = []
    for thresh in (190, 160, 215):
        crop = Frame_Handler.high_contrast(raw, thresh=thresh)
        for scale in (1, 2):
            img = crop if scale == 1 else cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
            text = Tesseract.read(img, digits=True)
            digits = re.sub(r"[^0-9]", "", text or "")
            if digits: candidates.append(int(digits))
        counts = Counter(candidates)
        best, n = counts.most_common(1)[0] if counts else (None, 0)
        if n >= 3: return best # three readings agree: done early
    if candidates:
        counts = Counter(candidates)
        best, n = counts.most_common(1)[0]
        if n >= 2: return best
        return max(candidates, key=lambda v: (len(str(v)), v))
    return OCR_Handler.get_number(Frame_Handler.high_contrast(raw, thresh=190)) # slow OCR as the last resort

def _read_resources_once(builder_base=False, save_debug=False):
    """
    Read gold / elixir / dark elixir from the village screen with OCR.
    Returns {"gold": int|None, "elixir": int|None, "dark": int|None} or None if nothing was readable.
    """
    try:
        frame = Frame_Handler.get_frame(grayscale=False)
        out = {}
        out["dark"] = None
        for name, (x1, y1, x2, y2) in (BUILDER_RESOURCE_BANDS if builder_base else RESOURCE_BANDS).items():
            raw = Frame_Handler.crop(frame, x1, y1, x2, y2)
            if save_debug or configs.DEBUG: Frame_Handler.save_frame(raw, f"resource_{name}.png")
            value = _read_number_robust(raw)
            out[name] = value if value is not None and 0 <= value <= RESOURCE_LIMITS[name] else None
        if all(v is None for v in out.values()): return None
        return out
    except (KeyboardInterrupt, SystemExit): raise
    except Exception:
        logger.exception("read_resources:")
        return None

def game_ready():
    """True when the game is already open and showing a village (nothing to restart)."""
    try:
        if in_home_base():
            TEMP_CACHE["location"] = "home_base"
            return True
        if in_builder_base():
            TEMP_CACHE["location"] = "builder_base"
            return True
    except (KeyboardInterrupt, SystemExit): raise
    except Exception: pass
    return False

def start_coc(timeout=120, detailed=False, force_restart=False):
    import time
    
    try:
        Emulator_Manager.wake()
        if not running():
            if not detailed: return False
            else: return False, "paused"
        # Game already open in a village -> keep it as is (no close / reopen)
        if not force_restart and game_ready():
            logger.info("CoC already open")
            if not detailed: return True
            else: return True, "running"
        # game open but showing something (e.g. the "Reload" popup after being idle): press it first
        if not force_restart and ADB_Manager.adbutils_device.shell("pidof com.supercell.clashofclans").strip():
            if Auto_Learn.handle_unknown_screen("start_game"):
                for _ in range(15):
                    time.sleep(1)
                    if game_ready():
                        logger.info("CoC reconnected")
                        if not detailed: return True
                        else: return True, "running"
        if force_restart and never_close():
            # never kill the game: just bring it to the front and deal with whatever is on screen
            logger.info(f"Not restarting the game (closing is turned off): {force_restart if isinstance(force_restart, str) else 'requested'}")
            Auto_Learn.handle_unknown_screen("start_game")
            force_restart = False
        if force_restart:
            logger.info(f"Restarting CoC ({force_restart if isinstance(force_restart, str) else 'requested'})")
            to_system_home()
        logger.info("Starting CoC...")

        cont_templates = [render_text("Continue", "SupercellMagic", s, color=(255, 255, 255)) for s in range(25, 31)]

        i = 0
        start = time.time()
        restarted_once = update_checked = False
        last_unknown = 0
        while time.time() - start < timeout:
            if not running():
                if not detailed: return False
                else: return False, "paused"

            elapsed = time.time() - start
            # bring the game to front (starts it if closed). The game can take a long time to load,
            # so never kill it while loading: a clean restart only when asked, or once if it's
            # been stuck for more than 70 seconds.
            force = (force_restart and i == 0) or (elapsed > 70 and not restarted_once and not never_close())
            if force and i > 0:
                restarted_once = True
                logger.info("Game stuck while starting, restarting it once")
            if force or i % 10 == 0:   # bring it to the front now and then, not every half second
                ADB_Manager.adbutils_device.shell(f"am start {'-S' if force else ''} -W -n com.supercell.clashofclans/com.supercell.titan.GameApp")
            if i % 4 == 0: Input_Handler.click_exit(x=0.99, y=0.01, n=2, delay=0.1)
            
            Frame_Handler.get_frame()
            
            if in_home_base():
                TEMP_CACHE["location"] = "home_base"
                break
            elif in_builder_base():
                TEMP_CACHE["location"] = "builder_base"
                break

            cont_locs = Frame_Handler.batch_locate(cont_templates, grayscale=False, thresh=0.7, prefilter=True, ref="cc", use_cached=True)
            for x, y in cont_locs:
                if x is not None and y is not None:
                    Input_Handler.click(x, y)
            
            if i and i % 40 == 0:    # ~every 20 s: say what is going on instead of staying silent
                alive = bool(ADB_Manager.adbutils_device.shell("pidof com.supercell.clashofclans").strip())
                logger.info(f"Still opening the game ({int(elapsed)}s): " + ("the game is open but the village is not recognised yet"
                                                                          if alive else "waiting for the game to load"))
            # stuck on something unknown (popup, offer, event) after the normal loading time?
            # read it, record it, press a safe button
            if elapsed > 25 and time.time() - last_unknown > 15:
                last_unknown = time.time()
                Auto_Learn.handle_unknown_screen("start_game")
            # game update popup: checked once, late (the uiautomator helper can push the game
            # to the background, which makes it drop its connection)
            if elapsed > 45 and not update_checked:
                update_checked = True
                update_coc(timeout=3, from_in_game=True)
            time.sleep(0.5)
            
            i += 1
        if time.time() - start > timeout:
            stop_coc(sleep=configs.SUSPEND_EMULATOR_ON_IDLE and not never_close(), reason="game did not open in 2 minutes")
            raise Exception("Failed to start CoC")
        logger.info("CoC started")
        if not detailed: return True
        else: return True, "running"
    except (KeyboardInterrupt, SystemExit): raise
    except Exception:
        logger.exception("start_coc:")
        if not detailed: return False
        else: return False, "error"

def never_close():
    """The user doesn't want the bot to ever close the game (default): only they close it."""
    return bool(getattr(configs, "NEVER_CLOSE_GAME", True))

def stop_coc(sleep=False, timeout=60, reason=""):
    import time
    if never_close():
        logger.info(f"Keeping the game open ({reason})" if reason else "Keeping the game open")
        return
    logger.info(f"Stopping CoC... ({reason})" if reason else "Stopping CoC...")
    start = time.time()
    while time.time() - start < timeout:
        ADB_Manager.adbutils_device.shell("am force-stop com.supercell.clashofclans")
        if ADB_Manager.adbutils_device.shell("pidof com.supercell.clashofclans") == "": break
    to_system_home()
    if sleep: Emulator_Manager.sleep()
    logger.info("CoC stopped")

def update_coc(timeout=10, from_in_game=False):
    conn = ADB_Manager.uiautomator_device
    if not from_in_game:
        ADB_Manager.adbutils_device.shell('am start -a android.intent.action.VIEW -d "market://details?id=com.supercell.clashofclans"')
    else:
        try:
            conn(text="UPDATE").click(timeout=0)
        except (KeyboardInterrupt, SystemExit): raise
        except:
            return # no update popup in game
    
    try:
        conn(text="Update").click(timeout=timeout)
    except (KeyboardInterrupt, SystemExit): raise
    except:
        logger.info("No update available")
        pass
    if not from_in_game: to_system_home()

def in_builder_base():
    import numpy as np
    
    # First check for resource colors
    section = Frame_Handler.get_frame_section(0.95, 0.02, 1.0, 0.225, grayscale=False)
    resource_sections = [
        Frame_Handler.crop(section, 0.0, 0.33*i, 1.0, 0.33*(i+1)) for i in range(3)
    ]
    target_colors = [
        (255, 255, 87), # gold
        (158, 49, 255), # elixir
        (211, 236, 116), # gems
    ]
    found_all = True
    for sec, color in zip(resource_sections, target_colors):
        diff = abs(sec.astype(int) - np.array(color).reshape((1, 1, 3))).sum(2).flatten()
        if min(diff) > 10:
            found_all = False
            break
    if found_all: return True

    # Fallback to gold template matching
    return Frame_Handler.locate(
        Asset_Manager.upgrader_assets["builder_gold"],
        grayscale=False,
        prefilter=True,
        thresh=0.85
    ) != (None, None)

def to_builder_base(ref_cache=False):
    import cv2, time, numpy as np
    
    if ref_cache and TEMP_CACHE.get("location") == "builder_base": return
    
    TEMP_CACHE["location"] = "builder_base"
    
    if in_builder_base(): return
    
    for _ in range(3):
        Input_Handler.zoom(dir="in")
    for _ in range(2):
        Input_Handler.zoom(dir="out", percent=0.75)
    for _ in range(3):
        Input_Handler.swipe_right()
        Input_Handler.swipe_up()
    
    scale_templates = []
    for scale in np.arange(0.43, 0.47, 0.01):
        scale_templates.append(cv2.resize(Asset_Manager.misc_assets["boat_icon"], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST))

    for _ in range(5):
        xys = Frame_Handler.batch_locate(scale_templates, grayscale=True, thresh=0.7, ref="cc")
        for x, y in xys:
            if x is None or y is None: continue
            Input_Handler.click(x, y)
            time.sleep(2)
            return
        Input_Handler.swipe(x1=0.5, y1=0.5, x2=0.25, y2=0.75, hold_end_time=100)

class classproperty:
    def __init__(self, func):
        self.func = func

    def __get__(self, obj, owner):
        return self.func(owner)

class Exit_Handler:
    RUN_AT_EXIT = []
    
    @classmethod
    def register(cls, func):
        import atexit
        if func in cls.RUN_AT_EXIT: return
        atexit.register(func)
        cls.RUN_AT_EXIT.append(func)
        return func

    @classmethod
    def handle_sig(cls, sig, frame):
        import signal, atexit
        for func in cls.RUN_AT_EXIT:
            try:
                func()
                atexit.unregister(func)
            except: pass
        if sig == signal.SIGINT:
            raise KeyboardInterrupt
        sys.exit(0)

    @classmethod
    def setup_signal_handlers(cls):
        import signal
        signals = [signal.SIGINT, signal.SIGTERM]
        if sys.platform != "win32":
            signals.append(signal.SIGHUP)
        for sig in signals:
            try: signal.signal(sig, cls.handle_sig)
            except ValueError: pass   # loaded from a worker thread (e.g. the window's server): no signal handlers there

Exit_Handler.setup_signal_handlers()

class Scheduler:
    from apscheduler.schedulers.background import BackgroundScheduler
    scheduler = BackgroundScheduler()
    scheduler.start()
    
    add_job = scheduler.add_job

class Disk_Cache(collections.UserDict):
    """
    JSON cache shared by every bot process (one per account/instance).
    Each process only writes back the keys it changed, merged into the latest
    on-disk contents, so parallel instances never overwrite each other's data.
    Writes are atomic (temp file + replace) so a crash can't corrupt the file.
    """
    def __init__(self, path):
        import threading
        super().__init__()
        self.path = Path(path)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._dirty = set()
        self._mutex = threading.Lock()
        self.load_cache()
        Exit_Handler.register(self.save_cache)

    def __setitem__(self, key, value):
        from datetime import datetime, timedelta
        super().__setitem__(key, value)
        if hasattr(self, "_dirty"):
            self._dirty.add(key)
            Scheduler.add_job(
                self.save_cache,
                trigger="date",
                run_date=datetime.now() + timedelta(seconds=10),
                id="save_cache",
                replace_existing=True
            )

    def _read_disk(self):
        import json
        if not self.path.exists(): return {}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except (ValueError, OSError):
            logger.warning("Disk_Cache: cache file unreadable, ignoring it")
            return {}

    def load_cache(self):
        import portalocker
        with portalocker.Lock(self.lock_path, "a", timeout=10):
            self.data.update(self._read_disk())
        return self.data

    def save_cache(self):
        import json, os, portalocker
        with self._mutex:
            if not self._dirty: return
            dirty = set(self._dirty)
            with portalocker.Lock(self.lock_path, "a", timeout=10):
                merged = self._read_disk()
                for key in dirty:
                    if key in self.data: merged[key] = self.data[key]
                tmp_path = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
                with open(tmp_path, "w") as f:
                    json.dump(merged, f, indent=4)
                os.replace(tmp_path, self.path)
            # pick up keys other instances wrote in the meantime
            for key, value in merged.items():
                if key not in self._dirty: self.data[key] = value
            self._dirty -= dirty

Cache_Manager = Disk_Cache(CACHE_PATH)

class _Emulator_Manager:

    _pid = None
    _adb_port = None

    @classproperty
    def adb_port(cls):
        raise NotImplementedError

    @classproperty
    def adb_address(cls):
        return f"127.0.0.1:{cls.adb_port}"

    @classproperty
    def pid(cls):
        if cls._pid is None:
            cls._pid = Cache_Manager.get(f"{INSTANCE_ID}_emulator_pid", None)
        return cls._pid

    @classmethod
    def init(cls):
        # closing the bot closes the emulator (and the game) only when the user allows closing the game
        Exit_Handler.register(lambda: None if never_close() else cls.stop())
        # an emulator that is already running is used as it is (restarting it closed the game
        # and made the start take minutes); only a stopped one is started
        try: already = cls.check()
        except Exception: already = False
        if already:
            logger.info("Emulator already running, using it")
            return
        logger.info("Starting the emulator…")
        cls.start()

    @classmethod
    def check(cls):
        if cls.pid is not None:
            import psutil
            try:
                proc = psutil.Process(cls.pid)
                if proc.status() == psutil.STATUS_ZOMBIE:
                    return False
                return proc.is_running()
            except psutil.NoSuchProcess:
                return False
        elif cls.adb_address is not None:
            try:
                ADB_Manager.connect_once(cls.adb_address)
                return True
            except (KeyboardInterrupt, SystemExit): raise
            except: return False
        return False

    @classmethod
    def start(cls, instance_id=None, timeout=60):
        raise NotImplementedError

    @classmethod
    def stop(cls, timeout=60):
        raise NotImplementedError

    @classmethod
    def restart(cls):
        cls.stop()
        cls.start()

    @classmethod
    def sleep(cls):
        # psutil.Process.suspend()/resume() wrap the native suspend APIs on every platform
        import psutil

        if cls.pid is None:
            logger.warning(f"{cls.__name__} PID unset. Cannot sleep.")
            return

        try:
            psutil.Process(cls.pid).suspend()
        except psutil.NoSuchProcess:
            pass

    @classmethod
    def wake(cls):
        import psutil

        if cls.pid is None:
            logger.warning(f"{cls.__name__} PID unset. Cannot wake.")
            return

        try:
            psutil.Process(cls.pid).resume()
        except psutil.NoSuchProcess:
            pass

class BlueStacks_Manager(_Emulator_Manager):
    """
    BlueStacks internal instance name is NOT the same as the bot instance ID or the user-facing instance name.
    Generally should be of the form 'Pie64_X' 'Nougat64_X' 'Tiramisu64_X'
    """
    
    _internal_instance_name = None
    _conf_path = None
    
    @classproperty
    def internal_instance_name(cls, instance_id=None):
        import re
        
        if cls._internal_instance_name is not None:
            return cls._internal_instance_name
        
        instance_id = instance_id if instance_id is not None else INSTANCE_ID
        
        if cls._conf_path is None or not Path(cls._conf_path).exists():
            if sys.platform == "darwin":
                cls._conf_path = "/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf"
            elif sys.platform == "win32":
                cls._conf_path = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
            else:
                raise Exception("Unsupported OS")
            if not Path(cls._conf_path).exists():
                cls._conf_path = file_search("/", "bluestacks.conf", ["bluestacks"])

        link = str((getattr(configs, "EMULATOR_LINKS", {}) or {}).get(instance_id, ""))
        if link:
            cls._internal_instance_name = link
            return link

        if cls._conf_path is not None and Path(cls._conf_path).exists():
            pattern = re.compile(r'^bst\.instance\.([^.]+)\.display_name="?(.*?)"?$')
            for line in Path(cls._conf_path).read_text().splitlines():
                match = pattern.match(line)
                if match and match.group(2) == instance_id:
                    cls._internal_instance_name = match.group(1)
                    break

        if cls._internal_instance_name is None:
            raise RuntimeError(
                f"BlueStacks instance '{instance_id}' was not found. "
                "Rename the emulator instance to match INSTANCE_IDS."
            )

        return cls._internal_instance_name
    
    @classproperty
    def adb_port(cls):
        if cls._adb_port is not None:
            return cls._adb_port

        if cls._conf_path is None or not Path(cls._conf_path).exists():
            if sys.platform == "darwin":
                cls._conf_path = "/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf"
            elif sys.platform == "win32":
                cls._conf_path = r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf"
            else:
                raise Exception("Unsupported OS")
            if cls._conf_path is None or not Path(cls._conf_path).exists():
                cls._conf_path = file_search("/", "bluestacks.conf", ["bluestacks"])

        if cls._adb_port is None and cls._conf_path is not None:
            if Path(cls._conf_path).exists():
                conf_data = Path(cls._conf_path).read_text()
                for line in conf_data.splitlines():
                    if line.startswith(f"bst.instance.{cls.internal_instance_name}.adb_port"):
                        cls._adb_port = line.split("=", 1)[1].strip().replace('"', '')
                        break

        if cls._adb_port is None:
            raise RuntimeError(
                f"ADB port for BlueStacks instance '{cls.internal_instance_name}' was not found."
            )

        return cls._adb_port

    @classmethod
    def start(cls, instance_id=None, timeout=60):
        import sys, subprocess, time
        
        instance_id = instance_id if instance_id is not None else INSTANCE_ID
        
        cls.wake()

        if cls.check():
            logger.info("Bluestacks already running.")
            return
        
        str_target_instance_name = cls.internal_instance_name if cls.internal_instance_name is not None else ""
        if sys.platform == "darwin":
            bin_path = BLUESTACKS_BIN_PATH if BLUESTACKS_BIN_PATH != "" else "/Applications/BlueStacks.app/Contents/MacOS/BlueStacks"
            if not Path(bin_path).exists():
                bin_path = file_search("/", "BlueStacks", ["bluestacks"])
            assert Path(bin_path).exists(), f"BlueStacks executable not found at {bin_path}"
            p = subprocess.Popen(
                [bin_path, "--instance", str_target_instance_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            cls._pid = p.pid
            Cache_Manager[f"{INSTANCE_ID}_emulator_pid"] = cls._pid
        elif sys.platform == "win32":
            bin_path = BLUESTACKS_BIN_PATH if BLUESTACKS_BIN_PATH != "" else r"C:\Program Files\BlueStacks_nxt\HD-Player.exe"
            if not Path(bin_path).exists():
                bin_path = file_search("/", "HD-Player.exe", ["bluestacks"])
            assert Path(bin_path).exists(), f"BlueStacks executable not found at {bin_path}"
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 7
            p = subprocess.Popen(
                [bin_path, "--instance", str_target_instance_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                startupinfo=startupinfo,
                creationflags=subprocess.DETACHED_PROCESS,
            )
            cls._pid = p.pid
            Cache_Manager[f"{INSTANCE_ID}_emulator_pid"] = cls._pid
        else:
            raise Exception("Unsupported OS")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            if cls.check():
                logger.info("BlueStacks started.")
                return
            time.sleep(0.5)
        
        raise Exception("BlueStacks failed to start.")

    @classmethod
    def stop(cls, timeout=60):
        import time, psutil

        cls.wake()

        if not cls.check():
            logger.info("BlueStacks stopped.")
            return

        try:
            ADB_Manager.adbutils_device.shell("reboot -p")
        except (KeyboardInterrupt, SystemExit): raise
        except: psutil.Process(cls.pid).terminate()

        start_time = time.time()
        while time.time() - start_time < timeout:
            if not cls.check():
                logger.info("BlueStacks stopped.")
                return
            time.sleep(0.5)
        
        raise Exception("BlueStacks failed to stop.")

class MuMu_Manager(_Emulator_Manager):
    """
    Instance identity is resolved via MuMuManager.exe's own "name" field for each vmindex,
    which must be renamed (in MuMu's multi-instance manager) to match the bot instance ID,
    same convention as BlueStacks_Manager.internal_instance_name.
    """

    _vmindex = None
    _adb_port = None
    _manager_path = None

    @classmethod
    def init(cls):
        if sys.platform == "darwin":
            raise Exception("MuMu Player is not supported on macOS yet. Use BlueStacks instead.")
        super().init()

    @classproperty
    def manager_path(cls):
        if cls._manager_path is not None and Path(cls._manager_path).exists():
            return cls._manager_path

        bin_path = getattr(configs, "MUMU_BIN_PATH", "") or r"C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe"
        if not Path(bin_path).exists():
            bin_path = file_search("/", "MuMuManager.exe", ["netease", "mumu"])
        assert bin_path is not None and Path(bin_path).exists(), f"MuMuManager.exe not found at {bin_path}"
        cls._manager_path = bin_path
        return cls._manager_path

    @classmethod
    def _run(cls, *args):
        import subprocess, json
        res = subprocess.run([cls.manager_path, *args], capture_output=True, text=True)
        return json.loads(res.stdout) if res.stdout.strip() else {}

    @classproperty
    def vmindex(cls, instance_id=None):
        if cls._vmindex is not None:
            return cls._vmindex

        instance_id = instance_id if instance_id is not None else INSTANCE_ID
        info = cls._run("info", "--vmindex", "all")
        for index, data in info.items():
            if data.get("name") == instance_id:
                cls._vmindex = index
                break
        else:
            raise Exception(f"No MuMu instance named '{instance_id}' found. Rename it in MuMu's multi-instance manager to match INSTANCE_IDS.")

        return cls._vmindex

    @classproperty
    def adb_port(cls):
        if cls._adb_port is not None:
            return cls._adb_port

        info = cls._run("info", "--vmindex", cls.vmindex)
        port = info.get("adb_port")
        if port is not None:
            cls._adb_port = str(port)
        else:
            # ponytail: MuMu only reports adb_port once the instance is running; before that,
            # fall back to its default multi-instance port formula (base 16384, step 32/index).
            # Upgrade path: verify this formula still holds if MuMu changes its port scheme.
            cls._adb_port = str(16384 + 32 * int(cls.vmindex))
        return cls._adb_port

    @classproperty
    def pid(cls):
        if cls._pid is not None:
            return cls._pid

        info = cls._run("info", "--vmindex", cls.vmindex)
        pid = info.get("pid")
        if pid is not None:
            cls._pid = int(pid)
        return cls._pid

    @classmethod
    def start(cls, timeout=60):
        import time
        
        cls.wake()

        if cls.check():
            logger.info("MuMu already running.")
            return

        cls._run("control", "--vmindex", cls.vmindex, "launch")

        start_time = time.time()
        while time.time() - start_time < timeout:
            if cls.check():
                logger.info("MuMu started.")
                return
            time.sleep(0.5)

        raise Exception("MuMu failed to start.")

    @classmethod
    def stop(cls, timeout=60):
        import time

        cls.wake()

        if not cls.check():
            logger.info("MuMu stopped.")
            return
        cls._run("control", "--vmindex", cls.vmindex, "shutdown")

        start_time = time.time()
        while time.time() - start_time < timeout:
            if not cls.check():
                logger.info("MuMu stopped.")
                return
            time.sleep(0.5)

        raise Exception("MuMu failed to stop.")

class LDPlayer_Manager(_Emulator_Manager):
    """
    LDPlayer, controlled through its ldconsole.exe. The instance whose title matches the bot
    account ID is used (rename it in LDMultiPlayer); with a single instance it is used directly.
    ADB port = 5555 + 2 * index.
    """

    _index = None
    _console = None

    COMMON_DIRS = [r"C:\LDPlayer\LDPlayer9", r"D:\LDPlayer\LDPlayer9", r"E:\LDPlayer\LDPlayer9",
                   r"C:\LDPlayer\LDPlayer4.0", r"D:\LDPlayer\LDPlayer4.0",
                   r"C:\Program Files\LDPlayer\LDPlayer9", r"C:\Program Files\ldplayer9box",
                   r"D:\LDPlayer", r"C:\LDPlayer"]

    @classmethod
    def init(cls):
        if sys.platform != "win32":
            raise Exception("LDPlayer is only available on Windows.")
        super().init()

    @classproperty
    def console(cls):
        if cls._console is not None and Path(cls._console).is_file():
            return cls._console
        custom = str(getattr(configs, "LDPLAYER_BIN_PATH", "") or "").strip().strip('"')
        candidates = []
        if custom: # the setting may be the LDPlayer folder or ldconsole.exe itself
            cp = Path(custom)
            candidates += [str(cp)] if cp.suffix.lower() == ".exe" else []
            candidates += [str(cp / "ldconsole.exe"), str(cp / "dnconsole.exe"), str(cp.parent / "ldconsole.exe")]
        for d in cls.COMMON_DIRS:
            candidates += [str(Path(d) / "ldconsole.exe"), str(Path(d) / "dnconsole.exe")]
        found = None
        for c in candidates:
            try:
                if c and Path(c).is_file(): found = c; break # a folder can't be run ("Access is denied")
            except OSError: # e.g. a BitLocker-locked drive
                continue
        if found is None: found = file_search("/", "ldconsole.exe", ["ldplayer"])
        assert found is not None and Path(found).exists(), "ldconsole.exe not found: set the LDPlayer folder in Settings"
        cls._console = found
        return cls._console

    @classproperty
    def adb_exe(cls):
        """LDPlayer's own adb (same version as its adb server avoids connection fights)."""
        try:
            p = Path(cls.console).parent / "adb.exe"
            return str(p) if p.exists() else None
        except Exception:
            return None

    @classmethod
    def _run(cls, *args):
        import subprocess
        res = subprocess.run([cls.console, *args], capture_output=True, text=True, timeout=60, **_no_window())
        return res.stdout or ""

    @classmethod
    def instances(cls):
        """[(index, title, running, pid)] from 'ldconsole list2'."""
        out = []
        for line in cls._run("list2").splitlines():
            c = line.strip().split(",")
            if len(c) < 6 or not c[0].strip().isdigit(): continue
            pid = int(c[5]) if c[5].strip().lstrip("-").isdigit() else -1
            # running = Android up, OR its window exists, OR it has a process (the Android flag alone is 0 for a
            # while and on some LDPlayer versions; "launch" on a running copy restarts Android -> device offline)
            window = c[2].strip() not in ("", "0")
            out.append((int(c[0]), c[1], c[4].strip() == "1" or window or pid > 0, pid))
        return out

    @classmethod
    def _adb_alive(cls):
        """The copy answers on its ADB port = it is running (independent of ldconsole)."""
        import subprocess
        try:
            adb = emulator_adb() or "adb"
            addr = f"127.0.0.1:{cls.adb_port}"
            subprocess.run([adb, "connect", addr], capture_output=True, timeout=8, **_no_window())
            r = subprocess.run([adb, "-s", addr, "get-state"], capture_output=True, text=True, timeout=8, **_no_window())
            return r.stdout.strip() == "device"
        except Exception:
            return False

    @classproperty
    def index(cls, instance_id=None):
        if cls._index is not None: return cls._index
        instance_id = instance_id if instance_id is not None else INSTANCE_ID
        inst = cls.instances()
        link = str((getattr(configs, "EMULATOR_LINKS", {}) or {}).get(instance_id, ""))
        match = [i for i, title, _, _ in inst if str(i) == link] if link else []
        match = match or [i for i, title, _, _ in inst if title == instance_id]
        if match:
            cls._index = match[0]
        elif len(inst) == 1:
            cls._index = inst[0][0]
            logger.info(f"Using the only LDPlayer instance '{inst[0][1]}' for account '{instance_id}'")
        else:
            names = ", ".join(t for _, t, _, _ in inst) or "none"
            raise Exception(f"No LDPlayer instance named '{instance_id}' (found: {names}). Rename it in LDMultiPlayer.")
        return cls._index

    @classproperty
    def adb_port(cls):
        if cls._adb_port is None: cls._adb_port = str(5555 + 2 * int(cls.index))
        return cls._adb_port

    @classproperty
    def pid(cls):
        for i, _, running, pid in cls.instances():
            if i == cls.index and running and pid > 0:
                cls._pid = pid
                return pid
        return None

    @classmethod
    def check(cls):
        try:
            if any(i == cls.index and running for i, _, running, _ in cls.instances()): return True
        except Exception:
            pass
        return cls._adb_alive()

    @classmethod
    def start(cls, timeout=120):
        import time
        if cls.pid is not None: cls.wake()
        if cls.check():
            logger.info("LDPlayer already running.")
            return
        logger.info(f"Starting LDPlayer (copy #{cls.index})…")
        cls._run("launch", "--index", str(cls.index))
        start_time = time.time()
        while time.time() - start_time < timeout:
            if cls.check():
                logger.info("LDPlayer started.")
                time.sleep(8)          # Android finishes booting after the window is up
                return
            time.sleep(2)
        raise Exception("LDPlayer failed to start.")

    @classmethod
    def stop(cls, timeout=60):
        import time
        if not cls.check():
            logger.info("LDPlayer stopped.")
            return
        cls._run("quit", "--index", str(cls.index))
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not cls.check():
                logger.info("LDPlayer stopped.")
                return
            time.sleep(1)
        raise Exception("LDPlayer failed to stop.")

def _chosen_emulator():
    """The emulator picked in the app (fresh from the settings file; LDPlayer when nothing is set)."""
    try:
        import settings as _s
        return _s.load_app().get("emulator") or getattr(configs, "EMULATOR_TYPE", "ldplayer")
    except Exception:
        return getattr(configs, "EMULATOR_TYPE", "ldplayer")

Emulator_Manager = {"bluestacks": BlueStacks_Manager, "mumu": MuMu_Manager, "ldplayer": LDPlayer_Manager}.get(
    _chosen_emulator(), LDPlayer_Manager)

class Task_Handler:
    
    cache_valid = False
    cached_exclusions = []
    task_defaults = {
        "home_base_priority": "PRIORITY_HOME_BASE_UPGRADES",
        "home_lab_priority": "PRIORITY_HOME_LAB_UPGRADES",
        "pet_house_priority": "PRIORITY_PET_UPGRADES",
        "builder_base_priority": "PRIORITY_BUILDER_BASE_UPGRADES",
        "builder_lab_priority": "PRIORITY_BUILDER_LAB_UPGRADES",
        "heroes": "UPGRADE_HEROES",
        "home_base": "UPGRADE_HOME_BASE",
        "builder_base": "UPGRADE_BUILDER_BASE",
        "home_lab": "UPGRADE_HOME_LAB",
        "builder_lab": "UPGRADE_BUILDER_LAB",
        "pet_house": "UPGRADE_PETS",
        "home_attacks": "ATTACK_HOME_BASE",
        "builder_attacks": "ATTACK_BUILDER_BASE",
        "lab_assistant": "ASSIGN_LAB_ASSISTANT",
        "builder_apprentice": "ASSIGN_BUILDER_APPRENTICE",
    }
    
    @classmethod
    def get_exclusions(cls, use_cached=False):
        import requests
        
        if use_cached and cls.cache_valid:
            return cls.cached_exclusions
        if WEB_APP_URL == "":
            # settings saved from the desktop GUI (per account), re-read every call
            import settings as bot_settings
            cls.cache_valid = True
            import today_plan
            cls.cached_exclusions = bot_settings.exclusions(today_plan.overlay(bot_settings.load(INSTANCE_ID), INSTANCE_ID))
            return cls.cached_exclusions
        if WEB_APP_URL != "":
            res = requests.get(
                f"{WEB_APP_URL}/instances/{INSTANCE_ID}/exclude",
                timeout=(10, 20)
            )
            if res.status_code == 200:
                cls.cache_valid = True
                cls.cached_exclusions = res.json().get("exclusions", [])
                return cls.cached_exclusions
        elif configs.LOCAL_GUI and TEMP_CACHE.get("gui_port") is not None:
            res = requests.get(
                f"http://127.0.0.1:{TEMP_CACHE['gui_port']}/instances/{INSTANCE_ID}/exclude",
                timeout=(10, 20)
            )
            if res.status_code == 200:
                cls.cache_valid = True
                cls.cached_exclusions = res.json().get("exclusions", [])
                return cls.cached_exclusions
        return None

    @classmethod
    def excluded(cls, task_name, use_cached=False):
        try:
            assert task_name in cls.task_defaults, "Invalid task name"
            exclusions = cls.get_exclusions(use_cached=use_cached)
            if exclusions is not None:
                return task_name in exclusions
            raise Exception("No external exclusion source available")
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            logger.error(f"Task_Handler.excluded: {e}")
            return not getattr(configs, cls.task_defaults[task_name], False)

class Tesseract:
    """
    Fast OCR for numbers through the Tesseract program (called directly, no extra Python package).
    Used for resource counters; easyocr stays the fallback and the engine for words.
    """
    path = None
    checked = False

    COMMON_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
        "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract",
    ]

    @classmethod
    def find(cls, refresh=False):
        import shutil
        if cls.checked and not refresh: return cls.path
        cls.checked = True
        candidates = [getattr(configs, "TESSERACT_PATH", "") or "", shutil.which("tesseract") or ""] + cls.COMMON_PATHS
        cls.path = next((c for c in candidates if c and Path(c).exists()), None)
        return cls.path

    @classmethod
    def version(cls):
        import subprocess
        exe = cls.find(refresh=True)
        if not exe: return None
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10, **_no_window())
            return (out.stdout or out.stderr).splitlines()[0].strip()
        except Exception:
            return None

    @classmethod
    def read(cls, img, digits=False, psm=7):
        """img: grayscale/RGB array. Returns the recognised text or None if Tesseract isn't available."""
        import subprocess, cv2, numpy as np
        exe = cls.find()
        if not exe: return None
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if img.ndim == 3 else img
        # game digits are white with a dark outline -> black text on white, upscaled, with margin
        if g.mean() < 128: g = 255 - g
        g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        g = cv2.copyMakeBorder(g, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        ok, png = cv2.imencode(".png", g)
        if not ok: return None
        args = [exe, "stdin", "stdout", "--psm", str(psm)]
        if digits: args += ["-c", "tessedit_char_whitelist=0123456789"]
        try:
            out = subprocess.run(args, input=png.tobytes(), capture_output=True, timeout=10, **_no_window())
            return out.stdout.decode("utf-8", errors="ignore").strip()
        except Exception:
            return None

def _no_window():
    """Hide the console window flash of helper programs on Windows."""
    import subprocess
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}

class OCR_Handler:
    
    backoff_time = 0

    @classmethod
    def get_number(cls, frame):
        """Read one integer: Tesseract first (fast), then the normal OCR as fallback."""
        import re
        text = Tesseract.read(frame, digits=True)
        if text:
            digits = re.sub(r"[^0-9]", "", text)
            if digits: return int(digits)
        return _parse_resource(cls.get_text(frame))
    
    @classmethod
    def get_text(cls, frame):
        import time
        if configs.GROQ_API_KEY != "":
            if time.time() > cls.backoff_time:
                try: return cls.external_ocr(frame)
                except (KeyboardInterrupt, SystemExit): raise
                except: cls.backoff_time = time.time() + 600
        return cls.local_ocr(frame)

    @classmethod
    def local_ocr(cls, frame):
        if sys.platform == "darwin":
            try:
                import ocrmac, PIL
                return ocrmac.OCR(
                    PIL.Image.fromarray(frame),
                    recognition_level="accurate",
                    language_preference=["en-US"],
                    detail=False
                )
            except (KeyboardInterrupt, SystemExit): raise
            except:
                logger.warning("ocrmac not available, falling back to easyocr")

        if not hasattr(cls, 'reader'):
            import easyocr
            cls.reader = easyocr.Reader(['en'], gpu=True)
        result = cls.reader.readtext(frame, detail=0)
        return [text for text in result if text.strip()]

    @classmethod
    def external_ocr(cls, frame):
        import cv2, base64
        from groq import Groq
        
        # PNG is lossless: JPEG artifacts around thin game-font digits cause misreads
        base64_img = base64.b64encode(cv2.imencode(".png", frame)[1]).decode("utf-8")
        if getattr(cls, "groq_client", None) is None:
            cls.groq_client = Groq(api_key=configs.GROQ_API_KEY, timeout=10, max_retries=0)
        chat_completion = cls.groq_client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "what text is in this image? respond ONLY with the text. if there is no text respond with ~"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_img}",
                            },
                        },
                    ],
                }
            ],
        )
        return chat_completion.choices[0].message.content.replace('~', '').splitlines()

class Asset_Manager:
    fonts = {}
    misc_assets = {}
    upgrader_assets = {}
    attacker_assets = {}
    
    @staticmethod
    def resource_path(rel_path):
        import sys
        from pathlib import Path
        if hasattr(sys, "_MEIPASS"):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent.resolve()
        return base_path / rel_path
    
    @classmethod
    def load_fonts(cls):
        import os
        cls.fonts = {}
        path = cls.resource_path("assets/fonts")
        for file in os.listdir(path):
            cls.fonts[file.replace('.ttf', '')] = str(path / file)

    @classmethod
    def load_misc_assets(cls):
        import os, cv2
        assets = {}
        path = cls.resource_path("assets/misc")
        for file in os.listdir(path):
            if not file.endswith('.png'): continue
            assets[file.replace('.png', '')] = cv2.cvtColor(cv2.imread(path / file, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        cls.misc_assets = assets
    
    @classmethod
    def load_upgrader_assets(cls):
        import os, cv2
        assets = {}
        path = cls.resource_path("assets/upgrader")
        for file in os.listdir(path):
            if not file.endswith('.png'): continue
            assets[file.replace('.png', '')] = cv2.cvtColor(cv2.imread(path / file, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        cls.upgrader_assets = assets

    @classmethod
    def load_attacker_assets(cls):
        import os, cv2
        assets = {}
        path = cls.resource_path("assets/attacker")
        for file in os.listdir(path):
            if not file.endswith('.png'): continue
            assets[file.replace('.png', '')] = cv2.cvtColor(cv2.imread(path / file, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
        cls.attacker_assets = assets

Asset_Manager.load_misc_assets()
Asset_Manager.load_upgrader_assets()
Asset_Manager.load_attacker_assets()
Asset_Manager.load_fonts()

class DeviceProxy:
    def __init__(self, manager_cls, private_attr_name, max_retries=1):
        self._manager_cls = manager_cls
        self._private_attr_name = private_attr_name
        self._max_retries = max_retries

    @property
    def _real_device(self):
        return getattr(self._manager_cls, self._private_attr_name)

    def _ensure_device(self):
        device = self._real_device
        if device is None:
            if not self._manager_cls.connect():
                raise RuntimeError("Device is not connected and auto-reconnect failed.")
            device = self._real_device
        return device

    def _execute(self, func_getter, context_name, *args, **kwargs):
        attempts = 0
        while True:
            device = self._ensure_device()
            target = func_getter(device)
            
            try:
                return target(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit): 
                raise
            except (AttributeError, NotImplementedError): 
                raise
            except Exception as e:
                if attempts >= self._max_retries:
                    if self._max_retries == 0:
                        raise
                    raise RuntimeError(f"Action '{context_name}' failed, and max retries ({self._max_retries}) exceeded.") from e
                
                attempts += 1
                logger.warning(f"ADB connection lost during '{context_name}' ({type(e).__name__}: {e}), reconnecting...")
                # cheap path first: re-attach the device; full rebuild only if that fails
                if self._manager_cls.quick_reconnect():
                    logger.info("ADB reconnected.")
                    continue
                if not self._manager_cls.connect():
                    raise RuntimeError(f"Action '{context_name}' failed, and auto-reconnection timed out.") from e

    def __call__(self, *args, **kwargs):
        return self._execute(lambda d: d, "__call__", *args, **kwargs)

    def __getattr__(self, name):
        device = self._ensure_device()
        attr = getattr(device, name)

        if callable(attr):
            def wrapper(*args, **kwargs):
                return self._execute(lambda d: getattr(d, name), name, *args, **kwargs)
            return wrapper
        
        return attr

MINITOUCH_PATH = "/data/local/tmp/minitouch"
MINITOUCH_URL = "https://github.com/williamfzc/stf-binaries/raw/master/node_modules/minitouch-prebuilt/prebuilt/{abi}/bin/minitouch"

def ensure_minitouch(device):
    """
    Install a working minitouch binary on the device ourselves.
    pyminitouch detects the CPU ABI with an unquoted shell command, which breaks when the
    adb path contains spaces (e.g. C:\\Program Files\\BlueStacks_nxt\\HD-Adb.exe): it then
    downloads an error page instead of the binary and pushes that, causing
    "minitouch[N]: syntax error". This also repairs a device that already has that bad file.
    """
    import io, requests
    import pyminitouch.connection as mnt_conn

    abi = device.getprop("ro.product.cpu.abi").strip()
    # make pyminitouch's own (buggy) ABI lookup harmless
    mnt_conn.MNTInstaller.get_abi = lambda self: abi

    check = device.shell(f"[ -f {MINITOUCH_PATH} ] && {MINITOUCH_PATH} -h 2>&1 | head -n 1")
    if "Usage" in check: return

    logger.info(f"Installing minitouch for ABI '{abi}'...")
    device.shell(f"rm -f {MINITOUCH_PATH}")
    res = requests.get(MINITOUCH_URL.format(abi=abi), timeout=30)
    if res.status_code != 200 or not res.content.startswith(b"\x7fELF"):
        raise RuntimeError(f"Could not download minitouch for ABI '{abi}' (HTTP {res.status_code})")
    device.sync.push(io.BytesIO(res.content), MINITOUCH_PATH, mode=0o755)
    device.shell(f"chmod 755 {MINITOUCH_PATH}")
    if "Usage" not in device.shell(f"{MINITOUCH_PATH} -h 2>&1 | head -n 1"):
        raise RuntimeError("minitouch was installed but does not run on this device")
    logger.info("minitouch installed.")

def current_emulator():
    """The emulator chosen in the app settings (read fresh: a child process may not have it in configs yet)."""
    try:
        import settings
        return settings.load_app().get("emulator") or getattr(configs, "EMULATOR_TYPE", "ldplayer")
    except Exception:
        return getattr(configs, "EMULATOR_TYPE", "ldplayer")


def emulator_adb():
    """The emulator's OWN adb. Two different adb programs on one PC keep killing each other's server
    (device offline / not found every few minutes), so LDPlayer always uses LDPlayer's adb, never BlueStacks'."""
    import os, sys
    from pathlib import Path
    if sys.platform != "win32": return None
    emu = current_emulator()
    if emu == "ldplayer":
        try:
            p = LDPlayer_Manager.adb_exe
            if p: return p
        except Exception:
            pass
        for base in ([os.environ.get("ProgramFiles", r"C:\Program Files")] + [f"{d}:\\" for d in "CDEF"]):
            for sub in ("LDPlayer\\LDPlayer9", "LDPlayer\\LDPlayer4.0", "LDPlayer9", "ChangZhi\\LDPlayer"):
                p = Path(base) / sub / "adb.exe"
                if p.exists(): return str(p)
        return None
    if emu == "bluestacks":
        p = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BlueStacks_nxt" / "HD-Adb.exe"
        return str(p) if p.exists() else None
    return None


class ADB_Manager:
    import uiautomator2 as u2
    from adbutils import AdbDevice
    from pyminitouch import MNTDevice
    
    _adbutils_device : AdbDevice | None = None
    _minitouch_device : MNTDevice | None = None
    _uiautomator_device : u2.Device | None = None

    @classmethod
    def is_connected(cls):
        import adbutils

        if cls._adbutils_device is None or cls._minitouch_device is None or cls._uiautomator_device is None:
            return False

        try:
            device_list = adbutils.adb.device_list()
            if cls._adbutils_device.serial not in [d.serial for d in device_list]: return False
            return True
        except (KeyboardInterrupt, SystemExit): raise
        except:
            return False

    @classmethod
    def connect_once(cls, addr=None):
        import subprocess, adbutils, os, shutil
        import uiautomator2 as u2
        from pyminitouch import MNTDevice
        
        if addr is None: addr = ADB_ADDRESS
        if ADB_ABS_DIR != "": os.environ["PATH"] = ADB_ABS_DIR + os.pathsep + os.environ["PATH"]
        adb_executable = emulator_adb() or shutil.which("adb")
        if adb_executable is None:
            raise FileNotFoundError("ADB executable not found. Set ADB_ABS_DIR to its directory.")
        os.environ["ADBUTILS_ADB_PATH"] = adb_executable
        import pyminitouch.config
        pyminitouch.config.ADB_EXECUTOR = adb_executable
        import pyminitouch.connection
        pyminitouch.connection._ADB = adb_executable
        # if cls.is_connected(): return
        subprocess.run([adb_executable, "start-server"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_no_window())
        cls._adb_exe = adb_executable
        def reset_adb():
            # Never kill the shared adb server (it drops every connection, including
            # minitouch and other accounts): just reconnect this device.
            subprocess.run([adb_executable, "disconnect", addr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **_no_window())
        res = adbutils.adb.connect(addr)
        if "connected" not in res:
            reset_adb()
            raise Exception("Failed to connect to ADB.")
        devices = []
        try:
            d1 = adbutils.device(addr)
            ensure_minitouch(d1)
            try:
                if cls._minitouch_device is not None: cls._minitouch_device.stop()
            except Exception: pass
            cls.kill_device_minitouch(d1)
            import time as _t
            _t.sleep(0.4) # let the old minitouch release its socket ("Address already in use")
            try:
                d2 = MNTDevice(addr)
            except Exception:
                cls.kill_device_minitouch(d1)
                _t.sleep(1.0)
                d2 = MNTDevice(addr)
            d3 = u2.connect(addr)
            devices = [d1, d2, d3]
            Exit_Handler.register(d2.stop)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            logger.debug(f"ADB device setup failed: {e}")
            reset_adb()
            raise Exception("Failed to get ADB device.")
        cls._adbutils_device, cls._minitouch_device, cls._uiautomator_device = devices
    
    _adb_exe = None
    _keepalive = None

    @classmethod
    def device_state(cls, addr=None):
        """'device' when usable, 'offline', or None when not listed."""
        import adbutils
        addr = addr or ADB_ADDRESS
        try:
            for info in adbutils.adb.list():
                if info.serial == addr: return info.state
        except Exception:
            pass
        return None

    @classmethod
    def quick_reconnect(cls, wait=6):
        """Re-attach the TCP device without rebuilding minitouch/uiautomator (takes ~1s)."""
        import time, subprocess, adbutils
        addr = ADB_ADDRESS
        try:
            if cls.device_state(addr) == "offline" and cls._adb_exe:
                subprocess.run([cls._adb_exe, "reconnect", "offline"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, **_no_window())
            adbutils.adb.connect(addr, timeout=5)
        except Exception:
            pass
        end = time.time() + wait
        while time.time() < end:
            if cls.device_state(addr) == "device": return True
            time.sleep(0.5)
        return False

    @classmethod
    def kill_device_minitouch(cls, device=None):
        """A minitouch left running on the device (old session / crash) makes the next start fail."""
        try:
            (device or cls._adbutils_device).shell("pkill minitouch; killall minitouch 2>/dev/null")
        except Exception:
            pass

    @classmethod
    def reset_minitouch(cls):
        import time
        from pyminitouch import MNTDevice
        try:
            if cls._minitouch_device is not None: cls._minitouch_device.stop()
        except Exception:
            pass
        cls.kill_device_minitouch()
        time.sleep(0.3)
        cls._minitouch_device = MNTDevice(ADB_ADDRESS)
        Exit_Handler.register(cls._minitouch_device.stop)
        logger.info("minitouch restarted.")

    @classmethod
    def start_keepalive(cls):
        """Background check every 15s so an idle TCP connection never stays dropped."""
        import threading, time
        if cls._keepalive is not None: return
        def loop():
            while True:
                time.sleep(15)
                try:
                    if cls._adbutils_device is not None and cls.device_state() != "device":
                        cls.quick_reconnect()
                except Exception:
                    pass
        cls._keepalive = threading.Thread(target=loop, daemon=True, name="adb-keepalive")
        cls._keepalive.start()

    @classmethod
    def connect(cls, timeout=60):
        import time
        start = time.time()
        waiting_logged = False
        last_error_log = 0
        while time.time() - start < timeout:
            try:
                cls.connect_once()
                logger.info("Connected to ADB.")
                cls.start_keepalive()
                return True
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                state = cls.device_state()
                if state != "device" or not cls.boot_completed():
                    # emulator still starting: normal, wait quietly instead of logging errors
                    if not waiting_logged:
                        logger.info("Waiting for the emulator to finish starting...")
                        waiting_logged = True
                    time.sleep(2)
                    continue
                if time.time() - last_error_log > 10:
                    logger.warning(f"Connecting to the emulator failed ({type(e).__name__}), retrying...")
                    last_error_log = time.time()
            time.sleep(1)
        logger.error("Failed to connect to ADB.")
        return False

    @classmethod
    def boot_completed(cls):
        """Android finished booting (the device can be 'online' before that)."""
        import adbutils
        try:
            return adbutils.device(ADB_ADDRESS).getprop("sys.boot_completed").strip() == "1"
        except Exception:
            return False

    @classproperty
    def adbutils_device(cls):
        if cls._adbutils_device is None: cls.connect()
        return DeviceProxy(cls, "_adbutils_device")

    @classproperty
    def minitouch_device(cls):
        if cls._minitouch_device is None: cls.connect()
        return DeviceProxy(cls, "_minitouch_device")

    @classproperty
    def uiautomator_device(cls):
        if cls._uiautomator_device is None: cls.connect()
        return DeviceProxy(cls, "_uiautomator_device", max_retries=0)

    @classproperty
    def adbutils_device_no_retry(cls):
        if cls._adbutils_device is None: cls.connect()
        return DeviceProxy(cls, "_adbutils_device", max_retries=0)

    @classproperty
    def minitouch_device_no_retry(cls):
        if cls._minitouch_device is None: cls.connect()
        return DeviceProxy(cls, "_minitouch_device", max_retries=0)

    @classproperty
    def uiautomator_device_no_retry(cls):
        if cls._uiautomator_device is None: cls.connect()
        return DeviceProxy(cls, "_uiautomator_device", max_retries=0)

class Input_Handler:
    @classmethod
    def _to_raw(cls, x_frac, y_frac):
        raw_w = int(ADB_Manager.minitouch_device.connection.max_x)
        raw_h = int(ADB_Manager.minitouch_device.connection.max_y)
        if raw_w >= raw_h:
            return int(x_frac * raw_w), int(y_frac * raw_h)
        # ponytail: not a "can't be set to landscape" limitation -- the display is
        # landscape (WINDOW_DIMS) same as any other emulator. MuMu's virtual touch
        # device just reports raw axes in native-portrait order regardless of the
        # display orientation, so we compensate for that rotation here. Assumes a
        # 90deg CW rotation, the common case for phone-profile emulators; upgrade
        # path: detect rotation direction if a 270deg case is ever seen.
        return int(raw_w - y_frac * raw_w), int(x_frac * raw_h)

    @classmethod
    def down(cls, x, y, pointer=0):
        from pyminitouch import CommandBuilder
        if x < 0: x = 1 + x
        if y < 0: y = 1 + y
        x, y = cls._to_raw(x, y)
        builder = CommandBuilder()
        if isinstance(pointer, int):
            builder.down(pointer, x, y, 100)
        elif isinstance(pointer, (list, tuple)):
            for p in pointer:
                builder.down(p, x, y, 100)
        cls._publish(builder)

    @classmethod
    def _publish(cls, builder):
        """Send touch commands; if the minitouch socket died, restart minitouch once and resend."""
        content = builder._content
        try:
            builder.publish(ADB_Manager.minitouch_device.connection)
        except (OSError, ConnectionError, BrokenPipeError) as e:
            builder.reset()
            logger.warning(f"Touch connection lost ({type(e).__name__}), restarting minitouch")
            ADB_Manager.reset_minitouch()
            ADB_Manager.minitouch_device.connection.send(content + "c\n")

    @classmethod
    def move(cls, x, y, pointer=0):
        """Move a finger that is already down (drag)."""
        from pyminitouch import CommandBuilder
        if x < 0: x = 1 + x
        if y < 0: y = 1 + y
        x, y = cls._to_raw(x, y)
        builder = CommandBuilder()
        builder.move(pointer, x, y, 100)
        cls._publish(builder)

    @classmethod
    def up(cls, pointer=0):
        from pyminitouch import CommandBuilder
        builder = CommandBuilder()
        if isinstance(pointer, int):
            builder.up(pointer)
        elif isinstance(pointer, (list, tuple)):
            for p in pointer:
                builder.up(p)
        cls._publish(builder)

    @classmethod
    def click(cls, x, y, n=1, delay=0, pointer=0):
        import time
        from pyminitouch import CommandBuilder
        if x < 0: x = 1 + x
        if y < 0: y = 1 + y
        x, y = cls._to_raw(x, y)
        builder = CommandBuilder()
        for _ in range(n):
            builder.down(pointer, x, y, 100)
            builder.commit()
            builder.up(pointer)
            cls._publish(builder)
            time.sleep(delay)

    @classmethod
    def click_exit(cls, x=0.99, y=0.99, n=1, delay=0):
        cls.click(x, y, n, delay=delay)

    @classmethod
    def multi_click(cls, x1, y1, x2, y2, duration=0):
        ADB_Manager.minitouch_device.tap([cls._to_raw(x1, y1), cls._to_raw(x2, y2)], duration=duration)

    @classmethod
    def swipe(cls, x1, y1, x2, y2, duration=100, hold_end_time=0, inter_points=0, pointer=0):
        import time, numpy as np
        from pyminitouch import CommandBuilder

        if x1 < 0: x1 = 1 + x1
        if y1 < 0: y1 = 1 + y1
        if x2 < 0: x2 = 1 + x2
        if y2 < 0: y2 = 1 + y2

        builder = CommandBuilder()

        x1, y1 = cls._to_raw(x1, y1)
        x2, y2 = cls._to_raw(x2, y2)

        x_points = np.linspace(x1, x2, inter_points + 2, dtype=int)
        y_points = np.linspace(y1, y2, inter_points + 2, dtype=int)
        dt = duration / (inter_points + 1)
        
        builder.down(pointer, x1, y1, pressure=100)
        cls._publish(builder)
        for x, y in zip(x_points, y_points):
            builder.move(pointer, x, y, pressure=100)
            cls._publish(builder)
            if dt > 0: time.sleep(dt / 1000)
        if hold_end_time > 0: time.sleep(hold_end_time / 1000)
        builder.up(pointer)
        cls._publish(builder)

    @classmethod
    def swipe_up(cls, y1=1.0, y2=0.0, x=1.0, **kwargs):
        cls.swipe(x, y1, x, y2, **kwargs)

    @classmethod
    def swipe_down(cls, y1=0.1, y2=1.0, x=1.0, **kwargs):
        cls.swipe(x, y1, x, y2, **kwargs)

    @classmethod
    def swipe_left(cls, x1=1.0, x2=0.0, y=1.0, **kwargs):
        cls.swipe(x1, y, x2, y, **kwargs)

    @classmethod
    def swipe_right(cls, x1=0.0, x2=1.0, y=1.0, **kwargs):
        cls.swipe(x1, y, x2, y, **kwargs)

    @classmethod
    def zoom(cls, dir="out", percent=1.0):
        from pyminitouch import CommandBuilder
        
        builder = CommandBuilder()

        left_in = cls._to_raw(0.15 + 0.30*percent, 0.5)
        left_out = cls._to_raw(0.15, 0.5)
        right_in = cls._to_raw(0.85 - 0.30*percent, 0.5)
        right_out = cls._to_raw(0.85, 0.5)
        
        start = [left_in, right_in] if dir=="in" else [left_out, right_out]
        end = [left_out, right_out] if dir=="in" else [left_in, right_in]
        
        builder.down(0, *start[0], pressure=100)
        builder.down(1, *start[1], pressure=100)
        cls._publish(builder)
        builder.move(0, *end[0], pressure=100)
        builder.move(1, *end[1], pressure=100)
        builder.commit()
        cls._publish(builder)
        builder.up(0)
        builder.up(1)
        cls._publish(builder)

class Frame_Handler:
    pool = None
    cached_frame = None

    @classmethod
    def grayscale(cls, frame):
        import cv2
        if len(frame.shape) == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        return frame
    
    @classmethod
    def high_contrast(cls, frame, thresh=200):
        frame = cls.grayscale(frame)
        frame[frame < thresh] = 0
        return frame
    
    @classmethod
    def crop(cls, frame, x1, y1, x2, y2):
        if x1 < 0: x1 = 1 + x1
        if y1 < 0: y1 = 1 + y1
        if x2 < 0: x2 = 1 + x2
        if y2 < 0: y2 = 1 + y2
        h, w = frame.shape[:2]
        return frame[int(h*y1):int(h*y2), int(w*x1):int(w*x2)]
    
    @classmethod
    def prefilter(cls, source, target):
        import numpy as np
        
        def pack(img):
            if img.ndim == 2: return img.astype(np.uint32)
            else: return (
                (img[..., 0].astype(np.uint32) << 16) |
                (img[..., 1].astype(np.uint32) << 8)  |
                (img[..., 2].astype(np.uint32))
            )

        mask_not_in_img1 = ~np.isin(pack(target), np.unique(pack(source)))
        out = target.copy()
        out[mask_not_in_img1] = 0
        return out

    @classmethod
    def get_frame(cls, grayscale=True, high_contrast=False, thresh=200, use_cached=False):
        import cv2, numpy as np
        if use_cached and cls.cached_frame is not None:
            frame = cls.cached_frame.copy()
        else:
            try: frame = ADB_Manager.adbutils_device_no_retry.framebuffer() # faster than screenshot but potentially unstable
            except (KeyboardInterrupt, SystemExit): raise
            except: frame = ADB_Manager.adbutils_device.screenshot()
            frame = np.array(frame)[..., :3]
            if (frame.shape[1], frame.shape[0]) != tuple(WINDOW_DIMS):
                frame = cv2.resize(frame, WINDOW_DIMS, interpolation=cv2.INTER_NEAREST)
            cls.cached_frame = frame.copy()
        # if configs.DEBUG: cls.save_frame(frame, "frame.png")
        if high_contrast: frame = cls.high_contrast(frame, thresh)
        elif grayscale: frame = cls.grayscale(frame)
        return frame

    @classmethod
    def get_frame_section(cls, x1, y1, x2, y2, high_contrast=False, thresh=200, grayscale=True, use_cached=False):
        frame = cls.get_frame(grayscale=grayscale, high_contrast=high_contrast, thresh=thresh, use_cached=use_cached)
        frame = cls.crop(frame, x1, y1, x2, y2)
        return frame

    @classmethod
    def save_frame(cls, frame, filename="frame.png"):
        import cv2
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{INSTANCE_ID}_{filename}" if INSTANCE_ID not in (None, "") else filename
        cv2.imwrite(DEBUG_DIR / filename, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    @classmethod
    def screenshot(cls, filename="screenshot.png", grayscale=False):
        frame = cls.get_frame(grayscale=grayscale)
        cls.save_frame(frame, filename)
    
    @classmethod
    def locate(
        cls,
        template,
        frame=None,
        grayscale=True,
        thresh=0,
        ref="cc",
        null_val=None,
        normalize=True,
        prefilter=False,
        return_confidence=False,
        return_all=False,
        use_cached=False,
    ):
        import cv2, numpy as np

        if grayscale: template = cls.grayscale(template)
        h, w = template.shape[:2]
        if frame is None:
            frame = cls.get_frame(grayscale=grayscale, use_cached=use_cached)
        elif grayscale: frame = cls.grayscale(frame)
        if prefilter: frame = cls.prefilter(template, frame)
        fh, fw = frame.shape[:2]
        nh = fh if normalize else 1
        nw = fw if normalize else 1
        
        if h > fh or w > fw:
            if return_all:
                return []
            if return_confidence:
                return null_val, null_val, 0
            return null_val, null_val

        res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        # logger.debug(f"locate confidence: {max_val}")

        if return_all:
            ys, xs = np.where(res >= thresh)
            results = []
            for (x_loc, y_loc, val) in zip(xs, ys, res[ys, xs]):
                if ref[0] == 'c':
                    x_loc += w / 2
                elif ref[0] == 'r':
                    x_loc += w
                if ref[1] == 'c':
                    y_loc += h / 2
                elif ref[1] == 'b':
                    y_loc += h

                if return_confidence:
                    results.append((x_loc / nw, y_loc / nh, float(val)))
                else:
                    results.append((x_loc / nw, y_loc / nh))
            if len(results) == 0: results = [(null_val, null_val, 0)] if return_confidence else [(null_val, null_val)]

            results.sort(key=lambda r: r[-1] if return_confidence else 0, reverse=True)
            return results
        
        if max_val > thresh:
            x_loc, y_loc = max_loc
            if ref[0] == 'c': x_loc += w / 2
            elif ref[0] == 'r': x_loc += w
            if ref[1] == 'c': y_loc += h / 2
            elif ref[1] == 'b': y_loc += h
            if return_confidence:
                return x_loc / nw, y_loc / nh, max_val
            else:
                return x_loc / nw, y_loc / nh
        if return_confidence:
            return null_val, null_val, max_val
        return null_val, null_val

    @classmethod
    def batch_locate(cls, templates, frame=None, grayscale=True, thresh=0, ref="cc", null_val=None, normalize=True, prefilter=False, return_confidence=False, return_all=False, use_cached=False):
        from concurrent.futures import ThreadPoolExecutor
        
        if cls.pool is None:
            cls.pool = ThreadPoolExecutor()
            Exit_Handler.register(cls.pool.shutdown)
        
        frame = cls.get_frame(grayscale=grayscale, use_cached=use_cached) if frame is None else frame
        
        threads = []
        for template in templates:
            threads.append(cls.pool.submit(
                cls.locate,
                template=template,
                frame=frame,
                grayscale=grayscale,
                thresh=thresh,
                ref=ref,
                null_val=null_val,
                normalize=normalize,
                prefilter=prefilter,
                return_confidence=return_confidence,
                return_all=return_all
            ))
        return [thread.result() for thread in threads]

class Dev_Tools:
    @classmethod
    def optimal_template_font_size(cls, frame, text, font, font_size_range=(1, 100), color=(255, 255, 255), grayscale=True, prefilter=True, return_results=False, plot_results=False):
        import numpy as np, matplotlib.pyplot as plt
        templates = [render_text(text, font, size, color) for size in range(font_size_range[0], font_size_range[1] + 1)]
        results = Frame_Handler.batch_locate(templates, frame=frame, grayscale=grayscale, prefilter=prefilter, return_confidence=True)
        confidences = [res[2] for res in results]
        highest_conf = max(confidences)
        optimal_size = confidences.index(highest_conf) + font_size_range[0]
        
        if plot_results:
            plt.plot(np.arange(font_size_range[0], font_size_range[1] + 1), confidences)
            plt.xlabel("Font Size")
            plt.ylabel("Confidence")
            plt.title(f"Optimal Font Size: {optimal_size} ({highest_conf:.2f})")
            plt.show()
        
        if return_results:
            return optimal_size, results
        return optimal_size

    @classmethod
    def optimal_template_scale(cls, frame, template, scale_range=(0.0, 1.0), step=0.1, grayscale=True, prefilter=True, return_results=False, plot_results=False):
        import cv2, numpy as np, matplotlib.pyplot as plt
        scale_range = np.arange(scale_range[0], scale_range[1] + step, step)
        templates = [cv2.resize(template, (0, 0), fx=scale, fy=scale) for scale in scale_range]
        results = Frame_Handler.batch_locate(templates, frame=frame, grayscale=grayscale, prefilter=prefilter, return_confidence=True)
        confidences = [res[2] for res in results]
        highest_conf = max(confidences)
        optimal_size = scale_range[confidences.index(highest_conf)]
        
        if plot_results:
            plt.plot(scale_range, confidences)
            plt.xlabel("Scale")
            plt.ylabel("Confidence")
            plt.title(f"Optimal Scale: {optimal_size:.2f} ({highest_conf:.2f})")
            plt.show()
        
        if return_results:
            return optimal_size, results
        return optimal_size

# ======================================================================
# Error reporter: every WARNING/ERROR is stored with the bot's current step
# and (for errors) a screenshot of the emulator, so the GUI can show exactly
# what went wrong and where.
# ======================================================================
ERRORS_DIR = APP_DATA_DIR / "errors"

def set_phase(name):
    """What the bot is doing right now (shown next to every error and on the GUI home page)."""
    import json, time
    TEMP_CACHE["phase"] = name
    TEMP_CACHE["phase_t"] = time.time()
    try:
        d = APP_DATA_DIR / "phase"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{INSTANCE_ID}.json").write_text(json.dumps({
            "phase": name, "t": time.time(), "adb": ADB_ADDRESS,
            "emulator": current_emulator(), "pid": __import__("os").getpid(),
        }))
    except Exception:
        pass

# ======================================================================
# Watchdog: a step that writes nothing to the log for too long is stuck (a popup the bot doesn't
# know, a screen that never came, a loop waiting forever). It is released and the game reopened.
# ======================================================================
WATCHDOG_LIMITS = {"commands": 900, "village_scan": 300, "home_attack": 600, "builder_attack": 600, "spend_full": 1500, "home_upgrades": 900,
                   "builder_upgrades": 900, "walls_farming": 900, "start_game": 300, "army_prepare": 300}
WATCHDOG_SKIP = {"idle", "recording", "army_learning", "capturing", "break", "", None}

def start_watchdog(default_limit=420):
    import threading, time
    TEMP_CACHE["last_log"] = time.time()
    logger.add(lambda _m: TEMP_CACHE.__setitem__("last_log", time.time()), level="INFO")

    def loop():
        while True:
            time.sleep(20)
            try:
                phase = TEMP_CACHE.get("phase")
                if phase in WATCHDOG_SKIP: continue
                quiet = time.time() - max(TEMP_CACHE.get("phase_t", 0), TEMP_CACHE.get("last_log", 0))
                if quiet > WATCHDOG_LIMITS.get(phase, default_limit):
                    logger.warning(f"Watchdog: stuck in '{phase}' for {int(quiet)}s, restarting the step")
                    TEMP_CACHE["stuck"] = True
                    TEMP_CACHE["restart_game"] = True
                    TEMP_CACHE["phase_t"] = time.time()
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="watchdog").start()

def install_error_reporter():
    import threading, time, traceback
    import stats as _stats

    state = {"last_shot": 0.0, "busy": False}
    shot_dir = ERRORS_DIR / str(INSTANCE_ID)

    def save_screenshot(path):
        # raw device, no proxy / no logging: must never recurse into the logger
        try:
            import cv2, numpy as np
            dev = ADB_Manager._adbutils_device
            if dev is None: return
            img = np.array(dev.screenshot())[..., :3]
            path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
        except Exception:
            pass
        finally:
            state["busy"] = False

    def sink(message):
        try:
            rec = message.record
            level = rec["level"].name
            text = str(rec["message"]).strip()
            first = text.splitlines()[0] if text else ""
            exc = rec.get("exception")
            detail = ""
            if exc is not None and exc.type is not None:
                detail = f"{exc.type.__name__}: {exc.value}"
                tb = traceback.extract_tb(exc.traceback)[-3:] if exc.traceback else []
                where = " <- ".join(f"{Path(f.filename).name}:{f.lineno} {f.name}" for f in reversed(tb))
            else:
                where = f"{Path(rec['file'].path).name}:{rec['line']} {rec['function']}"
            entry = {"level": level, "message": first, "detail": detail, "where": where,
                     "phase": TEMP_CACHE.get("phase", "")}
            now = time.time()
            if level in ("ERROR", "CRITICAL") and not state["busy"] and now - state["last_shot"] > 20:
                state["busy"], state["last_shot"] = True, now
                name = time.strftime("%Y%m%d_%H%M%S") + ".jpg"
                entry["shot"] = name
                threading.Thread(target=save_screenshot, args=(shot_dir / name,), daemon=True).start()
            _stats.record(INSTANCE_ID, "error" if level in ("ERROR", "CRITICAL") else "warning", **entry)
        except Exception:
            pass

    logger.add(sink, level="WARNING", enqueue=False, catch=True)

    # keep the screenshot folder small
    try:
        shots = sorted(shot_dir.glob("*.jpg"))
        for old in shots[:-60]: old.unlink()
    except OSError:
        pass

# ======================================================================
# Taught templates (see teach.py): find / tap / read what the user taught
# ======================================================================
def find_taught(key, multi=False, thresh=0.82, frame=None):
    """Positions (x, y fractions) of a taught button on screen. [] if not taught / not found."""
    import teach
    tpl = teach.template(key)
    if tpl is None: return []
    if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
    if not multi:
        x, y = Frame_Handler.locate(tpl, frame, grayscale=False, thresh=thresh)
        return [] if x is None else [(x, y)]
    hits = Frame_Handler.locate(tpl, frame, grayscale=False, thresh=thresh, return_all=True, return_confidence=True)
    out = []
    for x, y, c in hits: # best first; drop neighbours of an accepted hit
        if x is None: continue
        if all(abs(x - ox) > 0.025 or abs(y - oy) > 0.035 for ox, oy in out): out.append((x, y))
    return out

def tap_taught(key, multi=False, timeout=3, thresh=0.82):
    """Tap a taught button (all matches when multi). Returns how many taps were made."""
    import time
    end = time.time() + timeout
    while True:
        pts = find_taught(key, multi=multi, thresh=thresh)
        if pts or time.time() >= end: break
        time.sleep(0.4)
    for x, y in pts:
        Input_Handler.click(x, y)
        time.sleep(0.35)
    return len(pts)

def read_taught_number(key, frame=None):
    """Read the number inside a taught region (e.g. the opponent's loot)."""
    import teach
    r = teach.region(key)
    if r is None: return None
    if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
    crop = Frame_Handler.high_contrast(Frame_Handler.crop(frame, *r), thresh=190)
    return OCR_Handler.get_number(crop)

def start_capture_service():
    """Serve "take a screenshot" requests from the GUI's Teach tab (polls a request file)."""
    import threading, time, teach
    def loop():
        while True:
            time.sleep(1)
            try:
                req = teach.capture_request_path(INSTANCE_ID)
                if not req.exists(): continue
                req.unlink()
                import cv2
                frame = Frame_Handler.get_frame(grayscale=False)
                out = teach.capture_path(INSTANCE_ID)
                out.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="capture").start()

# ======================================================================
# Pre-flight: before the first cycle make sure the emulator is connected, the display is
# exactly what the images/positions were made for, the game is installed and screenshots
# and touches work. Fixes what it can by itself, otherwise waits and says what to change.
# ======================================================================
TARGET_SIZE = (1920, 1080)
TARGET_DPI = 240 # BlueStacks' default for 1920x1080 (the device profile the templates come from)

def _target():
    w, h, d = getattr(configs, "DISPLAY_TARGET", None) or (*TARGET_SIZE, TARGET_DPI)
    return (int(w), int(h)), int(d)

def display_info():
    """-> (width, height, dpi) the game really sees (override values win over physical ones)."""
    import re
    sh = lambda c: ADB_Manager.adbutils_device.shell(c)
    sizes = re.findall(r"(\d+)x(\d+)", sh("wm size"))
    dens = re.findall(r"(\d+)", sh("wm density"))
    w, h = map(int, sizes[-1]) if sizes else (None, None)
    return w, h, int(dens[-1]) if dens else None

def display_ok(w, h, d):
    size, dpi = _target()
    return w is not None and {w, h} == set(size) and d == dpi

def fix_display(w, h, d):
    """LDPlayer: change the copy's resolution + DPI (restart). Others: fix the DPI live if only that is off."""
    import time
    (tw, th), td = _target()
    if Emulator_Manager is LDPlayer_Manager and not never_close(): # changing it the LDPlayer way restarts the emulator
        idx = str(LDPlayer_Manager.index)
        logger.info(f"Pre-flight: setting LDPlayer to {tw}x{th} {td} DPI (the emulator restarts)")
        try: LDPlayer_Manager.stop()
        except Exception: pass
        LDPlayer_Manager._run("modify", "--index", idx, "--resolution", f"{tw},{th},{td}")
        LDPlayer_Manager.start()
        time.sleep(5)
        ADB_Manager.connect(timeout=180)
        return True
    ADB_Manager.adbutils_device.shell(f"wm size {tw}x{th}")
    ADB_Manager.adbutils_device.shell(f"wm density {td}")
    logger.info(f"Pre-flight: display changed from {w}x{h} {d} DPI to {tw}x{th} {td} DPI")
    return True

# ---------------------------------------------------------------- other screen sizes
# The built-in images were cut from a 1920x1080 screen. On another size the game draws its
# buttons smaller/bigger, so the bot measures that "UI scale" once (by finding the gold icon
# of the village at many sizes) and shrinks every built-in image to match.
UI_SCALE = 1.0
_ORIGINAL_ASSETS = {}

def detect_ui_scale(frame=None):
    import cv2, numpy as np
    if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
    if tuple(frame.shape[:2][::-1]) == TARGET_SIZE: return 1.0
    best_v, best_s = 0, None
    for name in ("home_gold", "builder_gold"):
        tpl = (_ORIGINAL_ASSETS.get("upgrader") or Asset_Manager.upgrader_assets).get(name)
        if tpl is None: continue
        for s in np.arange(0.25, 1.05, 0.0125):
            t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            if t.shape[0] < 8 or t.shape[0] > frame.shape[0] or t.shape[1] > frame.shape[1]: continue
            v = cv2.minMaxLoc(cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED))[1]
            if v > best_v: best_v, best_s = v, float(s)
    return round(best_s, 4) if best_v >= 0.8 else None

def apply_ui_scale(scale):
    """Resize every built-in image (in place, so all holders see it) to the measured UI scale."""
    global UI_SCALE
    import cv2
    groups = {"misc": Asset_Manager.misc_assets, "upgrader": Asset_Manager.upgrader_assets, "attacker": Asset_Manager.attacker_assets}
    for g, d in groups.items():
        orig = _ORIGINAL_ASSETS.setdefault(g, dict(d))
        for k, img in orig.items():
            d[k] = img if scale == 1.0 else cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    UI_SCALE = scale

def _scale_file():
    return Path.home() / ".CoC_Bot" / "ui_scale.json"

def setup_ui_scale(size):
    """Use the saved scale for this screen size, else measure it (the village must be on screen)."""
    import json, time
    key = f"{size[0]}x{size[1]}"
    if tuple(size) == TARGET_SIZE:
        apply_ui_scale(1.0); return 1.0
    try: saved = json.loads(_scale_file().read_text()).get(key)
    except (OSError, ValueError): saved = None
    scale = None
    for _ in range(12): # up to ~1 minute while the game loads
        scale = detect_ui_scale()
        if scale: break
        time.sleep(5)
    if scale:
        try:
            data = json.loads(_scale_file().read_text()) if _scale_file().exists() else {}
            data[key] = scale
            _scale_file().write_text(json.dumps(data))
        except (OSError, ValueError): pass
        logger.info(f"Pre-flight: game size measured, images scaled to {scale:.2f}")
    else:
        scale = saved or round(size[1] / TARGET_SIZE[1], 4)
        logger.warning(f"Pre-flight: could not measure the game size (open the village screen); using {scale:.2f}")
    apply_ui_scale(scale)
    return scale

def preflight():
    import time
    logger.info("Pre-flight check: starting")
    (tw, th), td = _target()
    warned = 0
    while True:
        problems = []
        try:
            # already connected (the emulator start just did it): don't rebuild minitouch a second time,
            # two minitouch servers fight over the same socket
            alive = False
            try: alive = ADB_Manager._adbutils_device is not None and "ok" in ADB_Manager._adbutils_device.shell("echo ok")
            except Exception: alive = False
            if not alive: ADB_Manager.connect(timeout=120)
            for _ in range(120):
                if ADB_Manager.boot_completed(): break
                time.sleep(1)
            logger.info("Pre-flight: emulator connected ✓")

            w, h, d = display_info()
            if not display_ok(w, h, d):
                logger.warning(f"Pre-flight: display is {w}x{h} {d} DPI, needs {tw}x{th} {td} DPI")
                if fix_display(w, h, d): w, h, d = display_info()
            if display_ok(w, h, d): logger.info(f"Pre-flight: display {tw}x{th} {td} DPI ✓")
            else: problems.append(f"display is {w}x{h} {d} DPI, needs {tw}x{th} {td} DPI")

            if "com.supercell.clashofclans" in ADB_Manager.adbutils_device.shell("pm list packages com.supercell.clashofclans"):
                logger.info("Pre-flight: Clash of Clans installed ✓")
            else:
                problems.append("Clash of Clans is not installed")

            frame = Frame_Handler.get_frame(grayscale=False)
            fh, fw = frame.shape[:2]
            if (fw, fh) == (tw, th): logger.info(f"Pre-flight: screenshots {fw}x{fh} ✓")
            else: problems.append(f"screenshots are {fw}x{fh} (landscape {tw}x{th} needed)")
            if (fw, fh) == (tw, th) and (tw, th) != TARGET_SIZE:
                try: start_coc()
                except Exception: pass
                setup_ui_scale((fw, fh))

            conn = ADB_Manager.minitouch_device.connection
            if int(conn.max_x) > 0 and int(conn.max_y) > 0: logger.info("Pre-flight: touch ready ✓")
            else: problems.append("touch not ready")
        except (KeyboardInterrupt, SystemExit): raise
        except Exception as e:
            problems.append(f"{type(e).__name__}: {e}")

        if not problems:
            logger.info("Pre-flight check passed: everything is ready ✓")
            return True
        if time.monotonic() - warned > 60:
            for p in problems: logger.error(f"Pre-flight problem: {p}")
            logger.error("Pre-flight: the bot waits until this is fixed (checks again every 20 seconds)")
            warned = time.monotonic()
        update_status("error")
        time.sleep(20)

def start_record_service():
    """Serve "record a battle" requests from the GUI: wait for the user's own attack and record their touches."""
    import threading, time, recorder
    def battle_visible():
        if find_taught("end_battle"): return True
        try:
            from attacker import Attacker
            a = getattr(battle_visible, "a", None) or Attacker()
            battle_visible.a = a
            return a.in_battle()
        except Exception:
            return False
    def record(name):
        logger.info(f"Battle recording '{name}': start an attack in the game yourself")
        deadline = time.monotonic() + 300
        while not battle_visible():
            if time.monotonic() > deadline:
                logger.warning("Battle recording cancelled: no battle started within 5 minutes"); return
            time.sleep(1)
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_up(y1=0.5)
        time.sleep(0.8)
        found = recorder.find_touch_device(lambda c: ADB_Manager.adbutils_device.shell(c))
        if not found:
            logger.error("Battle recording failed: touch device not found"); return
        rec = recorder.Recorder(ADB_Manager._adb_exe or "adb", ADB_ADDRESS, *found)
        rec.start()
        logger.info("Battle recording: attack now, every tap is being recorded")
        start, gone = time.monotonic(), 0
        while time.monotonic() - start < 200:
            time.sleep(1)
            gone = 0 if battle_visible() else gone + 1
            if gone >= 4: break
        rec.stop()
        time.sleep(0.3)
        data = rec.save(name)
        taps = sum(1 for e in data["events"] if e["type"] == "down")
        logger.info(f"Battle recording '{name}' saved: {taps} taps, {data['duration']:.0f} seconds")
    def loop():
        while True:
            time.sleep(1)
            try:
                req = recorder.take_request(INSTANCE_ID)
                if req: record(req.get("name") or "battle")
            except Exception:
                logger.exception("Battle recording failed")
    threading.Thread(target=loop, daemon=True, name="recorder").start()

# ======================================================================
# Automatic learning: read the screen with word positions, learn buttons
# by their text, learn the enemy loot numbers, and record unknown screens.
# ======================================================================
AUTO_WORDS = {
    "next_button":    ["next"],
    "return_home":    ["return home", "return"],
    "end_battle":     ["end battle", "surrender"],
    "okay_button":    ["okay"],
    "collect_button": ["collect"],
    "train_button":   ["quick train", "train again", "train"],
}
# words on popups that are safe to press to get out of the way
# only buttons that close / dismiss a window — never ones that take, buy or start something
DISMISS_WORDS = ["reload", "try again", "retry", "later", "not now", "close", "okay", "continue", "got it", "tap to continue"]

def ocr_boxes(frame):
    """[(text, x1, y1, x2, y2, conf)] with fractions of the frame. easyocr first, Tesseract TSV fallback."""
    import numpy as np, cv2
    h, w = frame.shape[:2]
    if w > 1300: # buttons/numbers are big: half resolution reads them fine and ~4x faster
        frame = cv2.resize(frame, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
    out = []
    try:
        if not hasattr(OCR_Handler, "reader"):
            import easyocr
            OCR_Handler.reader = easyocr.Reader(['en'], gpu=True)
        for pts, text, conf in OCR_Handler.reader.readtext(frame, detail=1):
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            if text.strip(): out.append((text.strip(), min(xs) / w, min(ys) / h, max(xs) / w, max(ys) / h, float(conf)))
        return out
    except (KeyboardInterrupt, SystemExit): raise
    except Exception:
        pass
    try: # Tesseract: one word per row
        import subprocess, cv2
        exe = Tesseract.find()
        if not exe: return out
        ok, png = cv2.imencode(".png", cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY) if frame.ndim == 3 else frame)
        res = subprocess.run([exe, "stdin", "stdout", "--psm", "11", "tsv"], input=png.tobytes(), capture_output=True, timeout=20, **_no_window())
        for row in res.stdout.decode("utf-8", "ignore").splitlines()[1:]:
            c = row.split("\t")
            if len(c) < 12 or not c[11].strip(): continue
            x, y, bw, bh, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
            out.append((c[11].strip(), x / w, y / h, (x + bw) / w, (y + bh) / h, conf / 100))
    except Exception:
        pass
    return out

def _word_hit(text, word):
    from rapidfuzz import fuzz
    t = text.lower().strip()
    return word in t or (len(word) >= 4 and fuzz.ratio(t, word) >= 80)

class Auto_Learn:
    """Learns taught-template items by itself, so the user doesn't have to."""
    enabled = True
    tried = {}            # key -> last attempt time (don't OCR the same thing over and over)

    @classmethod
    def learn_button(cls, key, frame=None, tap=False, min_interval=20):
        """Find the button by the word written on it; save its image; optionally tap it."""
        import time, teach
        if not cls.enabled or key not in AUTO_WORDS: return None
        if time.time() - cls.tried.get(key, 0) < min_interval: return None
        cls.tried[key] = time.time()
        if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
        boxes = ocr_boxes(frame)
        for word in AUTO_WORDS[key]:
            for text, x1, y1, x2, y2, conf in boxes:
                if conf < 0.3 or not _word_hit(text, word): continue
                # the button is a bit bigger than its label
                bw, bh = x2 - x1, y2 - y1
                rect = (x1 - bw * 0.25, y1 - bh * 0.6, x2 + bw * 0.25, y2 + bh * 0.6)
                try:
                    if not teach.taught(key) or teach.load_meta().get(key, {}).get("auto"):
                        teach.teach_array(key, rect, frame, auto=True)
                        logger.info(f"Learned '{key}' automatically")
                except Exception:
                    pass
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                if tap: Input_Handler.click(cx, cy)
                return (cx, cy)
        return None

    @classmethod
    def learn_enemy_loot(cls, frame=None):
        """On an enemy base: find "Available Loot" and the numbers under it (gold, elixir, dark)."""
        import re, time, teach
        if not cls.enabled: return False
        if all(teach.taught(k) for k in ("enemy_gold", "enemy_elixir")): return True
        if time.time() - cls.tried.get("enemy_loot", 0) < 30: return False
        cls.tried["enemy_loot"] = time.time()
        if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
        h, w = frame.shape[:2]
        left = frame[:int(h * 0.5), :int(w * 0.35)] # loot is always in the top-left corner
        boxes = ocr_boxes(left)
        boxes = [(t, x1 * 0.35, y1 * 0.5, x2 * 0.35, y2 * 0.5, c) for t, x1, y1, x2, y2, c in boxes]
        label = next((b for b in boxes if "loot" in b[0].lower() or "available" in b[0].lower()), None)
        nums = []
        for text, x1, y1, x2, y2, conf in boxes:
            digits = re.sub(r"[^0-9]", "", fix_digits(text))
            if len(digits) < 2 or len(digits) < len(text.replace(" ", "")) * 0.6: continue
            if label and y1 < label[2]: continue
            nums.append((y1, (x1, y1, x2, y2)))
        nums.sort()
        names = ["enemy_gold", "enemy_elixir", "enemy_dark"]
        for name, (_, (x1, y1, x2, y2)) in zip(names, nums[:3]):
            pad = (y2 - y1) * 0.25
            try:
                if not teach.taught(name) or teach.load_meta().get(name, {}).get("auto"):
                    teach.teach_array(name, (x1 - pad, y1 - pad, x2 + pad * 3, y2 + pad), frame, auto=True)
            except Exception:
                pass
        if nums: logger.info(f"Learned enemy loot positions automatically ({min(3, len(nums))} numbers)")
        return len(nums) >= 2

    @classmethod
    def handle_unknown_screen(cls, phase=""):
        """
        The bot doesn't recognise the screen: read it, record it for the user,
        and press a harmless button (Later / Close / Okay / Continue…) if there is one.
        """
        import time, teach
        if not cls.enabled: return False
        if time.time() - cls.tried.get("unknown", 0) < 15: return False
        cls.tried["unknown"] = time.time()
        try:
            frame = Frame_Handler.get_frame(grayscale=False)
            boxes = ocr_boxes(frame)
            words = [b[0] for b in boxes if b[5] > 0.3]
            action = ""
            # a screen Claude already explained (knowledge fetched from the learning repo)
            try:
                import learn_sync
                rule = learn_sync.match_screen(words, phase or TEMP_CACHE.get("phase", ""))
                if rule and rule.get("no_action"):      # a known screen that needs nothing (e.g. the village itself)
                    return False
                if rule and learn_sync.run_actions(rule, boxes):
                    logger.info(f"Known screen (taught by Claude): {rule.get('title') or rule.get('id')}")
                    return True
            except (KeyboardInterrupt, SystemExit): raise
            except Exception: pass
            # never confirm leaving the game: on an exit/quit dialog press Cancel (or nothing)
            text_all = " ".join(words).lower()
            danger = any(w in text_all for w in ("exit", "quit", "leave", "log out", "logout", "disconnect", "sign out", "delete", "buy", "purchase", "gems"))
            if danger:
                cancel = next((b for b in boxes if b[5] > 0.4 and (_word_hit(b[0], "cancel") or _word_hit(b[0], "no") or _word_hit(b[0], "close"))), None)
                if cancel:
                    Input_Handler.click((cancel[1] + cancel[3]) / 2, (cancel[2] + cancel[4]) / 2)
                    action = f"tap:{cancel[0]}"
                teach.record_discovery(INSTANCE_ID, frame, words, phase or TEMP_CACHE.get("phase", ""), action)
                logger.info(f"Unknown screen recorded ({len(words)} words){', pressed ' + repr(action[4:]) if action else ''}")
                return bool(action)
            for word in DISMISS_WORDS:
                hit = next((b for b in boxes if b[5] > 0.4 and _word_hit(b[0], word)), None)
                if hit:
                    Input_Handler.click((hit[1] + hit[3]) / 2, (hit[2] + hit[4]) / 2)
                    action = f"tap:{hit[0]}"
                    break
            teach.record_discovery(INSTANCE_ID, frame, words, phase or TEMP_CACHE.get("phase", ""), action)
            logger.info(f"Unknown screen recorded ({len(words)} words){', pressed ' + repr(action[4:]) if action else ''}")
            return bool(action)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.warning("Could not analyse the unknown screen")
            return False

def read_fraction(section):
    """Read a counter like "1/2" with Tesseract (fallback when the template digits don't match). -> (a, b) or None"""
    import re
    for img in (section,):
        text = Tesseract.read(img, digits=False, psm=7) or ""
        m = re.search(r"(\d+)\s*/\s*(\d+)", text.replace("O", "0").replace("o", "0"))
        if m: return int(m.group(1)), int(m.group(2))
    return None
