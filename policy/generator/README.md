# Scene generator

An LLM writes real MuJoCo MJCF for a scene from a plain brief. Results are in `results/`. The physics is uncalibrated, and every run is simulated.

## Flow
1. `prompt.py`: one contract for both models.
2. `gate.py`: strict XML with no DTD or entities, an element and attribute allowlist, typed values, caps. It never imports MuJoCo. It returns canonical XML rebuilt from the checked tree.
3. `harness.py` and `worker.py`: compile under sandbox-exec with CPU, memory, wall-time and file limits. Then: finite state, robot start clear, a reachable surface, settle with no divergence, bounded energy.
4. Reasons come from fixed text, so model text never returns through them. A failed file gets up to 2 repair tries. `eval.py` keeps all attempts in `policy/runs/generator/`.

`check_generator.py` needs no LLM. It runs the hostile MJCF, the limits, a valid trial and its replay.

## Commands
Run these from this folder with `../.venv/bin/python`: `check_generator.py`, then `eval.py generate`, `trials`, `blind`, `report`.

## How a generated scene joins the sim
`scene_sim.py` keeps our options, robot, tether and actuators, and drops the rest of our scene. `sim.py` does not read geoms for most of its physics: it takes joints, ledges, nose heights and the dirt mask from world numbers. So `SceneSim` replaces those inputs with boxes measured from the compiled geoms. Air, wind, battery, pad and dirt numbers stay those of `policy/highrise/worlds/nominal.json`.

## What the generator cannot do
- **Curved or angled glass.** The required glass is flat, vertical and on y=0. `sim.py` assumes this in `_corner_gaps`, `_update_pads`, `step` (adhesion along +y), `_apply_wind_and_line`, `gap_center` and the IMU heading. `judge.py` uses the same gap, and `controller.py` plans flat lanes. A curved facade needs a surface query (distance and normal at a point), adhesion and pads along that normal, wind on that normal, a new detach rule and a new controller. None of this exists.
- **Moving things.** No joints or mocap, so no cradle travel, no people, no vehicles. Schema `cradle` moves; a generated one is a parked box.
- **Weather and materials.** Rain, wet patches, dust and temperature come from world numbers, not from MJCF. A generated vent is a solid. It has no leak, unlike schema `vent`. Generated glass friction is ignored; our merge sets it.
- **Exact sensing.** A raised solid reaches the skirt-leak and nose models as its bounding box. A rotated or round shape counts as its larger box.
- **Tether contact.** The tether passes through every geom, as in the schema worlds.
- **Meshes and files.** Primitives and builtin textures only. A 45-storey facade must fit in 600 geoms.
- **Fit to brief.** The gate proves a scene is safe to load, not that it matches the brief. Objective fit checks read names and boxes, so they can be fooled.

## Trust
- A generated file is data. The gate reads it, and nothing executes it.
- Every worker re-gates its input.
- sandbox-exec shares the kernel with the host and Apple marks it deprecated, so it is one layer. MJCF parser memory bugs stay unknown (threat model, "Unknown").
- Stills render offscreen outside the sandbox, after the gate, because the sandbox blocks the GL path. Those processes have no CPU or memory limit.

## How to read results/eval_table.md
- One run per brief, per model. Six in-scope briefs is a small sample.
- "claude" is the default of `llm.py`, Sonnet, with tools off. "astra" is gpt-6-astra. `gpt-6.1-astra` returned model_not_found on 2026-11-06.
- Blind stills: one reader, scores 0 to 3, model names hidden. The reader had already seen some geometry dumps and trial results, so the scores are only partly blind.
- One fit check changed after the first results. The setback check counted only tiers behind the glass, and it failed a real setback that stepped outward from y=0. The same corrected check ran on both models.
- No hostile brief made a model write a hostile file. So the eval did not stress the gate. `check_generator.py` does.
- A trial pass often means the scene does not touch the robot. For example, Claude's flat-wall mullions are visual only, so the robot drives through them.
- Astra ran with the ASTRA.md command, with network off for the 3 hostile briefs. Its logs show only file patches, and each folder holds one file.
- Schema generation was not run head to head on these briefs.
