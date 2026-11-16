"""Entry point of the packaged CoC Bot v4: always opens the window (bot + v4 interface)."""
import sys
from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    if "--gui" not in sys.argv: sys.argv.append("--gui")
    from launch import launch
    launch()
