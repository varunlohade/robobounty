"""The chat's side of a generated object. It looks in the cache first, because a saved model costs nothing. The rules of making one live in generate_loop.py."""
import copy
import re
import shutil
import subprocess

KEEP, DROP = "keep", "drop"


def _loop():
    """Loaded on the first use, so the server's own import order stays as it is."""
    import generate_loop
    return generate_loop


def prompt_world(world):
    """A world for the AI's prompt: no hull numbers, which it never edits."""
    out = copy.deepcopy(world)
    for o in out.get("objects", []):
        o.pop("hulls", None)
    return out


def _picture(session):
    return lambda url, caption: session.emit(type="picture", url=url, caption=caption)


def ensure(description, session):
    """True when the model is in the cache on return."""
    L = _loop()
    if not isinstance(description, str) or not re.fullmatch(r"[A-Za-z0-9 ,.'-]{3,200}", description):
        return False
    entry = L.GO.find(description)
    if entry:
        session.say(f"Using the saved model of {entry['description']}. It needs no GPU.")
        return True
    made = L.make(description, session.say, session.working, mode="quality", show=_picture(session))
    if made["state"] == "ask":
        session.pending_model = made
    return made["state"] == "ok"


def asks(session, said):
    return getattr(session, "pending_model", None) is not None and said in (KEEP, DROP)


def answer(session, said):
    L = _loop()
    made, session.pending_model = session.pending_model, None
    if said == DROP:
        shutil.rmtree(made["folder"], ignore_errors=True)
        session.say("Dropped it. Nothing was added.")
        return
    stats = L.Stats()
    try:
        glb = made["glb"] or str(L._mesh(made["image_job"], made["mode"], 0, made["folder"], session.working, stats)[1])
        L.store(glb, made["words"], made["chosen"], stats, f"kept_after_no:{made['mode']}")
    except (OSError, ValueError, KeyError, L.GpuOff, subprocess.TimeoutExpired) as error:
        session.say(f"Keeping it stopped: {type(error).__name__}. Nothing was added.", True)
        return
    finally:
        shutil.rmtree(made["folder"], ignore_errors=True)
    session.say(f"Kept {made['words']}, marked as a model Claude said no to. Ask again to place it.")
