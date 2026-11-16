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
        "app_sub": "أتمتة كلاش أوف كلانس", "soon": "قريبًا", "search_ph": "ابحث في كل الإعدادات… (Ctrl+K)",
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
    },
    "en": {
        "app_sub": "Clash of Clans automation", "soon": "Soon", "search_ph": "Search every setting… (Ctrl+K)",
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


def translate_log(msg):
    """Arabic text for a log message (English original when no rule matches or English is chosen)."""
    if LANG != "ar": return msg
    for rx, rep in _LOG_RULES:
        m = rx.search(msg)
        if not m: continue
        if rep == "fn:storage":
            kind, value = m.group(1), m.group(2)
            return f"عرف حجم مخزن {'الدهب' if kind == 'gold' else 'الإكسير'}: {int(value):,}"
        if rep == "fn:troopbar":
            names = [n.strip() for n in m.group(1).split(",")]
            return "شريط الجيش: " + "، ".join("؟" if n == "?" else "بطل" if n == "hero" else unit_name(n) for n in names)
        try: return rx.sub(rep, msg, count=1)
        except (re.error, IndexError): return msg
    return msg
