# Robot packs

A pack is one robot with one job: model, controller, judge and world functions behind one file, `<pack>/pack.py`. The app imports only that file. `packs/__init__.py` lists the names in `CONTRACT`.

| Name | What it does |
|---|---|
| `NAME`, `ROBOT`, `BACKEND`, `SIMULATED_NOTE` | Plain strings. The note is shown with every result. |
| `new_world()`, `validate(world)` | A world is JSON data with no code and no paths. `validate` replays it through the checks. |
| `call(world, fn, args)` | Untrusted input. Returns `{"result", "rerun", "world"}` with `ok`, `picture only, no re-run` or `cannot_build:<code>`. The old world never changes. |
| `catalog()`, `physics_hash(world)` | The functions as JSON for the AI. A picture edit leaves the hash the same. |
| `load_model(world)` | The backend's model. Only the pack reads it. |
| `controller_files()` | Source paths for the editor tab. This is the code a user or an AI fix may change. |
| `run(world, seed=, out=)` | One run. Returns `(record, meta)`: state per frame, and the label, seed and world. |
| `judge(record, world)` | From recorded state only. Returns `verdict`, `passed`, a plain-words `reason`, and numbers. |
| `replay(record, meta, result)` | JSON for a browser: per-frame poses, solids, scenery, and `simulated: true`. |

`window/` wraps `policy/highrise5`, with no edit there. Its adapter holds engine5's state and hands back `state["world"]`, so a group made by one call lasts only in that process. `judge` reads the result the record stores, because `judge5` reads the sim live. `replay` gives one JSON. The app's own player still reads `export5`'s files, which also replay the run and refuse a mismatch.

Each pack also has `job.py`, its subprocess under its own Python. `policy/server/pack_job.py` lists the commands, and it writes `progress.json` each second during a run.

`inspection/` is: ANYmal C on Newton 1.7.0, CPU. Check it from `policy/` with `.venv-newton/bin/python -m packs.inspection.check_pack`. Solids on the walkway are one list, `world.primitives`, read by the physics and the picture alike. Hall scenery is picture only and never enters the physics. `render.py` sets textures and lights through private fields of Newton's camera, so a Newton upgrade may break the picture but not the physics. Results are simulated. The policy is upstream's and unchecked against a real robot. Asset license: BSD-3-Clause (ANYbotics), in Newton's asset repo. The browser draws the robot from `public/robots/anymal_c/`, which `python -m packs.inspection.export_robot` writes from that asset, picture only, with the LICENSE beside it.
