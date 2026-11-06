"""Blender entry for login film tiles. It runs an existing scene script unchanged (inspection_scene.py, or the wide-look scene.py), with two allowances. --fps may be a fraction, because a clip's time step is seconds of record per frame. scene.py's device comes from LOGIN_FILM_DEVICE, because it asks for Metal by name."""
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load(name, device=None):
    path = HERE / f"{name}.py"
    source = path.read_text().replace('"--fps", type=int', '"--fps", type=float')
    if device:
        source = source.replace('"METAL"', f'"{device}"')
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


if os.environ["LOGIN_FILM_SCENE"] == "window":
    import json
    import shots
    shots.SHOTS["login"] = json.loads(os.environ["LOGIN_FILM_SHOT"])
    load("scene", os.environ.get("LOGIN_FILM_DEVICE", "METAL")).main()
else:
    load("inspection_scene").main()
