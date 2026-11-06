# Lab events: server contract for the grid and the two robots

AI-written contract (Claude Code, Owner A), for Owner B on `src/lab/*`. A change here means this file changes and steve hears about it.
Every result is simulated. Every scenario reason is a guess by the AI and arrives already labelled.

All routes keep the existing rules: `Origin` must be the app's, the event stream works on `<sid>.localhost:<port>` and the rest on `127.0.0.1:<port>` or `localhost:<port>`.

## Packs

`GET /api/packs`

```json
{"packs": [
  {"name": "window", "label": "Window cleaning robot", "robot": "suction_window_cleaner", "backend": "mujoco", "note": "Simulated...", "viewer": "trial", "max_procs": 8},
  {"name": "inspection", "label": "Inspection robot", "robot": "anymal_c", "backend": "newton", "note": "Simulated...", "viewer": "poses", "max_procs": 6}
 ],
 "import": {"available": false, "note": "Importing a robot is not built yet."}}
```

`max_procs` values above are examples; read them from the reply. `viewer` says which player shows that pack's runs.

## Session

`POST /api/sessions` with `{"pack": "window"}` or `{"pack": "inspection"}` replies `201 {"id": "<sid>", "pack": "window"}`.

- `{"engine": "v5"}` with no pack still works and means `window`. No `pack` and no `engine` stays the old app path.
- An unknown pack replies `400 {"error": "unknown_pack"}`.
- `GET /api/sessions/<sid>/state` replies `{"phase", "busy", "engine", "pack"}`.

## Chat on each pack

`POST /api/sessions/<sid>/message` as today. Both packs emit `user`, `text`, `tool`, `working`, `idle`, `card` as today.

**window**: the world, view and replay events do not change: `world`, `view`, `trial`, `sim`, `camera`.

**inspection** has two events of its own, and never sends `world`, `view` or `trial`:

```json
{"type": "pose_world", "pack": "inspection", "hash": "<physics hash>", "world": {},
 "solids": [], "scenery": [], "route": [{"x": 0, "y": 0}], "floor_friction": 0.75, "note": "Simulated..."}
{"type": "pose_trial", "label": "Normal run", "passed": true, "verdict": "passed", "reason": "...", "url": "/api/sessions/<sid>/pose_runs/<key>/replay"}
```

`pose_world` also comes on load, before the first message, so the page has a scene. The `url` gives one `robot-pack-replay/1` JSON (see Replay).

## The test flow

1. List: `POST /api/sessions/<sid>/action` with `{"action": "list_scenarios", "value": "<optional words on the job>"}` replies 202. A chat message that asks for all scenarios or test cases does the same.
2. The `scenarios` event comes, then `idle`. `value` may be null.
3. Run: `{"action": "run_campaign"}` replies 202. A chat message of `run`, `run it`, `run all` or `go` does the same while a list waits.
4. `grid` comes at 1 Hz while it runs. `campaign_done` comes at the end, then `idle`.

Both actions reply `409 {"error": "busy"}` during another job, and `run_campaign` replies `409 {"error": "not_now"}` with no list waiting. One campaign runs at a time on one server: a second one waits, with a `working` line.

## `scenarios` event

Stored in the event list, like any event.

```json
{"type": "scenarios", "campaign": "c1", "pack": "window", "count": 44, "to_run": 36, "held_back": 8,
 "count_reason": "Why the agent chose this count.",
 "note": "Reasons are the AI's reasoned guesses, not evidence that these cases occur. Results are simulated.",
 "groups": [{"name": "High wind", "reason": "Reasoned guess: ...", "count": 6}],
 "worlds": [{"index": 0, "name": "gust_on_top_lane", "group": "High wind", "reason": "Reasoned guess: ...", "held_back": false, "seed": 3100, "changes": ["set_wind ..."]}],
 "not_tested": [{"factor": "Airborne sand", "reason": "...", "source": "agent"}],
 "dropped": {"refused:out_of_range": 2, "not_belonging": 1},
 "rejection": null}
```

- `rejection` is a fixed code when no list came, with `count` 0, for example `llm_timeout`. `not_tested` still holds the code's own items.
- `source` is `agent` or `code`.
- `dropped` counts scenarios the code refused, by reason. They are not in `worlds`.
- `index` is stable for the campaign. `changes` holds one plain line per call.

## `grid` event

It arrives on the normal event stream as a plain `data:` message with `"type": "grid"`, at 1 Hz. **It has no `id:` line** and stays out of the stored event list, so a reconnect gets only the latest grid, and `?after=` is unaffected. Each one is the full state, so a missed one costs nothing. Check `type === 'grid'` before you read `lastEventId`: `src/app/chat/live.ts` turns an empty one into 0, which is wrong if a grid were the first message on a stream.

```json
{"type": "grid", "campaign": "c1", "pack": "window", "running": true, "elapsed_s": 41.2, "max_procs": 8,
 "counts": {"queued": 20, "running": 8, "passed": 5, "failed": 3, "stuck": 0, "held": 8},
 "rows": [{"index": 0, "name": "gust_on_top_lane", "group": "High wind", "reason": "Reasoned guess: ...",
           "status": "running", "held_back": false, "t": 37.5, "t_limit": 600.0, "x": 1.2, "y": 41.7,
           "outline": {"kind": "area", "x0": -1.2, "x1": 1.2, "z0": 40.0, "z1": 43.0},
           "verdict": null, "verdict_reason": null}]}
```

**`status`**

| Value | Meaning | Draw |
|---|---|---|
| `queued` | Not started. | quiet |
| `running` | Child is alive and moving. | live |
| `passed` | The judge passed it. | pass |
| `failed` | The judge failed it, the physics blew up, or the process crashed. A result. It is never retried. | red |
| `stuck` | No progress for 30 s while the run is alive. It returns to `running` if progress resumes. A run killed at its deadline stays `stuck`, with a reason. | red |
| `held` | Not a pass and not a fail, see below. | amber or grey |

`held` covers two cases, and `held_back` tells them apart:
- `held_back: true`: this world is kept back as the fresh set for testing a fix. It does not run in the campaign. `t`, `x`, `y` are null.
- `held_back: false`: the run ended with the robot safely holding itself (`verdict` is `wind_hold` or `battery_stop`). The job did not finish, and nothing failed.

**Position**: `t` is simulated seconds, `t_limit` is the end of the run's simulated time. All three are null before the first progress.
- window: `x` is metres across the glass, `y` is the height in metres (world z).
- inspection: `x`, `y` are metres on the floor.

**`outline`**: window `{"kind": "area", "x0", "x1", "z0", "z1"}`. inspection `{"kind": "route", "points": [[x, y], ...]}`, starting at the origin.

**`verdict`** is a code once a run ended: `passed`, `wind_hold`, `battery_stop`, `sim_diverged`, `process_crashed`, `froze`, a window rule (`detach`, `tether_load`, `slip_distance`, `stalled`, `time_limit`, `coverage`, `false_done`) or an inspection verdict (`fell`, `stuck`, `timed_out`, `off_route`, `sim_failed`). **`verdict_reason`** is one plain sentence from code. Show it as it is.

Hover uses `name` and `reason`.

## `campaign_done` event

Stored.

```json
{"type": "campaign_done", "campaign": "c1", "counts": {}, "wall_s": 312.4, "max_procs": 8, "label": "sim highrise5 <sha12>", "note": "Simulated..."}
```

The server also emits `text` lines with the counts and the `not_tested` count.

## Fetching

Every path starts `/api/sessions/<sid>/campaigns/<campaign>`.

| Route | Reply |
|---|---|
| `GET .../grid` | The latest `grid` object. Use after a reload. `404` before a campaign. |
| `GET .../scenarios` | The `scenarios` object. |
| `GET .../worlds/<index>` | The detail, below. |
| `GET .../worlds/<index>/replay` | How to play it, below. `404 {"error": "no_replay"}` when the run has not ended, or left no record. |

### World detail

```json
{"index": 7, "name": "...", "group": "...", "reason": "Reasoned guess: ...", "status": "failed", "held_back": false,
 "verdict": "detach", "verdict_reason": "The robot came off the glass at 41.2 s.",
 "numbers": {"coverage": 0.41, "min_pressure_pa": 1320.0},
 "events": [{"name": "detach", "t": 41.2, "value": 0.031}],
 "log": ["last lines of the run's log"],
 "code": {"file": "policy/highrise5/controller5.py", "line": 212, "why": "...", "traced": false},
 "changes": ["set_wind ..."], "world": {}, "seed": 3107, "wall_s": 18.2,
 "label": "sim highrise5 <sha12>", "note": "Simulated...", "replay": true}
```

- `numbers` holds that pack's numbers, keys differ by pack. Show them as label and value.
- `events` are the judge's fired events, ordered by time. May be empty.
- `code` is null when no file or line is known. `traced: false` means the line is the code active at that moment and not an executed-line trace, so call it "active code", not "the bug".
- `replay` says whether the replay route will answer.

### Replay

`GET .../worlds/<index>/replay` replies with JSON that says how to play the run. It may take some seconds on window, since it checks the run by replaying it once.

- window: `{"kind": "trial", "tid": "c1-007", "label": "..."}`. Load it with the existing trial player from `/api/sessions/<sid>/trials/<tid>/<file>`.
- inspection: `{"kind": "poses", "url": "/api/sessions/<sid>/campaigns/c1/worlds/7/poses"}`. That URL gives one gzip-encoded `robot-pack-replay/1` JSON: `format, pack, robot, label, note, simulated, fps, body_labels, body_parents, pose_layout, route, floor_friction, solids, scenery, result, frames[{t, q}]`. `q` holds 7 numbers per body in `pose_layout` order. It has the same shape as `policy/packs/inspection/out/plant.replay.json.gz`.

## Not in this contract yet

Code tab, AI fix and running held-back worlds. Those belong to tasks 7 and 8.
