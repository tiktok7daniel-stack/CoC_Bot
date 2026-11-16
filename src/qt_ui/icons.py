"""
Hand-drawn SVG line icons (24x24 grid, 1.75 stroke, round caps/joins) and the CoC Bot crest.
icon(name, color) -> QIcon, pixmap(name, size, color) -> QPixmap. "currentColor" is replaced by the
requested color, so one drawing serves every state. No emoji anywhere in the UI: these are the icons.
"""
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">'

# path bodies (inside the <svg>)
PATHS = {
    # navigation
    "home": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5"/>',
    "trophy": '<path d="M8 21h8M12 17v4M7 4h10v5a5 5 0 0 1-10 0z"/><path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4"/>',
    "users": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/>',
    "swords": '<path d="M14.5 17.5 3 6V3h3l11.5 11.5"/><path d="m13 19 6-6M16 16l4 4M19 21l2-2"/><path d="M9.5 6.5 14 2h3v3l-4.5 4.5"/><path d="M5 14l-2 2 4 4 2-2"/>',
    "moon": '<path d="M20.5 14.5A8.5 8.5 0 1 1 9.5 3.5a7 7 0 0 0 11 11z"/>',
    "chart": '<path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="6" rx="1"/><rect x="12" y="8" width="3" height="10" rx="1"/><rect x="17" y="4" width="3" height="14" rx="1"/>',
    "castle": '<path d="M3 21V9l3-2v3h3V7l3-2 3 2v3h3V7l3 2v12z"/><path d="M10 21v-5a2 2 0 0 1 4 0v5"/>',
    "hammer": '<path d="m15 12-8.4 8.4a2 2 0 0 1-2.8-2.8L12.2 9.2"/><path d="m17.6 4.4 2 2a2 2 0 0 1 0 2.8L17 11.8 12.2 7l2.6-2.6a2 2 0 0 1 2.8 0z"/>',
    "scroll": '<path d="M8 21h11a2 2 0 0 0 2-2v-1H10v1a2 2 0 0 1-4 0V5a2 2 0 0 0-2-2h12a2 2 0 0 1 2 2v13"/><path d="M10 8h5M10 12h5"/>',
    "bot": '<rect x="4" y="8" width="16" height="12" rx="3"/><path d="M12 4v4M9 13v1M15 13v1M9.5 17h5"/><circle cx="12" cy="3.5" r="1"/><path d="M2 13v2M22 13v2"/>',
    "crown": '<path d="M3 8l4 4 5-7 5 7 4-4-2 11H5z"/>',
    "shield": '<path d="M12 21s8-3.5 8-10V5l-8-2-8 2v6c0 6.5 8 10 8 10z"/>',
    "chat": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.8A8 8 0 1 1 21 12z"/><path d="M8.5 12h.01M12 12h.01M15.5 12h.01"/>',
    "school": '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2.5 9 2.5 12 0v-5M22 9v6"/>',
    # actions
    "play": '<path d="M7 4.5v15l12-7.5z"/>',
    "stop": '<rect x="5.5" y="5.5" width="13" height="13" rx="2"/>',
    "pause": '<rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/>',
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>',
    "plug": '<path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5"/>',
    "save": '<path d="M5 3h11l4 4v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 1-2z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
    "refresh": '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "check": '<path d="M4.5 12.5l5 5 10-11"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3"/>',
    "edit": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "download": '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    "cloud": '<path d="M7 18a5 5 0 0 1-.6-10A6 6 0 0 1 18 8.5a4.5 4.5 0 0 1-.5 9.5z"/><path d="M12 11v6M9.5 14.5 12 17l2.5-2.5"/>',
    "wand": '<path d="m15 4 5 5L8 21l-5-5z"/><path d="M13 6l5 5M5 3v3M3.5 4.5h3M19 15v3M17.5 16.5h3"/>',
    "camera": '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13.5" r="3.5"/>',
    "video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3"/>',
    "record": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4" fill="currentColor"/>',
    "film": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M7 3v18M17 3v18M3 8h4M3 12h18M3 16h4M17 8h4M17 16h4"/>',
    "power": '<path d="M12 3v8"/><path d="M6.3 6.7a8 8 0 1 0 11.4 0"/>',
    "gamepad": '<rect x="2.5" y="7" width="19" height="11" rx="5"/><path d="M7 10.5v4M5 12.5h4M15.5 11.5h.01M18 13.5h.01"/>',
    "expand": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "zoomin": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5M11 8v6M8 11h6"/>',
    "zoomout": '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5M8 11h6"/>',
    "crosshair": '<circle cx="12" cy="12" r="8"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    "send": '<path d="M21 3 3 10.5l7 3 3 7z"/><path d="m21 3-11 10.5"/>',
    "link": '<path d="M9.5 14.5 14.5 9.5"/><path d="M11 6.5 13 4.5a4 4 0 0 1 5.5 5.5l-2 2M13 17.5l-2 2A4 4 0 0 1 5.5 14l2-2"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "drag": '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
    "chevron_left": '<path d="m15 18-6-6 6-6"/>',
    "chevron_right": '<path d="m9 18 6-6-6-6"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "win_min": '<path d="M5 12h14"/>',
    "win_max": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "win_restore": '<rect x="5" y="8" width="11" height="11" rx="2"/><path d="M8 8V6a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-2"/>',
    # status
    "ok": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 3 3 5-6"/>',
    "bad": '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "warn": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "dash_circle": '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "hourglass": '<path d="M6 3h12M6 21h12M7 3v4a5 5 0 0 0 10 0V3M7 21v-4a5 5 0 0 1 10 0v4"/>',
    "pulse": '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "memory": '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 11v2M11 11v2M15 11v2M6 17v3M10 17v3M14 17v3M18 17v3"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "usb": '<path d="M12 3v14"/><circle cx="12" cy="19" r="2"/><path d="m9 6 3-3 3 3M7 10v2l5 3M17 9v3l-5 3"/><rect x="15.5" y="7" width="3" height="2"/><circle cx="7" cy="9" r="1"/>',
    "stethoscope": '<path d="M5 3v6a4 4 0 0 0 8 0V3"/><path d="M9 13v2a5 5 0 0 0 10 0v-2"/><circle cx="19" cy="11" r="2"/>',
    "bug": '<rect x="7" y="8" width="10" height="12" rx="5"/><path d="M12 8V20M9 5l1.5 2M15 5l-1.5 2M3 12h4M17 12h4M4 18l3-2M20 18l-3-2M4 7l3 2M20 7l-3 2"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M17 6l3 3M14 9l2 2"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "github": '<path d="M9 19c-4.5 1.4-4.5-2.5-6.5-3M15 21v-3.5a3 3 0 0 0-.9-2.4c3-.3 6.1-1.5 6.1-6.6a5.2 5.2 0 0 0-1.4-3.6 4.8 4.8 0 0 0-.1-3.6s-1.1-.3-3.7 1.4a12.6 12.6 0 0 0-6.6 0C5.8 1 4.7 1.4 4.7 1.4a4.8 4.8 0 0 0-.1 3.6A5.2 5.2 0 0 0 3.2 8.5c0 5.1 3.1 6.3 6.1 6.6a3 3 0 0 0-.9 2.4V21"/>',
    "text": '<path d="M4 7V5h16v2M12 5v14M9 19h6"/>',
    "sliders": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "list": '<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "flag": '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    "box": '<path d="M3 7.5 12 3l9 4.5v9L12 21l-9-4.5z"/><path d="m3 7.5 9 4.5 9-4.5M12 12v9"/>',
    "flask": '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21h11.6a2 2 0 0 0 1.7-2.5L14 9V3"/><path d="M7.5 15h9"/>',
    "paw": '<circle cx="7" cy="9" r="1.8"/><circle cx="12" cy="6.5" r="1.8"/><circle cx="17" cy="9" r="1.8"/><path d="M12 12c-3 0-6 4-5 6.5 1 2 3 1 5 1s4 1 5-1c1-2.5-2-6.5-5-6.5z"/>',
    "wall": '<path d="M3 7h18v12H3z"/><path d="M3 11h18M3 15h18M8 7v4M14 7v4M11 11v4M17 11v4M6 15v4M13 15v4"/>',
    "brick": '<rect x="3" y="7" width="18" height="10" rx="1"/><path d="M3 12h18M10 7v5M15 12v5"/>',
    "army": '<circle cx="8" cy="7" r="3"/><circle cx="16" cy="7" r="3"/><path d="M2.5 20a5.5 5.5 0 0 1 11 0M10.5 20a5.5 5.5 0 0 1 11 0"/>',
    "map_pin": '<path d="M12 21s7-6 7-12a7 7 0 0 0-14 0c0 6 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="9.5" r="2"/><path d="m21 16-5-5-9 9"/>',
    "lang": '<path d="M4 5h8M8 3v2M5.5 5c1 4 4 7 7 8M10.5 5c-1 4-3.5 7-6.5 9"/><path d="m13 21 4-10 4 10M14.5 17.5h5"/>',
    "palette": '<path d="M12 3a9 9 0 0 0 0 18c1 0 1.5-.8 1.5-1.5 0-1.2-1-1.5-1-2.5 0-.8.7-1.5 1.5-1.5H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="7.5" r="1"/>',
    "sparkle": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    "spin": '<path d="M12 3a9 9 0 1 0 9 9"/>',
    "dot": '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M12 15h5"/>',
    "id": '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M6 16a3 3 0 0 1 6 0M14 10h4M14 13h3"/>',
    "lightbulb": '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
}

# filled resource / game glyphs (own colors, not tinted)
GLYPHS = {
    # premium check seals: green = done / ok, gold = learned (taught by Claude)
    "verified": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7CF5B8"/><stop offset=".55" stop-color="#2FCB7E"/><stop offset="1" stop-color="#178F55"/></linearGradient><linearGradient id="h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".55"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient></defs><path d="M16.00 3.40Q20.01 1.05 22.30 5.09Q26.94 5.06 26.91 9.70Q30.95 11.99 28.60 16.00Q30.95 20.01 26.91 22.30Q26.94 26.94 22.30 26.91Q20.01 30.95 16.00 28.60Q11.99 30.95 9.70 26.91Q5.06 26.94 5.09 22.30Q1.05 20.01 3.40 16.00Q1.05 11.99 5.09 9.70Q5.06 5.06 9.70 5.09Q11.99 1.05 16.00 3.40Z" fill="#0B5A34" transform="translate(0 .9)"/><path d="M16.00 3.40Q20.01 1.05 22.30 5.09Q26.94 5.06 26.91 9.70Q30.95 11.99 28.60 16.00Q30.95 20.01 26.91 22.30Q26.94 26.94 22.30 26.91Q20.01 30.95 16.00 28.60Q11.99 30.95 9.70 26.91Q5.06 26.94 5.09 22.30Q1.05 20.01 3.40 16.00Q1.05 11.99 5.09 9.70Q5.06 5.06 9.70 5.09Q11.99 1.05 16.00 3.40Z" fill="url(#b)" stroke="#0B5A34" stroke-width=".9" stroke-linejoin="round"/><circle cx="16" cy="16" r="9.6" fill="none" stroke="#D9FFEC" stroke-opacity=".55" stroke-width=".9"/><path d="M7.2 12.2A9.6 9.6 0 0 1 24.8 12.2" fill="none" stroke="url(#h)" stroke-width="3.2" stroke-linecap="round"/><path d="M10.6 16.6l3.6 3.6 7.4-7.8" fill="none" stroke="#0B5A34" stroke-opacity=".55" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" transform="translate(0 .8)"/><path d="M10.6 16.6l3.6 3.6 7.4-7.8" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "verified_gold": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><linearGradient id="b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFE89A"/><stop offset=".55" stop-color="#F5B740"/><stop offset="1" stop-color="#C47F12"/></linearGradient><linearGradient id="h" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".55"/><stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient></defs><path d="M16.00 3.40Q20.01 1.05 22.30 5.09Q26.94 5.06 26.91 9.70Q30.95 11.99 28.60 16.00Q30.95 20.01 26.91 22.30Q26.94 26.94 22.30 26.91Q20.01 30.95 16.00 28.60Q11.99 30.95 9.70 26.91Q5.06 26.94 5.09 22.30Q1.05 20.01 3.40 16.00Q1.05 11.99 5.09 9.70Q5.06 5.06 9.70 5.09Q11.99 1.05 16.00 3.40Z" fill="#6E4405" transform="translate(0 .9)"/><path d="M16.00 3.40Q20.01 1.05 22.30 5.09Q26.94 5.06 26.91 9.70Q30.95 11.99 28.60 16.00Q30.95 20.01 26.91 22.30Q26.94 26.94 22.30 26.91Q20.01 30.95 16.00 28.60Q11.99 30.95 9.70 26.91Q5.06 26.94 5.09 22.30Q1.05 20.01 3.40 16.00Q1.05 11.99 5.09 9.70Q5.06 5.06 9.70 5.09Q11.99 1.05 16.00 3.40Z" fill="url(#b)" stroke="#6E4405" stroke-width=".9" stroke-linejoin="round"/><circle cx="16" cy="16" r="9.6" fill="none" stroke="#FFF6D6" stroke-opacity=".55" stroke-width=".9"/><path d="M7.2 12.2A9.6 9.6 0 0 1 24.8 12.2" fill="none" stroke="url(#h)" stroke-width="3.2" stroke-linecap="round"/><path d="M10.6 16.6l3.6 3.6 7.4-7.8" fill="none" stroke="#6E4405" stroke-opacity=".55" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round" transform="translate(0 .8)"/><path d="M10.6 16.6l3.6 3.6 7.4-7.8" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "gold": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><radialGradient id="g" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#FFF6C2"/><stop offset=".45" stop-color="#FBBF24"/><stop offset="1" stop-color="#B7791F"/></radialGradient></defs><circle cx="16" cy="16" r="13" fill="url(#g)" stroke="#92600E" stroke-width="1.5"/><circle cx="16" cy="16" r="8.5" fill="none" stroke="#B7791F" stroke-width="1.5" opacity=".75"/><path d="M12 13.5h8M12 18.5h8" stroke="#FFF6C2" stroke-width="1.2" stroke-linecap="round" opacity=".6"/></svg>',
    "elixir": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><radialGradient id="e" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#FFD9F0"/><stop offset=".5" stop-color="#EC4899"/><stop offset="1" stop-color="#9D174D"/></radialGradient></defs><path d="M16 3S6 15 6 20.5a10 10 0 0 0 20 0C26 15 16 3 16 3z" fill="url(#e)" stroke="#831843" stroke-width="1.5"/><ellipse cx="12" cy="18" rx="2.4" ry="4" fill="#fff" opacity=".45"/></svg>',
    "dark": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><defs><radialGradient id="d" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#C7D2FE"/><stop offset=".5" stop-color="#6366F1"/><stop offset="1" stop-color="#1E1B4B"/></radialGradient></defs><path d="M12 3h8M13 3v6.5L7.5 19A7 7 0 0 0 13.6 29h4.8A7 7 0 0 0 24.5 19L19 9.5V3" fill="url(#d)" stroke="#1E1B4B" stroke-width="1.5" stroke-linejoin="round"/><ellipse cx="13" cy="21" rx="2" ry="3.4" fill="#fff" opacity=".35"/></svg>',
    "trophy_shield": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M16 29s11-4.5 11-13.5V7L16 3 5 7v8.5C5 24.5 16 29 16 29z" fill="#3B2A63" stroke="#A855F7" stroke-width="1.5"/><path d="M11 10h10v4a5 5 0 0 1-10 0z" fill="#FBBF24"/><path d="M14 22h4M16 19v3" stroke="#FBBF24" stroke-width="1.5" stroke-linecap="round"/></svg>',
    "builder_hammer": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M19 15 8 26a2.8 2.8 0 0 1-4-4l11-11" fill="none" stroke="#B7791F" stroke-width="3" stroke-linecap="round"/><path d="M23 5l4 4-5 5-4-4-2 2-2-2 5-5z" fill="#94A3B8" stroke="#334155" stroke-width="1.2" stroke-linejoin="round"/></svg>',
}

# the Clash Farmer crest lives in logo.py (brand assets in one place)
from .logo import CREST  # noqa: E402


def svg_markup(name, color="#EDEAF7"):
    if name == "crest": return CREST
    if name in GLYPHS: return GLYPHS[name]
    body = PATHS.get(name, PATHS["dot"])
    return (_HEAD + body + "</svg>").replace("currentColor", color)


@lru_cache(maxsize=2048)
def pixmap(name, size=20, color="#EDEAF7", dpr=2.0):
    """Crisp icon pixmap (rendered at device pixel ratio dpr)."""
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode("utf-8")))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name, color="#EDEAF7", size=20):
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color), QIcon.Normal)
    ic.addPixmap(pixmap(name, size, "#6F6885"), QIcon.Disabled)
    return ic


def render_to_file(name, path, size):
    """Used by generate_ico.py to write PNG frames of the crest."""
    pm = pixmap(name, size, dpr=1.0)
    pm.save(str(path), "PNG")


_IMG_DIR = None


def img_tag(name, size=16, color="#EDEAF7"):
    """<img> for rich-text labels (the check seals inline with text): rendered once to a cached PNG."""
    global _IMG_DIR
    import os, tempfile
    if _IMG_DIR is None:
        _IMG_DIR = os.path.join(tempfile.gettempdir(), "clash_farmer_icons")
        os.makedirs(_IMG_DIR, exist_ok=True)
    path = os.path.join(_IMG_DIR, f"{name}_{size}_{color.strip('#')}.png")
    if not os.path.exists(path): pixmap(name, size, color, 2.0).save(path)
    return f'<img src="{path}" width="{size}" height="{size}">'
