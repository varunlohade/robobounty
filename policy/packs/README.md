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

**The window robot's pack would wrap `policy/highrise5`**, with no edit there: `call`, `catalog` wrap `engine5.call`, `engine5.catalog`; the adapter holds engine5's state and hands back `state["world"]`. `new_world`, `validate` wrap `world5`. `physics_hash`, `load_model` wrap `compile5.physics_hash`, `compile5.compile`. `controller_files` names `controller5.py`. `run` wraps `run_trial5.run`. `judge` wraps `judge5`, which reads the sim live, so the adapter must store its result in the record. `replay` wraps `export5.py`, which writes files, not one JSON. These three gaps are real and not yet built.

`inspection/` is the first pack: ANYmal C on Newton 1.7.0, CPU. Check it from `policy/` with `.venv-newton/bin/python -m packs.inspection.check_pack`. Solids on the walkway are one list, `world.primitives`, read by the physics and the picture alike. Hall scenery is picture only and never enters the physics. `render.py` sets textures and lights through private fields of Newton's camera, so a Newton upgrade may break the picture but not the physics. Results are simulated. The policy is upstream's and unchecked against a real robot. Asset license: BSD-3-Clause (ANYbotics), in Newton's asset repo.
