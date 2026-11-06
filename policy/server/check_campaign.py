"""The whole test flow: policy/.venv/bin/python policy/server/check_campaign.py [--pack window|inspection] [--limit N] [--live] [--faults-only]

It starts its own server on a free port and stops it. Stored scenario replies by default. --live makes one real AI call per pack, and needs --limit for its fewer worlds.
It checks: stuck and crash handling with fake children, pack sessions, the inspection chat, the scenario list, the grid stream, the world detail, the replay, and that a campaign's seed gives the same result as a direct run. Results are simulated.
"""
import argparse
import gzip
import json
import subprocess
import sys
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import site_auth
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
sys.path.insert(0, str(HERE))
import pack_campaign as PC
import pack_job as J

ORIGIN = "http://localhost:5199"
MESSAGE = "add a control cabinet beside the walkway"
failed = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + str(detail) if detail != '' else ''}", flush=True)
    if not ok:
        failed.append(name)


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, path, body=None, timeout=60, raw=False):
        request = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(), headers={"Origin": ORIGIN, "Content-Type": "application/json", "Authorization": f"Bearer {site_auth.local_token()}"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                data = reply.read()
                return reply.status, (data if raw else json.loads(data))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def stream(self, sid):
        return Stream(self.base + f"/api/sessions/{sid}/events")


class Stream(threading.Thread):
    """Collects events. Grids go to their own list, each with its arrival time and whether it carried an id."""

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.events, self.grids, self.ids_on_grids, self.stop = url, [], [], 0, False
        self.start()

    def run(self):
        request = urllib.request.Request(self.url, headers={"Origin": ORIGIN})
        with urllib.request.urlopen(request, timeout=60) as reply:
            has_id = False
            for line in reply:
                if self.stop:
                    return
                text = line.decode().rstrip("\n")
                if text.startswith("id:"):
                    has_id = True
                elif text.startswith("data:") and text != "data: 0":
                    event = json.loads(text[5:])
                    if event.get("type") == "grid":
                        self.grids.append((time.monotonic(), event))
                        self.ids_on_grids += has_id
                    else:
                        self.events.append(event)
                    has_id = False

    def wait(self, kind, timeout, after=0, also=None):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for event in self.events[after:]:
                if event["type"] == kind and (also is None or also(event)):
                    return event
            time.sleep(0.2)
        return None


def fake_children():
    """A child that freezes, one that crashes and one that pauses then goes on."""
    rule = type("Rule", (), {"quiet_s": None, "silent_s": 8.0})
    frozen = "import json,sys,time;r=json.load(sys.stdin);open(r['progress'],'w').write(json.dumps({'t':1.0,'x':0,'y':0,'status':'running'}));time.sleep(1000)"
    crash = "import os;os._exit(7)"
    pauses = ("import json,sys,time,pathlib;r=json.load(sys.stdin);p=pathlib.Path(r['progress']);o=pathlib.Path(r['out'])\n"
              "for t in (1,2):\n p.write_text(json.dumps({'t':t,'x':0,'y':0,'status':'running'}));time.sleep(4 if t==1 else 0.5)\n"
              "(o/'job_result.json').write_text(json.dumps({'passed':True,'verdict':'passed','reason':'Fine.','safe_hold':False,'end_t':2,'end_x':0,'end_y':0}));print('{}')")
    programs = [frozen, crash, pauses]
    worlds = [{"index": i, "name": f"w{i}", "group": "g", "reason": "r", "held_back": False, "t_limit": 10.0, "outline": {}, "world": {}, "seed": i, "changes": []} for i in range(3)]
    worlds.append({**worlds[0], "index": 3, "held_back": True})
    seen = {}

    def on_grid(grid):
        for row in grid["rows"]:
            seen.setdefault(row["index"], []).append(row["status"])

    def spawn(argv, **kw):
        return subprocess.Popen(argv, start_new_session=True, **kw)

    def kill(pgid):
        import os
        import signal
        os.killpg(pgid, signal.SIGKILL)
    with tempfile.TemporaryDirectory() as tmp:
        c = PC.Campaign("window", "c1", {"worlds": worlds}, tmp, 4, rule, spawn, lambda p: None, kill, argv_for=lambda w: [sys.executable, "-c", programs[w["index"]]], on_grid=on_grid, stuck_s=2.0)
        grid = c.run()
    rows = grid["rows"]
    check("a frozen child shows stuck, then its deadline stops it", "stuck" in seen[0] and rows[0]["status"] == "stuck" and rows[0]["verdict"] == "froze", rows[0]["verdict_reason"])
    check("a crashed child is a failed result", rows[1]["status"] == "failed" and rows[1]["verdict"] == "process_crashed", rows[1]["verdict_reason"])
    check("a child that resumes goes from stuck back to running, then ends passed", "stuck" in seen[2] and seen[2].index("stuck") < len(seen[2]) - 1 and rows[2]["status"] == "passed", seen[2])
    check("a held-back world never starts", rows[3]["status"] == "held" and rows[3]["t"] is None and set(seen[3]) == {"held"})


def direct_result(pack, world, seed):
    """The same world and seed with no server, no job file and no progress hook."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "world.json"
        path.write_text(json.dumps(world))
        if pack == "window":
            done = subprocess.run([str(J.PACKS[pack]["python"]), str(POLICY / "highrise5" / "run_trial5.py"), str(path), "--seed", str(seed)], capture_output=True, text=True, check=True)
            return json.loads(done.stdout)["final_state_sha256"]
        code = (f"import hashlib,json;from packs.inspection import pack as P;w=json.load(open({str(path)!r}));r,m=P.run(w,seed={seed});print('SHA',hashlib.sha256(r['base_q'].tobytes()).hexdigest())")
        done = subprocess.run([str(J.PACKS[pack]["python"]), "-c", code], capture_output=True, text=True, cwd=POLICY, check=True)
        return done.stdout.split("SHA ")[-1].strip()


def inspection_chat(client):
    code, made = client.call("/api/sessions", {"pack": "inspection"})
    stream = client.stream(made["id"])
    world = stream.wait("pose_world", 30)
    check("an inspection session sends its scene on load", world is not None and len(world["solids"]) > 0 and len(world["scenery"]) > 0, f"{len(world['solids'])} solids, {len(world['scenery'])} scenery")
    check("it has no window events", not [e for e in stream.events if e["type"] in ("world", "view", "trial")])
    stream.wait("idle", 30)
    at = len(stream.events)
    t0 = time.monotonic()
    client.call(f"/api/sessions/{made['id']}/message", {"text": MESSAGE})
    trial = stream.wait("pose_trial", 180, at)
    added = stream.wait("pose_world", 5, at)
    check("a message on inspection adds a box, through the pack", added is not None and any(s["object"] == "control_cabinet" for s in added["solids"]), f"{time.monotonic() - t0:.1f} s, with one run")
    check("the chat run gives a verdict and a replay", trial is not None, trial and trial["reason"])
    if trial:
        code, data = client.call(trial["url"], raw=True)
        replay = json.loads(data if data[:2] != b"\x1f\x8b" else gzip.decompress(data))
        check("the chat replay is the pack's format", code == 200 and replay["format"] == "robot-pack-replay/1" and replay["simulated"] is True, f"{len(replay['frames'])} frames")
    stream.wait("idle", 60, at)
    stream.stop = True


def campaign(client, pack, want_min, check_passes):
    code, made = client.call("/api/sessions", {"pack": pack})
    sid = made["id"]
    check(f"{pack}: session stores the pack", code == 201 and client.call(f"/api/sessions/{sid}/state")[1]["pack"] == pack)
    stream = client.stream(sid)
    if pack == "inspection":
        stream.wait("idle", 30)
    at = len(stream.events)
    t0 = time.monotonic()
    client.call(f"/api/sessions/{sid}/action", {"action": "list_scenarios", "value": None})
    listed = stream.wait("scenarios", 600, at)
    list_s = time.monotonic() - t0
    if listed is None:
        check(f"{pack}: a scenario list came", False)
        return None
    print(f"{pack}: {listed['count']} worlds, {listed['to_run']} to run, {listed['held_back']} held back, dropped {listed['dropped']}, rejection {listed['rejection']}, {list_s:.1f} s", flush=True)
    print(f"{pack}: why this count: {listed['count_reason']}", flush=True)
    for g in listed["groups"]:
        print(f"  {g['count']:3d} {g['name']}", flush=True)
    for item in listed["not_tested"]:
        print(f"  not tested ({item['source']}): {item['factor']}", flush=True)
    check(f"{pack}: enough valid worlds", listed["count"] >= want_min, listed["count"])
    check(f"{pack}: every reason says it is a guess", all(w["reason"].startswith("Reasoned guess: ") for w in listed["worlds"]))
    check(f"{pack}: not_tested has the agent's and the code's items", {i["source"] for i in listed["not_tested"]} >= {"agent", "code"})
    expected = 0
    for g in listed["groups"]:
        expected += max(1, g["count"] // 5) if g["count"] >= 3 else 0
    check(f"{pack}: 1 in 5 held back per group", listed["held_back"] == expected, f"{listed['held_back']} of {listed['count']}")
    stream.wait("idle", 30, at)
    at = len(stream.events)
    t1 = time.monotonic()
    code, _ = client.call(f"/api/sessions/{sid}/action", {"action": "run_campaign"})
    check(f"{pack}: run_campaign starts", code == 202, code)
    done = stream.wait("campaign_done", 1800, at)
    wall = time.monotonic() - t1
    check(f"{pack}: campaign_done came", done is not None)
    if done is None:
        return None
    stream.wait("idle", 30, at)
    gaps = [b[0] - a[0] for a, b in zip(stream.grids, stream.grids[1:])]
    live = [g for _, g in stream.grids if g["running"]]
    moved = {r["index"] for g in live for r in g["rows"] if r["status"] == "running" and r["t"] is not None}
    print(f"{pack}: counts {done['counts']}, {wall:.1f} s on {done['max_procs']} procs, {done['label']}", flush=True)
    check(f"{pack}: grid comes at about 1 Hz", gaps and sorted(gaps)[len(gaps) // 2] < 1.5, f"{len(gaps)} gaps, median {sorted(gaps)[len(gaps) // 2]:.2f} s" if gaps else "")
    check(f"{pack}: grid lines carry no id and stay out of the stored list", stream.ids_on_grids == 0 and not [e for e in stream.events if e["type"] == "grid"])
    check(f"{pack}: live positions reached the grid", len(moved) >= min(5, listed["to_run"]), f"{len(moved)} worlds")
    final = stream.grids[-1][1]
    row = final["rows"][0]
    check(f"{pack}: a row has every contract field", set(row) >= {"index", "name", "group", "reason", "status", "held_back", "t", "t_limit", "x", "y", "outline", "verdict", "verdict_reason"})
    check(f"{pack}: nothing stayed queued or running", not final["counts"]["queued"] and not final["counts"]["running"] and not final["running"])
    check(f"{pack}: every world that ran has a reason", all(r["verdict_reason"] for r in final["rows"]))
    check(f"{pack}: held-back worlds did not run", all(r["status"] == "held" and r["t"] is None for r in final["rows"] if r["held_back"]))
    if check_passes:
        check(f"{pack}: real failures and passes both happen", done["counts"]["passed"] > 0 and done["counts"]["failed"] > 0, done["counts"])
    base = f"/api/sessions/{sid}/campaigns/{done['campaign']}"
    check(f"{pack}: the grid route answers", client.call(base + "/grid")[1]["campaign"] == done["campaign"])
    bad = [r for r in final["rows"] if r["status"] == "failed"]
    good = [r for r in final["rows"] if r["status"] == "passed"]
    for row in bad[:1] + good[:1]:
        code, detail = client.call(f"{base}/worlds/{row['index']}")
        print(f"{pack}: {row['status']} world {row['index']} {row['name']}: {detail['verdict_reason']} numbers {list(detail['numbers'])[:4]} events {detail['events'][:2]} code {detail['code']} log {detail['log'][-1:]}", flush=True)
        check(f"{pack}: world detail for a {row['status']} world", code == 200 and detail["numbers"] and detail["log"] and detail["world"] and detail["label"] and detail["replay"])
    if bad:
        t2 = time.monotonic()
        code, replay = client.call(f"{base}/worlds/{bad[0]['index']}/replay", timeout=320)
        check(f"{pack}: replay route", code == 200 and replay["kind"] == ("trial" if pack == "window" else "poses"), f"{replay}, {time.monotonic() - t2:.1f} s")
        if code == 200 and replay["kind"] == "trial":
            code, manifest = client.call(f"/api/sessions/{sid}/trials/{replay['tid']}/manifest.json", raw=True)
            check(f"{pack}: the trial player's files are served", code == 200 and json.loads(manifest)["replay_match"] is True)
        elif code == 200:
            code, data = client.call(replay["url"], raw=True)
            poses = json.loads(data if data[:2] != b"\x1f\x8b" else gzip.decompress(data))
            check(f"{pack}: the poses file plays", code == 200 and poses["format"] == "robot-pack-replay/1" and poses["simulated"] is True and len(poses["frames"]) > 0, f"{len(poses['frames'])} frames")
    code, plan = client.call(base + "/scenarios")
    folder = next((POLICY / "runs" / "server").glob(f"{sid}/campaigns/{done['campaign']}"))
    stored = json.loads((folder / "scenarios.json").read_text())
    sha = "final_state_sha256" if pack == "window" else "record_sha256"
    same = []
    for row in (bad[:2] + good[:1]):
        world = stored["worlds"][row["index"]]
        got = json.loads((folder / f"w{row['index']:03d}" / "job_result.json").read_text())[sha]
        same.append(direct_result(pack, world["world"], world["seed"]) == got)
    check(f"{pack}: the same seed gives the same result as a direct run", same and all(same), same)
    stream.stop = True
    return {"counts": done["counts"], "wall_s": wall, "list_s": list_s, "worlds": listed["count"], "ran": listed["to_run"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", choices=sorted(J.PACKS), action="append")
    ap.add_argument("--limit", type=int, help="fewer worlds, from each group in turn")
    ap.add_argument("--live", action="store_true", help="real AI scenario lists. One call per pack.")
    ap.add_argument("--faults-only", action="store_true")
    ap.add_argument("--recorded", default=str(HERE / "fixtures"))
    ap.add_argument("--save-replies", help="with --live: keep each AI reply as scenarios_<pack>.json in this folder")
    a = ap.parse_args()
    fake_children()
    if a.faults_only:
        return finish()
    with __import__("socket").socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    argv = [str(J.PACKS["window"]["python"]), str(HERE / "server.py"), "--port", str(port), *([] if a.live else ["--recorded", a.recorded]), *(["--scenario-limit", str(a.limit)] if a.limit else [])]
    server = subprocess.Popen(argv)
    client = Client(port)
    try:
        for _ in range(60):
            try:
                client.call("/api/health", timeout=2)
                break
            except OSError:
                time.sleep(0.25)
        code, packs = client.call("/api/packs")
        check("/api/packs lists two packs, and import says not yet", code == 200 and [p["name"] for p in packs["packs"]] == ["window", "inspection"] and packs["import"]["available"] is False, [(p["name"], p["max_procs"]) for p in packs["packs"]])
        check("an unknown pack is refused", client.call("/api/sessions", {"pack": "rover"})[0] == 400)
        code, old = client.call("/api/sessions", {})
        check("no pack stays the old path", code == 201 and old["pack"] is None and client.call(f"/api/sessions/{old['id']}/state")[1]["engine"] == "old")
        code, v5 = client.call("/api/sessions", {"engine": "v5"})
        check("engine v5 means the window pack", code == 201 and v5["pack"] == "window")
        if not a.live:
            inspection_chat(client)
        summary = {}
        for pack in a.pack or ["window", "inspection"]:
            summary[pack] = campaign(client, pack, 1 if a.limit else 40, not a.live or pack == "window")
            if a.save_replies and summary[pack]:
                newest = max((POLICY / "runs" / "server").glob("*/campaigns/*/scenarios.json"), key=lambda p: p.stat().st_mtime)
                reply = json.loads(newest.read_text())["llm_reply"]
                (Path(a.save_replies) / f"scenarios_{pack}.json").write_text(json.dumps(reply, indent=1))
        print(json.dumps(summary, indent=1), flush=True)
    finally:
        server.terminate()
        server.wait(10)
    return finish()


def finish():
    print("ALL PASS" if not failed else f"FAILED: {failed}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
