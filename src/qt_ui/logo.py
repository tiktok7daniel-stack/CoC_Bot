"""
Clash Farmer brand: the crest (SVG) and the 3D gold wordmark, drawn in code so they stay sharp at any size.

Crest  : a heater shield with a riveted gold rim; inside, a deep crimson field with a golden wheat stalk
         crossed by a steel sword (farming + clashing), light catching the top-left edge.
Wordmark: "CLASH" over "FARMER" in Lilita One, extruded gold letters with a dark outline, a hot top
         highlight and an optional moving shine (the intro animates it).
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

from . import theme

CREST = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
<defs>
 <linearGradient id="rim" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFF1B8"/><stop offset=".28" stop-color="#FFD24A"/><stop offset=".62" stop-color="#E29A1C"/><stop offset="1" stop-color="#8A5208"/></linearGradient>
 <linearGradient id="rimside" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#7A4606"/><stop offset="1" stop-color="#3A1F02"/></linearGradient>
 <linearGradient id="field" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#C4223A"/><stop offset=".55" stop-color="#8E1026"/><stop offset="1" stop-color="#4A0614"/></linearGradient>
 <linearGradient id="fieldshade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFFFFF" stop-opacity=".22"/><stop offset=".45" stop-color="#FFFFFF" stop-opacity="0"/></linearGradient>
 <linearGradient id="steel" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".5" stop-color="#C6CED8"/><stop offset="1" stop-color="#5E6875"/></linearGradient>
 <linearGradient id="wheat" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF0A8"/><stop offset=".5" stop-color="#FFC93C"/><stop offset="1" stop-color="#C98314"/></linearGradient>
 <linearGradient id="hilt" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#8A5208"/><stop offset=".5" stop-color="#FFD24A"/><stop offset="1" stop-color="#8A5208"/></linearGradient>
</defs>
<path d="M64 10 110 22v36c0 30-20 50-46 62C38 108 18 88 18 58V22z" fill="url(#rimside)" transform="translate(0 5)"/>
<path d="M64 10 110 22v36c0 30-20 50-46 62C38 108 18 88 18 58V22z" fill="url(#rim)" stroke="#2A1602" stroke-width="2.5" stroke-linejoin="round"/>
<path d="M64 20 100 29.5V58c0 24-16 40-36 50C44 98 28 82 28 58V29.5z" fill="url(#field)" stroke="#3A0610" stroke-width="2" stroke-linejoin="round"/>
<path d="M64 20 100 29.5V58c0 24-16 40-36 50C44 98 28 82 28 58V29.5z" fill="url(#fieldshade)"/>

<!-- wheat stalk: bottom-right to top-left, crossing the sword -->
<g>
 <path d="M86 98 45.1 38.5" stroke="#5A3204" stroke-width="4.4" stroke-linecap="round"/>
 <path d="M86 98 45.1 38.5" stroke="#E0A02A" stroke-width="2.6" stroke-linecap="round"/>
 <ellipse cx="65.7" cy="61.1" rx="6" ry="3.1" transform="rotate(-92.5 65.7 61.1)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="58.8" cy="65.9" rx="6" ry="3.1" transform="rotate(-156.5 58.8 65.9)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="61.3" cy="54.7" rx="6" ry="3.1" transform="rotate(-92.5 61.3 54.7)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="54.4" cy="59.5" rx="6" ry="3.1" transform="rotate(-156.5 54.4 59.5)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="56.9" cy="48.3" rx="6" ry="3.1" transform="rotate(-92.5 56.9 48.3)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="50.0" cy="53.1" rx="6" ry="3.1" transform="rotate(-156.5 50.0 53.1)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="52.5" cy="41.9" rx="6" ry="3.1" transform="rotate(-92.5 52.5 41.9)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="45.6" cy="46.7" rx="6" ry="3.1" transform="rotate(-156.5 45.6 46.7)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="48.6" cy="36.1" rx="6" ry="3.1" transform="rotate(-92.5 48.6 36.1)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="41.6" cy="40.9" rx="6" ry="3.1" transform="rotate(-156.5 41.6 40.9)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <ellipse cx="42.0" cy="34.0" rx="6" ry="3.1" transform="rotate(-124.5 42.0 34.0)" fill="url(#wheat)" stroke="#5A3204" stroke-width="1.2"/>
 <path d="M39.7 30.7 37.9 21.0" stroke="#FFD24A" stroke-width="1.1" stroke-linecap="round"/>
 <path d="M39.7 30.7 31.3 25.6" stroke="#FFD24A" stroke-width="1.1" stroke-linecap="round"/>
</g>
<!-- sword: blade bottom-left to top-right -->
<g stroke-linejoin="round">
 <path d="M83 30 88 33 52 88 46 91 47 84z" fill="url(#steel)" stroke="#20262E" stroke-width="1.6"/>
 <path d="M84.5 31.5 49 86" stroke="#FFFFFF" stroke-opacity=".7" stroke-width="1"/>
 <path d="M40 80 56 92" stroke="#2A1602" stroke-width="7" stroke-linecap="round"/>
 <path d="M40 80 56 92" stroke="url(#hilt)" stroke-width="4.6" stroke-linecap="round"/>
 <path d="M44 92 39 100" stroke="#2A1602" stroke-width="6" stroke-linecap="round"/>
 <path d="M44 92 39 100" stroke="#7A4606" stroke-width="3.6" stroke-linecap="round"/>
 <circle cx="37.5" cy="102" r="3.6" fill="url(#rim)" stroke="#2A1602" stroke-width="1.4"/>
</g>
<!-- rivets + specular -->
<g fill="url(#rim)" stroke="#2A1602" stroke-width="1"><circle cx="64" cy="15.5" r="2.4"/><circle cx="104" cy="26" r="2.4"/><circle cx="24" cy="26" r="2.4"/><circle cx="105" cy="58" r="2.4"/><circle cx="23" cy="58" r="2.4"/></g>
<path d="M24 26v30c0 6 1 12 3 17" fill="none" stroke="#FFF7D6" stroke-opacity=".75" stroke-width="2" stroke-linecap="round"/>
<path d="M26 24 64 14l22 5.5" fill="none" stroke="#FFF7D6" stroke-opacity=".8" stroke-width="2" stroke-linecap="round"/>
</svg>'''


def _line_path(text, size):
    f = theme.display_font(size)
    f.setLetterSpacing(QFont.PercentageSpacing, 102)
    path = QPainterPath()
    path.addText(0, 0, f, text)
    return path


def wordmark_paths(width):
    """Two stacked lines scaled to `width` -> (path CLASH, path FARMER) positioned from y=0."""
    a = _line_path("CLASH", 100)
    b = _line_path("FARMER", 64)
    ra, rb = a.boundingRect(), b.boundingRect()
    s = width / max(ra.width(), rb.width())
    from PySide6.QtGui import QTransform
    ta = QTransform().scale(s, s)
    a, b = ta.map(a), ta.map(b)
    ra, rb = a.boundingRect(), b.boundingRect()
    a.translate(width / 2 - ra.center().x(), -ra.top())
    b.translate(width / 2 - rb.center().x(), a.boundingRect().bottom() + width * 0.02 - rb.top())
    return a, b


def paint_wordmark(p, x, y, width, shine=None, glow=0.0):
    """Draw the 3D wordmark with its top-left at (x, y). shine: 0..1 position of the light sweep."""
    a, b = wordmark_paths(width)
    path = QPainterPath(a)
    path.addPath(b)
    path.translate(x, y)
    br = path.boundingRect()
    depth = max(2, int(width * 0.028))
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if glow > 0: # warm halo behind the letters
        for k, al in ((width * 0.05, 26), (width * 0.03, 40)):
            p.setPen(QPen(QColor(255, 196, 70, int(al * glow)), k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
    outline = max(2.0, width * 0.022)
    # extrusion (the 3D side), darkest at the bottom
    for i in range(depth, 0, -1):
        c = QColor(58 + i * 6, 30 + i * 3, 2)
        p.setPen(QPen(QColor("#1A0D01"), outline, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(c)
        p.drawPath(path.translated(0, i))
    # outline + face
    p.setPen(QPen(QColor("#1A0D01"), outline, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    face = QLinearGradient(0, br.top(), 0, br.bottom())
    for stop, col in ((0, "#FFF5C4"), (0.22, "#FFE070"), (0.48, "#FFC12E"), (0.5, "#E99A12"), (0.78, "#F2B23A"), (1, "#B86A06")):
        face.setColorAt(stop, QColor(col))
    p.setPen(Qt.NoPen)
    p.fillPath(path, face)
    p.setClipPath(path)
    # inner bevel: thin light line hugging the top of each letter
    p.setPen(QPen(QColor(255, 250, 220, 150), max(1.0, width * 0.005)))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path.translated(0, max(1.0, width * 0.004)))
    if shine is not None:
        sx = br.left() - br.width() * 0.3 + br.width() * 1.6 * shine
        g = QLinearGradient(sx - br.width() * 0.12, br.top(), sx + br.width() * 0.12, br.bottom())
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 200))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(br, g)
    p.restore()
    return QRectF(br.left(), br.top(), br.width(), br.height() + depth)


def wordmark_pixmap(width, dpr=2.0, glow=0.0):
    a, b = wordmark_paths(width)
    h = b.boundingRect().bottom() + width * 0.06
    pad = width * 0.06
    pm = QPixmap(int((width + pad * 2) * dpr), int((h + pad * 2) * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_wordmark(p, pad, pad, width, glow=glow)
    p.end()
    return pm
