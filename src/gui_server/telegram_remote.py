"""
Control the bot from the phone through the Telegram bot the user already set up for notifications.

Runs in the app (GUI server) as a background thread: reads the messages sent to the bot (getUpdates, long poll)
and answers ONLY the chat the notifications go to (the owner). Arabic or English words, with or without "/":
  الحالة / status      what every account is doing, resources, builders, last loot
  صورة / screen        a picture of the game screen now
  وقف / pause          pause all bots (or: وقف main)
  كمل / resume         resume them
  شغل / start          start the bots of the app's account list
  اقفل / stop          stop them
  احصائيات / stats     today's loot per account
  مساعدة / help        this list
"""
import json, threading, time

_STATE = {"offset": None, "thread": None, "chat": None}


def _token():
    try:
        import settings
        return (settings.load_app().get("telegram_bot_token") or "").strip()
    except Exception:
        return ""


def _api(token, method, http_timeout=35, **kw):
    """kw = the Telegram parameters (its own "timeout" is the long-poll wait)."""
    import requests
    files = kw.pop("files", None)
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=kw, files=files, timeout=http_timeout)
    return r.json() if r.status_code == 200 else {}


def _owner(token):
    """The chat the notifications go to (the first chat that wrote to the bot, as before)."""
    if _STATE["chat"]: return _STATE["chat"]
    try:
        import utils
        _STATE["chat"] = utils.Cache_Manager.get("telegram_chat_id", None)
    except Exception:
        pass
    return _STATE["chat"]


PHASES = {"home_attack": "بيهاجم", "start_game": "بيفتح اللعبة", "home_upgrades": "بيرقّي", "idle": "مستني",
          "read_resources": "بيقرا الموارد", "walls_farming": "بيرقّي أسوار", "builder_attack": "بيهاجم القرية الليلية",
          "builder_upgrades": "بيرقّي القرية الليلية", "army_prepare": "بيجهّز الجيش", "recording": "بيسجّل هجمة"}

COMMANDS = {
    "status": ("status", "الحالة", "حالة", "حاله"), "screen": ("screen", "صورة", "صوره", "شاشة", "شاشه"),
    "pause": ("pause", "وقف", "استنى"), "resume": ("resume", "كمل", "كمّل", "اكمل"),
    "start": ("start", "شغل", "شغّل", "ابدأ"), "stop": ("stop", "اقفل", "قفل"),
    "stats": ("stats", "احصائيات", "إحصائيات", "غنايم"), "net": ("net", "نت", "النت", "انترنت"), "help": ("help", "مساعدة", "مساعده", "اوامر", "أوامر"),
}


def _parse(text):
    words = text.strip().lstrip("/").split()
    if not words: return None, None
    w = words[0].lower().split("@")[0]
    for cmd, names in COMMANDS.items():
        if w in names: return cmd, (words[1] if len(words) > 1 else None)
    return None, None


def _handle(app, token, chat, cmd, arg):
    from gui_server import gui_server as gs
    client = app.test_client()
    accounts = gs.accounts()
    minutes = float(arg) if arg and arg.replace(".", "", 1).isdigit() else None
    targets = [arg] if arg and arg in accounts else accounts
    if cmd == "help":
        return _send(token, chat, "أوامر Clash Farmer:\n"
                     "• الحالة — كل حساب بيعمل إيه\n• صورة — صورة الشاشة دلوقتي\n• وقف / كمل — إيقاف مؤقت وكمّل (وقف 30 = نص ساعة)\n"
                     "• شغل / اقفل — تشغيل وقفل البوت\n• احصائيات — غنايم النهارده\n• نت — النت وسيرفر اللعبة شغالين؟\n(ممكن تكتب اسم الحساب بعد الأمر)")
    if cmd == "status":
        import stats
        from pathlib import Path
        st = client.get("/api/state").get_json() or {}
        lines = []
        for a in st.get("accounts", []):
            if a.get("id") not in targets: continue
            run = {"paused": "⏸️ متوقف مؤقتًا", "stopped": "⏹️ مقفول"}.get(a.get("status"), "▶️ شغال")
            try: phase = json.loads((Path.home() / ".CoC_Bot" / "phase" / f"{a['id']}.json").read_text()).get("phase", "")
            except Exception: phase = ""
            line = f"{a.get('id')}: {run}" + (f" — {PHASES.get(phase, phase)}" if phase and a.get("running") else "")
            ev = [e for e in stats.read(a["id"], since=time.time() - 6 * 3600) if e.get("type") == "resources"]
            if ev:
                r = ev[-1]
                line += f"\n   دهب {r.get('gold') or 0:,} — إكسير {r.get('elixir') or 0:,} — دارك {r.get('dark') or 0:,}"
            try:                                   # the official API (when set up): levels exactly
                import clash_api
                p = clash_api.summary(clash_api.profile(a["id"]))
                if p and not p.get("error"):
                    line += (f"\n   تاون {p.get('th')} — 🏆 {p.get('trophies')} — الأبطال {p.get('heroes_pct')}%: " +
                             "، ".join(f"{h['name'].split()[-1]} {h['level']}/{h['max']}" for h in p.get("heroes", [])))
            except Exception:
                pass
            lines.append(line)
        return _send(token, chat, "📊 الحالة\n" + ("\n".join(lines) or "مفيش حسابات"))
    if cmd in ("pause", "resume", "start", "stop"):
        done = []
        for acc in targets:
            if cmd == "pause": r = client.post(f"/api/account/{acc}/pause", json={"minutes": minutes or 7 * 24 * 60})
            elif cmd == "resume": r = client.post(f"/api/account/{acc}/pause", json={"minutes": 0})
            else: r = client.post(f"/api/account/{acc}/{cmd}")
            if (r.get_json() or {}).get("ok"): done.append(acc)
        word = {"pause": f"⏸️ اتوقف{' ' + str(int(minutes)) + ' دقيقة' if minutes else ' لحد ما تكتب كمل'}", "resume": "▶️ كمّل",
                "start": "▶️ اشتغل", "stop": "⏹️ اتقفل"}[cmd]
        return _send(token, chat, f"{word}: {', '.join(done) or 'ولا حساب (مش شغال؟)'}")
    if cmd == "screen":
        import settings
        from gui_server import emu_setup
        sent = 0
        for acc in targets[:3]:
            png = emu_setup.screenshot(settings.load_app(), acc)
            if png:
                _api(token, "sendPhoto", http_timeout=60, chat_id=chat, caption=f"📸 {acc}", files={"photo": ("screen.png", png)})
                sent += 1
        if not sent: _send(token, chat, "ما قدرتش أصوّر — المحاكي مقفول؟")
        return
    if cmd == "net":
        import net_check
        pc, game = net_check._pc(), net_check._game()
        return _send(token, chat, "📡 " + ("النت شغال على الجهاز" if pc else "النت مقطوع على الجهاز") + " — " +
                     ("سيرفر اللعبة بيرد ✓" if game else "سيرفر Clash of Clans مش بيرد"))
    if cmd == "stats":
        import stats
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        lines = []
        for acc in targets:
            ev = [e for e in stats.read(acc, since=start) if e.get("type") == "attack"]
            g = sum(e.get("gold", 0) or 0 for e in ev); x = sum(e.get("elixir", 0) or 0 for e in ev)
            d = sum(e.get("dark", 0) or 0 for e in ev)
            lines.append(f"{acc}: {len(ev)} هجمة — دهب {g:,} — إكسير {x:,} — دارك {d:,}")
        return _send(token, chat, "💰 النهارده\n" + ("\n".join(lines) or "مفيش هجمات النهارده"))


def _send(token, chat, text):
    try: _api(token, "sendMessage", http_timeout=15, chat_id=chat, text=text)
    except Exception: pass


def loop(app):
    while True:
        token = _token()
        if not token:
            time.sleep(30)
            continue
        try:
            params = {"timeout": 25, "allowed_updates": json.dumps(["message"])}
            if _STATE["offset"] is not None: params["offset"] = _STATE["offset"]
            res = _api(token, "getUpdates", http_timeout=35, **params)
            for upd in res.get("result", []):
                _STATE["offset"] = upd["update_id"] + 1
                msg = upd.get("message") or {}
                chat = (msg.get("chat") or {}).get("id")
                owner = _owner(token)
                if owner is None and chat:                      # first contact: this chat becomes the owner
                    try:
                        import utils
                        utils.Cache_Manager["telegram_chat_id"] = chat
                    except Exception:
                        pass
                    _STATE["chat"] = owner = chat
                if chat != owner: continue                      # only the owner can control the bot
                cmd, arg = _parse(msg.get("text") or "")
                if cmd:
                    try: _handle(app, token, chat, cmd, arg)
                    except Exception as e: _send(token, chat, f"⚠️ حصلت مشكلة: {type(e).__name__}")
        except Exception:
            time.sleep(10)


def start(app):
    if _STATE["thread"] is not None: return
    t = threading.Thread(target=loop, args=(app,), daemon=True, name="telegram-remote")
    _STATE["thread"] = t
    t.start()
