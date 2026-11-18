"""
Is the internet working? Checked when the game hangs on its loading screen, so the bot can say WHY instead of
closing and reopening the game in a loop:

  pc        this PC reaches the internet (Google's / Cloudflare's "are you online" addresses)
  emulator  LDPlayer itself reaches the internet (a ping from inside the emulator, over ADB)
  game      Clash of Clans' game server answers (gamea.clashofclans.com, port 9339)

check() -> {"pc": bool, "emulator": bool|None, "game": bool|None, "verdict": "...", "ar": "<Arabic sentence>"}
"""
import socket, time

GAME = ("gamea.clashofclans.com", 9339)


def _pc():
    import requests
    for url in ("https://connectivitycheck.gstatic.com/generate_204", "https://1.1.1.1/cdn-cgi/trace",
                "https://www.msftconnecttest.com/connecttest.txt", "https://api.github.com"):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code < 500: return True
        except Exception:
            continue
    return False


def _game():
    try:
        with socket.create_connection(GAME, timeout=5):
            return True
    except OSError:
        return False


def _emulator():
    """A ping from inside LDPlayer (None when it can't be asked)."""
    try:
        from utils import ADB_Manager
        dev = ADB_Manager.adbutils_device
        for host in ("8.8.8.8", "1.1.1.1"):
            out = dev.shell(f"ping -c 1 -W 3 {host} >/dev/null 2>&1 && echo OK || echo NO", timeout=10)
            if "OK" in str(out): return True
        return False
    except Exception:
        return None


def check():
    pc, game, emu = _pc(), _game(), _emulator()
    if not pc:
        verdict, ar = "pc_offline", "النت مقطوع على الجهاز نفسه — اتأكد من الواي فاي / الراوتر"
    elif emu is False:
        verdict, ar = "emulator_offline", "النت شغال على الجهاز بس LDPlayer مش واصل للنت — اقفل LDPlayer وافتحه تاني (أو شغّل النت من إعداداته)"
    elif not game:
        verdict, ar = "game_server", "النت شغال، بس سيرفر Clash of Clans مش بيرد — غالبًا صيانة أو مشكلة عندهم، البوت هيستنى ويجرّب تاني"
    else:
        verdict, ar = "ok", "النت شغال وسيرفر اللعبة بيرد — المشكلة من اللعبة نفسها (تحديث / تحميل بطيء)، البوت هيعيد فتحها"
    return {"pc": pc, "emulator": emu, "game": game, "verdict": verdict, "ar": ar, "t": time.time()}


def wait_until_online(running, logger=None, every=30, notify=None):
    """No internet: check every `every` seconds until it is back (or the bot is stopped). -> True when back."""
    told = False
    while running():
        r = check()
        if r["verdict"] in ("ok", "game_server") and r["pc"] and r["emulator"] is not False:
            if told and logger: logger.info("Internet is back — opening the game again")
            if told and notify:
                try: notify("✅ النت رجع — البوت بيفتح اللعبة ويكمّل")
                except Exception: pass
            return True
        if not told:
            told = True
            if logger: logger.warning(f"No internet ({r['verdict']}): waiting for it instead of reopening the game")
            if notify:
                try: notify("📡 " + r["ar"] + " — البوت مستني النت يرجع وهيكمّل لوحده")
                except Exception: pass
        time.sleep(every)
    return False
