"""
Entry point of the v4 window: high-DPI + RTL setup, fonts, style sheet, animated splash with the
crest, then the main window connected to the bot's local server on `port`.
run_qt(port, pipe) is what gui.py starts in its window process.
"""
import os, sys

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QApplication, QSplashScreen

from . import icons, theme
from .api import Api
from .i18n import set_lang, tr


def splash_pixmap(text):
    w, h = 560, 320
    pm = QPixmap(w * 2, h * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.TOKENS["void"]))
    p.drawRoundedRect(QRectF(0, 0, w, h), 22, 22)
    g = QRadialGradient(w / 2, 110, 260)
    g.setColorAt(0, QColor(139, 92, 246, 120))
    g.setColorAt(1, QColor(139, 92, 246, 0))
    p.setBrush(g)
    p.drawRoundedRect(QRectF(0, 0, w, h), 22, 22)
    p.drawPixmap(int(w / 2 - 56), 34, icons.pixmap("crest", 112))
    p.setPen(QColor(theme.TOKENS["text"]))
    p.setFont(theme.ui_font(24, QFont.Bold))
    p.drawText(QRectF(0, 160, w, 44), Qt.AlignCenter, "CoC Bot")
    p.setPen(QColor(theme.TOKENS["muted"]))
    p.setFont(theme.ui_font(11))
    p.drawText(QRectF(0, 204, w, 26), Qt.AlignCenter, tr("app_sub"))
    bar = QLinearGradient(140, 0, 420, 0)
    bar.setColorAt(0, QColor(theme.TOKENS["violet"]))
    bar.setColorAt(1, QColor(theme.TOKENS["fuchsia"]))
    p.setPen(Qt.NoPen)
    p.setBrush(bar)
    p.drawRoundedRect(QRectF(140, 250, 280, 4), 2, 2)
    p.setPen(QColor(theme.TOKENS["dim"]))
    p.setFont(theme.ui_font(9))
    p.drawText(QRectF(0, 266, w, 24), Qt.AlignCenter, text)
    p.end()
    return pm


def create_app(argv=None):
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("CoC Bot")
    app.setOrganizationName("CoC_Bot")
    theme.load_fonts()
    app.setFont(theme.ui_font(10))
    app.setStyleSheet(theme.qss())
    app.setWindowIcon(QIcon(icons.pixmap("crest", 64)))
    lang = _saved_language()
    set_lang(lang)
    app.setLayoutDirection(Qt.RightToLeft if lang == "ar" else Qt.LeftToRight)
    return app


def _saved_language():
    try:
        import settings
        return settings.load_app().get("language", "ar")
    except Exception:
        return "ar"


def run_qt(port, pipe=None, debug=False):
    app = create_app()
    splash = QSplashScreen(splash_pixmap(tr("splash_loading")))
    splash.setWindowFlag(Qt.FramelessWindowHint)
    splash.setAttribute(Qt.WA_TranslucentBackground)
    splash.show()
    app.processEvents()
    from .window import MainWindow
    api = Api(port)
    win = MainWindow(api, pipe)

    def go():
        win.show()
        splash.finish(win)
        win.start()
    QTimer.singleShot(900, go)
    code = app.exec()
    if pipe is not None:
        try: pipe.send(-1)
        except (OSError, EOFError): pass
    return code


if __name__ == "__main__":
    # standalone: python -m qt_ui.app <port>  (connect to an already running bot server)
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    run_qt(int(sys.argv[1]) if len(sys.argv) > 1 else 5077)
