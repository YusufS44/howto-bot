# main.py
import importlib

for name in ("server.app", "app"):
    try:
        mod = importlib.import_module(name)
        app = getattr(mod, "app")
        break
    except Exception:
        continue
else:
    raise RuntimeError("Could not import FastAPI app from server.app or app")
