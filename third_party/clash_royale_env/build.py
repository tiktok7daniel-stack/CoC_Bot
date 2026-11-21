"""Build the engine for the running Python into assets/royale/engine/ (needs a C++20 compiler and pybind11)."""
import os, shutil, sys, sysconfig, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.environ.get("ENGINE_OUT") or os.path.join(HERE, "..", "..", "assets", "royale", "engine"))


def main():
    from setuptools import Distribution
    from pybind11.setup_helpers import Pybind11Extension, build_ext
    msvc = sys.platform == "win32"
    ext = Pybind11Extension(
        "clash_royale_env", [os.path.join(HERE, "src", "bindings.cpp")],
        include_dirs=[os.path.join(HERE, "include", d) for d in ("core", "entities", "rendering")],
        cxx_std=20,
        extra_compile_args=["/O2", "/bigobj", "/EHsc"] if msvc else ["-O2"])
    tmp = tempfile.mkdtemp()
    dist = Distribution({"name": "clash_royale_env", "ext_modules": [ext]})
    cmd = build_ext(dist)
    cmd.build_lib, cmd.build_temp = tmp, os.path.join(tmp, "t")
    cmd.ensure_finalized()
    cmd.run()
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(tmp):
        if f.startswith("clash_royale_env") and f.endswith((".pyd", ".so")):
            shutil.copy2(os.path.join(tmp, f), os.path.join(OUT, f))
            print("built", os.path.join(OUT, f))


if __name__ == "__main__":
    main()
