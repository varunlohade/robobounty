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
