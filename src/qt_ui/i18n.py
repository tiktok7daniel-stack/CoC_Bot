"""
Arabic / English strings. The bulk comes from i18n_data.json (the same texts the bot always used,
emoji-free); the v4 interface adds its own keys in EXTRA. tr() falls back ar -> en -> key.
Log lines are translated with the same regex rules the bot's log viewer used.
"""
import json, re
from pathlib import Path

_DATA = json.loads((Path(__file__).resolve().parent / "i18n_data.json").read_text(encoding="utf-8"))

EXTRA = {
    "ar": {
        "app_sub": "مزرعة كلاش الذكية", "soon": "قريبًا", "search_ph": "ابحث في كل الإعدادات… (Ctrl+K)",
        "search_none": "مفيش نتائج", "unsaved": "فيه تغييرات ما اتحفظتش", "all_saved": "كل التغييرات محفوظة",
        "autosave": "حفظ تلقائي", "start_all": "تشغيل الكل", "stop_all": "إيقاف الكل",
        "uptime": "مدة التشغيل", "ver": "الإصدار", "open_full_log": "فتح السجل الكامل",
        "quick_actions": "أوامر سريعة", "hero_summary": "ملخص الجلسة", "loot_gained": "اللوت المكسوب",
        "per_hour_chart": "اللوت في الساعة", "efficiency": "الكفاءة", "eff_sub": "نسبة الهجمات اللي جابت لوت",
        "live_state": "حالة البوت المباشرة", "minutes_short": "د", "seconds_short": "ث",
        "gauge_cpu": "المعالج", "gauge_ram": "الذاكرة", "splash_loading": "جاري التحميل…",
        "conn_lost": "مش قادر يوصل للبوت — بيحاول تاني", "conn_ok": "متصل",
        "filter_ph": "فلتر…", "level": "المستوى", "add_level": "إضافة مستوى", "drag_hint": "اسحب أي عنصر لمستوى تاني أو رتّبه",
        "add_item_ph": "اكتب اسم واضغط Enter", "remove_level": "حذف المستوى",
        "zoom_in": "تكبير", "zoom_out": "تصغير", "zoom_fit": "ملائمة", "coords": "الإحداثيات",
        "save_selection": "حفظ التحديد", "capture_shot": "التقاط صورة", "no_shot": "مفيش صورة لسه — دوس \"التقاط صورة\" والبوت شغال",
        "learned": "متعلّم", "not_learned": "مش متعلّم", "forget": "انسى", "draw_hint": "ارسم مربع على العنصر في الصورة، وبعدين دوس \"حفظ التحديد\"",
        "all_levels": "كل المستويات", "lv_info": "معلومات", "lv_warn": "تحذير", "lv_err": "خطأ", "raw": "النص الأصلي",
        "copy": "نسخ", "clear_view": "مسح العرض", "copied": "اتنسخ", "errors_n": "أخطاء", "warnings_n": "تحذيرات",
        "check_now": "افحص دلوقتي", "checking": "بيفحص…", "test_ping": "تجربة", "verify": "تحقق",
        "frameless_min": "تصغير", "frameless_max": "تكبير", "frameless_close": "إغلاق",
        "acc_settings": "الإعدادات", "acc_delete": "حذف", "acc_runtime": "شغال من",
        "time_from": "من", "time_to": "إلى", "days": "الأيام",
        "army_search_ph": "ابحث عن وحش أو تعويذة…", "selected": "متختار",
        "ready_title": "تجهيز البوت", "close": "إغلاق",
        "kpi_attacks": "هجمات", "kpi_searches": "عمليات بحث", "kpi_skipped": "قرى اتخطت", "kpi_upgrades": "ترقيات",
        "kpi_walls": "جدران", "kpi_cycles": "دورات", "kpi_avg": "متوسط الدورة",
        "total": "الإجمالي", "per_attack": "لكل هجمة", "per_hour": "في الساعة", "highest": "أعلى", "lowest": "أقل",
        "refresh_now": "تحديث", "reset": "تصفير", "time": "الوقت", "base": "القرية", "type": "النوع", "name": "الاسم",
        "home_v": "رئيسية", "builder_v": "ليلية", "rec_delete_q": "تمسح التسجيل ده؟",
        "plan_n": "التشكيلة", "use_it": "استخدمها", "active": "شغالة", "send_report": "رفع الأخطاء على GitHub",
        "save_report": "حفظ تقرير للمطور", "open_shots": "فتح فولدر الصور", "no_errors": "مفيش أخطاء",
        "update_check": "التحقق من التحديثات", "update_now": "تحديث الآن", "latest": "آخر إصدار", "current": "الإصدار الحالي",
        "tess_found": "Tesseract موجود", "tess_missing": "Tesseract مش موجود", "install": "تثبيت",
        "easyocr_fallback": "EasyOCR شغال كبديل لو Tesseract مش موجود", "privacy": "قبل الرفع البوت بيشيل الأسماء والمسارات من الرسائل",
        "account_n": "حساب", "no_recordings": "مفيش تسجيلات لسه",
        "sync_title": "نفس اللعب على كل الحسابات", "sync_sub": "خلّي كل الحسابات تلعب وتطوّر بنفس الطريقة بالظبط",
        "sync_on": "نفس الإعدادات لكل الحسابات", "sync_on_sub": "أي تغيير تعمله في حساب بيتطبق على كل الحسابات على طول",
        "copy_to_all_lbl": "انسخ إعدادات الحساب المفتوح دلوقتي لكل الحسابات التانية", "copy_to_all": "انسخ لكل الحسابات",
        "sync_note": "كل حساب بيختار جيشه وتسجيله لوحده: افتح الحساب من فوق، وسجّل له معركة بجيشه، واختار التشكيلة أو التسجيل بتاعه — ده مش بيتنسخ على الحسابات التانية. كل حاجة غير كده (الترقيات، الأسوار، الجدول…) بتبقى واحدة. وكل حساب لازم يبقى له نسخة محاكي لوحده (LDMultiPlayer ← نسخة جديدة) مربوطة بيه من شاشة تجهيز البوت.",
        "copy_from": "إعداداته زي", "copy_none": "إعدادات جديدة", "copied_from": "اتضاف الحساب بنفس إعدادات {a}",
        "copy_no_other": "مفيش حسابات تانية — ضيف حساب الأول", "copy_confirm": "هتتنسخ إعدادات {a} على {n} حساب تاني. موافق؟",
        "copy_done": "اتنسخت الإعدادات على {n} حساب",
        "never_close": "البوت ما يقفلش اللعبة أبدًا",
        "never_close_sub": "اللعبة والمحاكي بيفضلوا مفتوحين دايمًا — حتى في الاستراحات ولما المخازن تتملي ولما تقفل البوت. بتتقفل بس لما إنت تقفلها",
        "farm_max_walls": "تمكيس الأسوار",
        "farm_max_walls_sub": "يفضل يهاجم ويطوّر الأسوار كل ما المخازن تتملي لحد ما كل الأسوار توصل للماكس — وبيطوّر كل المباني الناقصة كمان، بس بيسيب بنّاء واحد فاضي دايمًا للأسوار",
        "walls_maxed_banner": "كل الأسوار وصلت للماكس",
        "upd_sub": "تحديث البرنامج لآخر إصدار", "discard": "تراجع عن التغييرات", "up": "لفوق", "down": "لتحت", "add": "إضافة",
        "emu_ld": "LDPlayer", "emu_bs": "BlueStacks", "emu_mumu": "MuMu Player", "lang_ar": "العربية", "lang_en": "English",
        "recent_attacks": "آخر الهجمات", "session_results_sub": "نتايج الجلسة الحالية من أول ما البوت اشتغل",
        "strategies": "اللي البوت اتعلمه", "strategies_sub": "متوسط اللوت لكل طريقة إنزال",
        "tg_need_token": "اكتب توكن بوت تيليجرام الأول", "ui_kind": "شكل البرنامج", "ui_kind_sub": "الواجهة الجديدة أو القديمة (بيتطبق لما تفتح البرنامج تاني)",
        "ui_qt": "الواجهة الجديدة (v4)", "ui_web": "الواجهة القديمة", "up_building": "مبنى", "up_wall": "سور", "up_lab": "مختبر",
        "up_pet": "حيوان", "session_since": "الجلسة من", "no_attacks": "مفيش هجمات لسه",
        "ra_live_vision": "رؤية YOLO المباشرة", "ra_live_detections": "وحدات مرصودة",
        "rl_vision": "مصدر الرؤية", "rl_source_large": "YOLO متزامن",
        "ra_snapshot": "لقطة من البوت · البث متوقف",
        "rl_source_fast": "YOLO سريع متزامن", "rl_source_fallback": "الكاشف الاحتياطي الحالي",
        "rl_source_unknown": "غير معروف", "rl_units": "وحدة", "rl_tracks": "مسار",
        "rl_vision_ms": "زمن الرؤية",
        "ra_live_no_units": "الموديل جاهز لكن مفيش وحدات مرصودة حالياً.",
        "ra_live_loading": "جاري تجهيز موديل الكشف…", "ra_live_error": "حصل خطأ في الكشف المحلي",
        "ra_live_waiting": "في انتظار صورة من بث اللعبة…",
        "ra_live_bot_note": "قرارات الكروت ومكان اللعب تظهر لما يكون بوت المعركة شغال.",
        "ra_picture_sub": "المربعات: أحمر = الخصم، أزرق = بتاعنا، أصفر = كشف YOLO مباشر ولسه الجهة مش مؤكدة · الشريط = الحياة · النقط: الحركات اللي المحرك جربها · الدواير البيضا: اختيارات الموديل · السهم الدهبي: من الكارت للمكان اللي اتلعب فيه",
    },
    "en": {
        "app_sub": "Smart Clash farming", "soon": "Soon", "search_ph": "Search every setting… (Ctrl+K)",
        "search_none": "No results", "unsaved": "Unsaved changes", "all_saved": "All changes saved",
        "autosave": "Auto-save", "start_all": "Start all", "stop_all": "Stop all",
        "uptime": "Uptime", "ver": "Version", "open_full_log": "Open full log",
        "quick_actions": "Quick actions", "hero_summary": "Session summary", "loot_gained": "Loot gained",
        "per_hour_chart": "Loot per hour", "efficiency": "Efficiency", "eff_sub": "Share of attacks that brought loot",
        "live_state": "Live bot state", "minutes_short": "m", "seconds_short": "s",
        "gauge_cpu": "CPU", "gauge_ram": "RAM", "splash_loading": "Loading…",
        "conn_lost": "Can't reach the bot — retrying", "conn_ok": "Connected",
        "filter_ph": "Filter…", "level": "Level", "add_level": "Add level", "drag_hint": "Drag items between levels to reorder",
        "add_item_ph": "Type a name and press Enter", "remove_level": "Remove level",
        "zoom_in": "Zoom in", "zoom_out": "Zoom out", "zoom_fit": "Fit", "coords": "Coordinates",
        "save_selection": "Save selection", "capture_shot": "Capture screenshot", "no_shot": "No screenshot yet — press \"Capture\" while the bot runs",
        "learned": "Learned", "not_learned": "Not learned", "forget": "Forget", "draw_hint": "Draw a box over the element, then press \"Save selection\"",
        "all_levels": "All levels", "lv_info": "Info", "lv_warn": "Warning", "lv_err": "Error", "raw": "Raw text",
        "copy": "Copy", "clear_view": "Clear view", "copied": "Copied", "errors_n": "Errors", "warnings_n": "Warnings",
        "check_now": "Check now", "checking": "Checking…", "test_ping": "Test", "verify": "Verify",
        "frameless_min": "Minimize", "frameless_max": "Maximize", "frameless_close": "Close",
        "acc_settings": "Settings", "acc_delete": "Delete", "acc_runtime": "Running for",
        "time_from": "From", "time_to": "To", "days": "Days",
        "army_search_ph": "Search a troop or spell…", "selected": "Selected",
        "ready_title": "Bot setup", "close": "Close",
        "kpi_attacks": "Attacks", "kpi_searches": "Searches", "kpi_skipped": "Skipped", "kpi_upgrades": "Upgrades",
        "kpi_walls": "Walls", "kpi_cycles": "Cycles", "kpi_avg": "Avg cycle",
        "total": "Total", "per_attack": "Per attack", "per_hour": "Per hour", "highest": "Highest", "lowest": "Lowest",
        "refresh_now": "Refresh", "reset": "Reset", "time": "Time", "base": "Village", "type": "Type", "name": "Name",
        "home_v": "Home", "builder_v": "Builder", "rec_delete_q": "Delete this recording?",
        "plan_n": "Loadout", "use_it": "Use", "active": "Active", "send_report": "Upload errors to GitHub",
        "save_report": "Save report for the developer", "open_shots": "Open screenshots folder", "no_errors": "No errors",
        "update_check": "Check for updates", "update_now": "Update now", "latest": "Latest", "current": "Current",
        "tess_found": "Tesseract found", "tess_missing": "Tesseract missing", "install": "Install",
        "easyocr_fallback": "EasyOCR is used when Tesseract is missing", "privacy": "Names and paths are removed before upload",
        "account_n": "Account", "no_recordings": "No recordings yet",
        "sync_title": "Same play on every account", "sync_sub": "Make every account play and upgrade exactly the same way",
        "sync_on": "Same settings for all accounts", "sync_on_sub": "Any change on one account applies to every account",
        "copy_to_all_lbl": "Copy the open account's settings to all other accounts", "copy_to_all": "Copy to all",
        "sync_note": "Each account picks its own army and recording (open the account at the top, record a battle with its army, choose its loadout) - that is never copied. Everything else (upgrades, walls, schedule…) stays the same. Each account needs its own emulator copy, linked on the setup screen.",
        "copy_from": "Settings like", "copy_none": "New settings", "copied_from": "Account added with the settings of {a}",
        "copy_no_other": "No other accounts — add one first", "copy_confirm": "Copy the settings of {a} to {n} other account(s)?",
        "copy_done": "Settings copied to {n} account(s)",
        "never_close": "Never close the game",
        "never_close_sub": "The game and the emulator always stay open - during breaks, when storages are full and when the bot stops. Only you close them",
        "farm_max_walls": "Max all walls",
        "farm_max_walls_sub": "Keep farming and upgrade walls every time the storages are full until every wall is maxed; buildings are upgraded too, always keeping one builder free for walls",
        "walls_maxed_banner": "Every wall is maxed",
        "upd_sub": "Get the latest version", "discard": "Discard changes", "up": "Up", "down": "Down", "add": "Add",
        "emu_ld": "LDPlayer", "emu_bs": "BlueStacks", "emu_mumu": "MuMu Player", "lang_ar": "العربية", "lang_en": "English",
        "recent_attacks": "Recent attacks", "session_results_sub": "Results of the current session",
        "strategies": "What the bot learned", "strategies_sub": "Average loot per deployment strategy",
        "tg_need_token": "Enter the Telegram bot token first", "ui_kind": "Interface", "ui_kind_sub": "New or classic window (applies on next start)",
        "ui_qt": "New interface (v4)", "ui_web": "Classic interface", "up_building": "Building", "up_wall": "Wall", "up_lab": "Lab",
        "up_pet": "Pet", "session_since": "Session since", "no_attacks": "No attacks yet",
        "ra_live_vision": "Live YOLO vision", "ra_live_detections": "units detected",
        "rl_vision": "Vision source", "rl_source_large": "YOLO, current frame",
        "ra_snapshot": "Bot snapshot · live video paused",
        "rl_source_fast": "Fast YOLO, current frame", "rl_source_fallback": "Current-frame fallback",
        "rl_source_unknown": "Unknown", "rl_units": "units", "rl_tracks": "tracks",
        "rl_vision_ms": "vision time",
        "ra_live_no_units": "The model is ready but has no unit detections right now.",
        "ra_live_loading": "Loading the detection model…", "ra_live_error": "Local detection failed",
        "ra_live_waiting": "Waiting for a game video frame…",
        "ra_live_bot_note": "Card choices and placements appear while the battle bot loop is running.",
        "ra_picture_sub": "Boxes: red = theirs, blue = ours, yellow = live YOLO with ownership not yet known · bar = life · dots: engine candidate moves · white rings: model choices · gold arrow: the played card and placement",
    },
}

LANG = "ar"
_listeners = []
_LOG_RULES = [(re.compile(src), rep) for src, rep in _DATA["log"]]


def set_lang(lang):
    global LANG
    LANG = "en" if lang == "en" else "ar"
    for fn in list(_listeners):
        try: fn()
        except RuntimeError: _listeners.remove(fn) # widget already deleted


def on_lang(fn):
    """Call fn whenever the language changes (widgets re-apply their texts)."""
    _listeners.append(fn)
    return fn


def is_rtl():
    return LANG == "ar"


def tr(key):
    for table in (EXTRA.get(LANG, {}), _DATA.get(LANG, {}), EXTRA["en"], _DATA["en"]):
        if key in table: return table[key]
    return key


def unit_name(name):
    if LANG == "ar" and name in _DATA["unit_ar"]: return _DATA["unit_ar"][name]
    return name.replace("_", " ")


_WHY = [("the video library (av) is not installed", "مكتبة الفيديو (av) مش متسطّبة — حدّث البرنامج"),
        ("the emulator did not start the stream", "المحاكي ما شغّلش البث"),
        ("the emulator sent no picture", "المحاكي ما بعتش صورة"),
        ("the stream shows something else than the game", "البث بيوري حاجة غير اللعبة"),
        ("the stream server file is missing", "ملف سيرفر البث ناقص — البوت بينزّله لوحده"),
        ("LDPlayer window not found", "مش لاقي نافذة LDPlayer"),
        ("LDPlayer window is minimized", "نافذة LDPlayer متصغّرة — مش مشكلة، الشاشة اللايف بتشتغل وهي متصغّرة"),
        ("pw3", "النافذة"), ("pw2", "النافذة كاملة"), ("screen", "الشاشة"),
        (": nothing", ": مفيش صورة"), (": black", ": صورة سودة"), ("different", "مختلفة عن اللعبة")]


def why_ar(text):
    """A capture problem (English, from the bot) in plain Egyptian Arabic."""
    if LANG != "ar" or not text: return text
    for en, ar in _WHY: text = text.replace(en, ar)
    return text


def translate_log(msg):
    """Arabic text for a log message (English original when no rule matches or English is chosen)."""
    if LANG != "ar": return msg
    for rx, rep in _LOG_RULES:
        m = rx.search(msg)
        if not m: continue
        if rep == "fn:storage":
            kind, value = m.group(1), m.group(2)
            return f"عرف حجم مخزن {'الدهب' if kind == 'gold' else 'الإكسير'}: {int(value):,}"
        if rep == "fn:round":
            jobs = {"attack & farm": "هجوم وفارم", "buildings": "ترقية المباني", "walls": "الأسوار", "lab": "المعمل",
                    "heroes & pets": "الأبطال والحيوانات", "builder base": "القرية الليلية"}
            parts = [jobs.get(j.strip(), j.strip()) for j in m.group(2).split(",")]
            return f"▶ الجولة {m.group(1)}: هيعمل " + " ← ".join(parts)
        if rep == "fn:capture_live":
            return f"الشاشة اللايف مش متاحة ({why_ar(m.group(1))}) — بيجرّب التصوير من النافذة"
        if rep == "fn:capture_window":
            return f"التصوير من نافذة LDPlayer مش متاح ({why_ar(m.group(1))}) — شغال بالطريقة العادية"
        if rep == "fn:troopbar":
            names = [n.strip() for n in m.group(1).split(",")]
            return "شريط الجيش: " + "، ".join("؟" if n == "?" else "بطل" if n == "hero" else unit_name(n) for n in names)
        if rep in ("fn:spellcard", "fn:spellcast"):
            ar = {"lightning": "البرق", "earthquake": "الزلزال", "freeze": "التجميد", "invisibility": "الإخفاء",
                  "poison": "السم", "rage": "الغضب", "haste": "السرعة", "healing": "العلاج", "recall": "الاستدعاء",
                  "totem": "التوتم", "overgrowth": "النمو", "jump": "القفز", "clone": "الاستنساخ", "skeleton": "الهياكل",
                  "bat": "الخفافيش", "revive": "الإحياء", "ice_block": "الجليد", "fury": "الهياج"}
            where = {"air_defense": "على دفاعات الجو اللي قريبة", "cluster": "على الدفاعات المتجمعة في الطريق",
                     "strong": "على أقوى دفاع قدام الجيش", "clan": "على كلان كاسل العدو", "front": "قدام الجيش"}
            if rep == "fn:spellcard": return f"🪄 عرف كارت السبيل: {ar.get(m.group(1), m.group(1))}"
            return f"🪄 رمى {ar.get(m.group(1), m.group(1))} ×{m.group(2)} {where.get(m.group(3), '')}"
        if rep == "fn:netcheck":
            t = m.group(1)
            v = {"pc_offline": "النت مقطوع على الجهاز", "emulator_offline": "LDPlayer مش واصل للنت",
                 "game_server": "سيرفر اللعبة مش بيرد", "ok": "النت شغال — المشكلة من اللعبة نفسها"}
            verdict = next((ar for k, ar in v.items() if f"({k})" in t), "")
            return ("📡 فحص النت: الجهاز " + ("✓" if "PC ok" in t else "✗") + "، LDPlayer " +
                    ("✓" if "LDPlayer ok" in t else ("✗" if "LDPlayer OFFLINE" in t else "؟")) + "، سيرفر اللعبة " +
                    ("✓" if "server ok" in t else "✗") + (f" — {verdict}" if verdict else ""))
        if rep == "fn:missed":
            kinds = m.group(2).strip(" ()")
            for en, ar in (("troop", "وحش"), ("hero", "بطل"), ("clan", "كلان كاسل"), ("None", "مش معروف")): kinds = kinds.replace(en, ar)
            return f"⚠️ {m.group(1)} كارت ما نزلش في أي مكان" + (f" ({kinds})" if kinds else "")
        if rep == "fn:btiming":
            t = m.group(1)
            for en, ar in (("waiting for the base", "انتظار القرية"), ("clouds", "السحاب"), ("zoom", "الزووم"),
                           ("eyes", "العيون"), ("red line", "الخط الأحمر"), ("recording ready", "تجهيز التسجيل"),
                           ("pictures:", "التصوير:"), ("stream", "لايف"), ("window", "النافذة"), ("adb", "ADB")):
                t = t.replace(en, ar)
            return "⏱️ وقت بداية الهجمة: " + t.replace("s,", " ث،").replace("s ", " ث ")
        if rep == "fn:smart":
            sides = {"bottom-left": "اللي تحت شمال", "bottom-right": "اللي تحت يمين", "top-left": "اللي فوق شمال",
                     "top-right": "اللي فوق يمين", "left": "الشمال", "right": "اليمين", "bottom": "اللي تحت"}
            return (f"🧠 هجوم ذكي: اختار الجهة {sides.get(m.group(1), m.group(1))} (أضعف جهة — خطورتها {m.group(2)}) "
                    f"— {m.group(3)} أماكن إنزال على العشب")
        if rep.startswith("res:"):            # the resource names in Arabic too
            try: out = rx.sub(rep[4:], msg, count=1)
            except (re.error, IndexError): return msg
            for en, ar in ((" elixir", " إكسير"), (" gold", " دهب"), (" dark", " دارك")): out = out.replace(en, ar)
            return out
        try: return rx.sub(rep, msg, count=1)
        except (re.error, IndexError): return msg
    return msg
