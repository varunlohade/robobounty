# One world, edited by functions

AI-written plan (Claude), directed by the owner, 2026-11-06.

Owner's words: "the engine has all this verticals edited by a function and all ai does is call those functions". "a real world which i can change by prompting". "i am okay if its slow just make sure that its working".

## Rules
- Window robot only for now.
- One world file. It compiles to: physics MJCF for MuJoCo, a Blender scene through our own bpy functions, and a browser preview.
- The AI picks typed functions and arguments. Code validates every call. The AI writes no code and no MJCF. Blender MCP's execute-code tool is never used.
- `policy/highrise` stays untouched, so old evidence and bounty specs stay valid. New results carry the code hash of `policy/highrise5` and the label "sim highrise5 <sha12>".
- Results are simulated, with hand-built physics. Never claim scientific accuracy, real failures or an AI robot.
- A thing the engine cannot build returns `cannot_build:<reason>` and shows it to the user. Never fake it.

## World file: `policy/highrise5/world5.py`
`{schema, tower{height_m,width_m,floor_m,shape:"flat"}, area, panes, objects[], materials{}, weather, wind, light, surroundings, robot, robot_start}`. `upgrade(v3|v4)` maps the ledge fields and elements 1:1 into objects.

## Compiler
`compile(world) -> physics_xml, view_xml, effects[]`. physics_xml holds only solids, so a picture edit leaves its hash unchanged. Each object gets `effect: physics|picture`, set by code: solid and within 0.13 m of the glass means physics.

## Functions
| Function | Arguments | Physics | Picture | Re-run |
|---|---|---|---|---|
| set_tower | height 40-300, width 10-80, floor_m 3-5 | roof, anchor, tether, floor joints | tower, parapet | yes |
| set_panes | w, h, offx, offz, joint_depth, joint_gap, skip | joint leak, nose | bars | yes |
| set_work_area | w, h, drop, margin | glass rect, lanes | glass | yes |
| add_ledge, sill, fin, sign, balcony, vent, frame_step, wet_patch, dirt_patch, cradle; set_corner; set_setback | as elements.py, plus material | box, leak, nose, mask | box | yes |
| add_object | name, shape box/cyl/sphere/capsule, size, pos(x, below_top, out), euler, material, solid | collision, leak, nose if solid and near glass | geom | solid only |
| add_part | name, crane/antenna/ac_unit/billboard/cradle_parked/tree/car, pos, rot, scale | per library piece | group | if a solid is near glass |
| group, repeat, move_object, rotate_object, remove_object | names, count, step, delta | as members | as members | if physics |
| set_material, assign_material | rgba, roughness, metal | none | yes | no |
| set_weather, set_wind, set_robot, set_dirt, set_robot_start | existing ranges | yes | yes | yes |
| set_light, set_surroundings | sun_level, azimuth, haze, sky, city_seed, density, radius | none | yes | no |
| generate_object | description, real_size_m, position, rotation, solid | hulls if solid and near glass | mesh | if physics |
| read_world, read_result, undo, list_parts, explain_limits | none | none | none | no |

Caps: 600 geoms, 300 solids, 120 objects, 12 parts, 20 generated objects with 16 hulls each. Robot heading stays fixed.

## Order
1. World v5.
2. Compiler, three targets.
3. Functions.
4. AI loop: `{calls:[{fn,args}]}`, `--model claude-opus-5-5`, at most 3 rounds of call, validate, compile, run, read result. Each applied batch is world_N.json. `undo` restores N-1. One plain line per call.
5. sim5.py, a copy of sim.py, reads compiled object rects, vents and patches.
6. Browser view reads tower, panes, materials and surroundings from the world. The `set_look` work moves into the `materials` and `light` blocks. Demo is safe here.
7. Blender bpy target reads compiled objects.
8. Library parts.
9. generate_object with a Poly Haven backend: GLB, trimesh checks, scale, coacd hulls, mass, cache. The view needs a mesh draw path.
10. Text-to-3D backend: after the deadline unless the owner rents a GPU.

Cut: curved glass, moving machinery, people, fluids, cloth.

## Limits
Blender at about 17 s per frame gives about 34 frames in a 10 minute wait. Physics stops at detach, so the fall is not shown. Calibration, cross-machine replay and robot import are not done by the deadline. Isaac Sim is worth a look only if a real team already runs it.

## After the AI loop: test in all directions
Owner's words: "after this have a tab somewhere saying simulate it in all possible directions". One button in `lab.html` starts the scenario agent on the current world. It reuses policy/crashlab/scenarios.py and the campaign runner, and shows the worlds, their reasons and results in a tab. It runs on sim5. It lists what it did not test. It never claims to cover every case.

### Owner's spec for that tab (2026-11-06)
His words: "when clicked it runs and writes down all possible combination and on the ui you can see all 44 square each running the simulator and whichever fails its marked as fails with possible reason which a user can click and check and change the robots code so like vscode after clicking a file will open up for failed ones we can have a option to open file, and see why it failed".
1. Click: the agent writes the list of worlds. The count comes from the agent; 44 is an example.
2. A grid has one square per world, each running at the same time and showing live progress.
3. A failed square is marked failed, with a possible reason from the diagnosis, labelled as possible.
4. Click a failed square: replay of that recorded run, and why it failed.
5. "Open file": a VS Code style editor tab opens the robot's controller at the traced line. The user can edit it and re-run that world, then all worlds. Edits go to a session copy, and the frozen files never change.
Check how squares show live state: 44 WebGL views will not fit, so use one shared canvas or light 2D squares fed from each run's progress.

## Other robots and Newton (owner, 2026-11-06)
His words: "i want to have world building where we actually build the world around it and simulate real physics with newton 1.1 ... Imagine a robotics company using it ... not using anything gimmicky but actually something useful." "I also need to see the code as well." "don't worry about licenses ... We're not selling it" for now; keep a note of what is used, so it can change before any sale.
Robot pack = model + controller + judge + world functions. Backend per pack: MuJoCo for the window robot, Newton for others if the test in policy/newton_lab passes. Installed Newton is 1.7.0, CPU only on macOS. Code must be visible: a VS Code style editor tab shows the robot's controller and the world file.

### Import a robot from the chat (owner, 2026-11-06)
His words: "a person imports a robot in the channel, like there is an option to import in the chat window, and then we build everything around it."
A "+" in the chat box offers: import a file (MJCF, URDF or a zip with its meshes) or pick from a library (Menagerie, Newton's robots). The file is untrusted data: strict parse, size caps, no paths outside the upload. The app reads joints, actuators, mass and size, shows the robot in the main area, and says plainly what it found. It then asks only for what is missing: "What drives this robot?" with options: a trained controller if one exists, the user's code, or a passive drop test. A robot with no controller must say so, never fake motion. Then the AI builds the world around it with the engine functions. Build order: after the Newton test and the robot pack split.
