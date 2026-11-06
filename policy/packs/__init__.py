"""Robot packs. README.md describes the contract. A pack module must expose every name in CONTRACT."""
CONTRACT = ("NAME", "ROBOT", "BACKEND", "SIMULATED_NOTE", "new_world", "validate", "call", "catalog", "physics_hash", "load_model", "controller_files", "run", "judge", "replay")


def missing(pack):
    return [name for name in CONTRACT if not hasattr(pack, name)]
