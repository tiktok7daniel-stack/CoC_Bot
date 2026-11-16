import nowindow
nowindow.install()   # no black CMD windows for adb & co (also in every child process)
import gpu_setup
gpu_setup.activate() # NVIDIA: the CUDA torch (if installed) before anything loads torch
from multiprocessing import freeze_support
from launch import launch

if __name__ == "__main__":
    freeze_support()
    launch()
