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

### More robot packs the owner wants (2026-11-06)
His words: "a cleaner robot that cleans submarines underneth as well and other robot that runs on mars".
Mars rover: gravity 3.71 m/s2, thin air, rough heightfield terrain, rocks, low friction; a rocker-bogie rover with a scripted drive. Loose sand as grains needs Newton MPM, which needs a GPU.
Hull cleaner: needs curved surface adhesion (surface query, like the curved glass work), magnet or thruster model, water density and drag from MuJoCo's fluid model, a current as a force. No wave or flow simulation.
Both are robot packs: model, controller, judge, world functions.

### Test flow, owner's full description (2026-11-06)
His words: "after the world is built and we have all the configurations of the world ... we say agent to figure out all the test cases ... then we say run ... wherever it fails. It corrects the code and tries to run that again ... the main simulation window ... zooms out, and there are like 40 or 50 simulations ... You can hover on a scenario and you can see, oh, this scenario means this, and there would be a detailed log and description panel ... Whenever it gets stuck, it goes to red, and the user can then figure out how to fix it, or ask AI to fix it."
Steps: world and its settings; agent lists scenarios with a reason each; user says run; main area zooms out to a grid of live runs; hover shows meaning; click opens a log and description panel; failed or stuck goes red; user edits the code or asks the AI to fix; re-run.
Guards for AI fixes: a fix is a session diff shown to the user. It is tested on held-back worlds, with no regressions. A fix that weakens a safety guard is flagged, since an earlier best patch passed more worlds by removing the low-pressure guard. The controller is the only thing a fix can change: never the judge or the world. Scenarios are the AI's reasoned guesses, not evidence that they occur in real use, and are labelled so.

### Product flow, final order from the owner (2026-11-06)
1. Import the robot in the chat and say its job. 2. The AI builds the world. 3. The user modifies the world by chat until satisfied. 4. The user asks for all scenarios, and the agent lists them. 5. The user says run. 6. The main window zooms out to a grid of live runs; click for details. 7. Red means failed or stuck; the user or the AI fixes the code and re-runs.

### Objects must belong (owner, 2026-11-06)
His words: "anything what you are building basically should also mimic the environment, so it shouldn't look just like it's just added for the sake of adding."
Rule for every pack: objects use realistic materials and are things found at that site, with mounts or supports, never floating. A vague request becomes a plausible object, and the chat says what it chose. Plain shapes or bright colours appear only on a clear request.

## Build plan: neutral policy testing, two robots (Fri 17:00 to Sat 09:00 IST)
Facts: window run 3-28 s; campaigns 34-74 trials/min on 4 procs. Inspection run 17-46 s for 30 s sim. 
1. Window pack adapter: `policy/packs/window/pack.py` wraps engine5, world5, compile5, run_trial5, judge5. Check: packs.missing() empty, one run passes. Owner A.
2. Pack subprocess: `policy/server/pack_job.py`, `policy/packs/inspection/job.py`: catalog|call|run|judge, JSON on stdin/stdout, run with .venv-newton, writes a heartbeat and progress.json (t, xy, status) each second. Check: plant world runs under the run deadline. Owner A.
3. Robot picker: chat "+" with two packs, import entry says not yet; session stores pack; turn5 becomes one loop over the pack. Check: a message on inspection adds a box. A server, B chat.
4. Poses player: `src/lab/poses.ts`: three.js solids and scenery, one capsule per body, route line, same shell. Check: plant.replay.json.gz plays. B.
5. Scenario agent per pack: `policy/crashlab/scenarios_pack.py`: scenarios {name, reason, calls[]}, each call replayed through pack.call on a copy, a refusal drops it, count from the agent, cap 50, 1 in 5 per group held back, not_tested list, reasons shown as "Reasoned guess: ...". Check: 40+ valid worlds from a stored reply. A.
6. Grid: `src/lab/grid.ts`: a 2D canvas per square, `grid` SSE event at 1 Hz from progress files, swap() replaces the viewport, click returns to the full view. Hover: name, reason. Detail rail: judge reason, events, log lines, Open file. Red: failed, or no progress for 30 s. MAX_PROCS measured first. A/B.
7. Code tab: CodeMirror 6 in `src/lab/code_tab.ts`, session copy, opened at the traced line. Run through fix.validate_source and fix.run_sandboxed with sandbox_worker5.py. Inspection: RouteFollower only. D.
8. AI fix: fix.py gets --base controller5.py; held-back worlds are the fresh set; flag diff lines touching LOW_PRESSURE_PA, RESUME, TETHER, HOLD. Inspection: RouteFollower constants only. D.
9. Recorded fallback: stored replies in policy/server/fixtures, one recorded batch each in policy/runs/demo, played by --recorded. C.
Demo is safe after 1, 2, 5, 6, 9. Cut in order: ONNX upload, import, inspection AI fix, live inspection grid, code tab run. Bounty board: latest start 05:30 Sat.

## Bounty board: solve what the company cannot (owner, 2026-11-06)
His words: "we can have the bounty board to solve issues company are facing". Earlier: the AI tries a fix first; if it fails, the company posts a bounty for experienced engineers.
Flow: a red failure the AI could not fix gets "Post a bounty": the failure pack and pay. Engineers read it and submit a controller change. Code runs it in the sandbox on the same worlds and on hidden held-back worlds, with the frozen judge and no regressions. A pass goes to the dispute window, then payment. Finding new failures stays as a second bounty type.

### The agent pays people (owner, 2026-11-06)
His words: "our AI agent can actually pay operators or pay people, pay people to try out test cases and pay it if it works well."
The company funds a capped budget. The agent posts bounties from it. Code and the contract decide each payout from the gate result; the agent never does. Later: pay operators with real robots to run a test and upload logs, as real data for comparison with the simulator.

## Ideas to adapt from self-driving testing (owner, 2026-11-06)
His words: "automated driving companies doing this, right? Can we adapt some implementation". Steve's order:
1. Operating limits: the company states where the robot must work (wind up to X, wet glass, height). Scenarios and bounties stay inside them, and results report coverage of them.
2. Scenario families with ranges, plus a boundary search: after a failure, search nearby values to report "fails above 11 m/s with wet glass", not only pass or fail.
3. Regression suite: every failure found is saved and re-run on each code change.
4. Later: replay real logs into simulation, then compare, which is how a company comes to trust a simulator.

### Bounty build plan (Fri 18:40 IST)
Kinds: fix_failure, find_failure. Folder policy/runs/board/<id>/: pack.json (pack, controller copy and sha, frozen shas of judge and sim, public failing worlds, replays, judge reason, pay, cap, window, status), hidden.json 0600 (held-back and passed-before worlds, never served), campaign/ copy, ledger.json.
Solver check, board_fix_gate.py: calls fix.py run --base --group --pack --patch. Pass: every target world passed or safe hold, zero worse in all four sets, zero replay mismatch, zero limits hit. Safety flags send it to awaiting_company, and the company approves. Then propose on the ledger. Queue: one gate lock, cap 4, 5 per tester, source up to 60 KB, same source sha refused. Window: controller5.py under the AST allowlist. Inspection: RouteFollower, _closest_on_leg, six constants. Limits: 240 s, 200 CPU s, 1500 MB, kill means fail. Say plainly: World ID not connected; sandbox-exec shares the kernel; inspection has no replay re-judge unless proven.
App: bounties.html, src/board/*.ts, vite port 5299, /api/bounties, /api/fixable, real data only with an empty state, both labels fixed. A grid button opens ?post=<session>/<cid>/<group>.
Chain: no Solidity change. fingerprint = keccak(bountyId, patched_sha), perFailure = pay, cap = pay, so a second fix hits CapExceeded. Tonight: anvil 31337. Arc needs the booth answer and owner keystores.
Budget: policy/bounty/budget.py, budget.json {cap, held, spent, stopped, per_bounty_max}, spend.jsonl. agent_post.py: code posts, not the LLM. Triggers: a fix report of did_not_help, rejected or no_change gives fix_failure; a not_tested item mapped to world fields gives find_failure with limits from the campaign. No physics model means "no gate, not posted". Submission text, tester names and source never enter any prompt. POST /api/budget/stop.
Tasks: 1 board_fix.py, 2 board_fix_gate.py, 3 board_fix_routes.py, 4 bounties.html and src/board, 8 budget and agent_post, 5 grid button, 6 check_board_fix.py, 7 anvil mirror. Cut 7, 6, 5 in that order.
Later: real_run.v1.json operator upload, labelled unverified until a human checks it.
