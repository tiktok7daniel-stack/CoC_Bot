import nowindow
nowindow.install()   # no black CMD windows for adb & co (also in every child process)
from multiprocessing import freeze_support
from launch import launch

if __name__ == "__main__":
    freeze_support()
    launch()
