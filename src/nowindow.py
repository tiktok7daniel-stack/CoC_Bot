"""
Windows: programs started by the bot (adb, the emulator console, tesseract …) must never open a console
window. The app itself runs windowless (pythonw), so without this every console program it starts — above
all the adb server, which keeps running — would get its own empty black CMD window.
install() makes CREATE_NO_WINDOW the default for every subprocess that doesn't choose its own flags.
"""
import subprocess, sys

CREATE_NO_WINDOW = 0x08000000
_installed = False


def install():
    global _installed
    if _installed or sys.platform != "win32": return
    _installed = True
    original = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
