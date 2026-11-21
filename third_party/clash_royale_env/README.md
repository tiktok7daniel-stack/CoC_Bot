# clash_royale_env (vendored)

The battle engine of [itzik123/ClashRoyaleAi](https://github.com/itzik123/ClashRoyaleAi) (MIT, see LICENSE),
commit `ec28641b59e08967dca6b9b8c86d10f2f391182e`: `include/` (header-only C++) and `src/bindings.cpp` (pybind11), unchanged.

Built for Windows by `.github/workflows/royale_engine.yml` into `assets/royale/engine/`
(one `clash_royale_env.cp3XX-win_amd64.pyd` per Python version); used by `src/royale/engine.py`.

Build by hand (any OS): `python third_party/clash_royale_env/build.py`
