"""Fix bounties: a company posts a failure group from a real campaign, and an engineer submits a controller change.

Folder policy/runs/board/<id>/: pack.json (public), hidden.json 0600, campaign/ 0700, ledger.json, fixes/<n>/.
hidden.json and campaign/ hold the held-back and passed-before worlds. No route serves them: routes read pack.json through view() and fix rows through fix_view().
LOCAL LEDGER. NOT ON CHAIN. Amounts are test units. Results are simulated. World ID is not connected, so a tester is only a name.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "crashlab"))
import board_store as B
import fix as F
import gate as G

POLICY = HERE.parent
SERVER_RUNS = POLICY / "runs" / "server"
PYTHON = POLICY / ".venv" / "bin" / "python"
RUNNER = HERE / "board_fix_run.py"
SCHEMA = "crashlab.board.fix.v1"
MAX_PUBLIC_REPLAYS = 6
SESSION = re.compile(r"[0-9a-f]{32}")
CAMPAIGN = re.compile(r"c[0-9]{1,6}")
GROUP = re.compile(r"[a-z_]{1,40}")
SIM_LABEL = "Simulated with hand-built physics. Not checked against real hardware. A pass says nothing about a real robot."
SANDBOX_LABEL = "sandbox-exec shares the kernel with this machine. It is one layer, not a VM."
FROZEN_FILES = {
    "window": ["highrise5/judge5.py", "highrise5/sim5.py", "highrise5/compile5.py", "highrise5/engine5.py", "highrise5/parts5.py", "highrise5/geoms5.py", "highrise5/scene5.py", "highrise5/world5.py", "highrise5/run_trial5.py"],
    "inspection": ["packs/inspection/judge.py", "packs/inspection/sim.py", "packs/inspection/world.py", "packs/inspection/model.py", "packs/inspection/plant.py", "packs/inspection/controller.py"],
}
ROBOT_NAME = {"window": "Window cleaning robot", "inspection": "Inspection robot"}
SCOPE = {"window": "You can edit the whole of controller5.py under the code rules. The judge and the worlds stay frozen. The board replays your recorded actions outside the sandbox and judges that replay.",
         "inspection": "You can change only the six RouteFollower number constants. The board runs the frozen robot again outside the sandbox with those numbers, and judges that run."}


def frozen_shas(pack, code_root=POLICY):
    return {name: hashlib.sha256((Path(code_root) / name).read_bytes()).hexdigest() for name in FROZEN_FILES[pack]}


def _read(path):
    return json.loads(Path(path).read_text())


def _campaign(session, cid, runs):
    if not (isinstance(session, str) and SESSION.fullmatch(session) and isinstance(cid, str) and CAMPAIGN.fullmatch(cid)):
        raise B.BoardError("bad_campaign", "The session or campaign name is not valid.")
    folder = Path(runs) / session / "campaigns" / cid
    if not (folder / "grid.json").is_file() or not (folder / "scenarios.json").is_file():
        raise B.BoardError("unknown_campaign", "There is no such finished campaign.")
    return folder


def _fixable_groups(pack, rows):
    groups = {}
    for r in rows:
        v = r.get("verdict")
        if r["held_back"] or r["status"] not in ("failed", "stuck") or not v or v in F.NOT_A_CONTROLLER_FAILURE or (pack == "inspection" and v in F.INSPECTION_CANNOT):
            continue
        groups[v] = groups.get(v, 0) + 1
    return groups


def fixable(root=B.ROOT, runs=SERVER_RUNS):
    """What can be posted: each failure group of each finished campaign. Names and counts only."""
    posted = {tuple(_hidden(p.parent)["source"]) for p in Path(root).glob("*/pack.json")} if Path(root).is_dir() else set()
    out = []
    for grid_path in Path(runs).glob("*/campaigns/*/grid.json"):
        folder = grid_path.parent
        try:
            grid = _read(grid_path)
        except (OSError, ValueError):
            continue
        if grid.get("running") or grid.get("pack") not in FROZEN_FILES or not (folder / "scenarios.json").is_file():
            continue
        session, cid = folder.parent.parent.name, folder.name
        for group, count in _fixable_groups(grid["pack"], grid["rows"]).items():
            out.append({"session": session, "cid": cid, "group": group, "pack": grid["pack"], "robot": ROBOT_NAME[grid["pack"]], "failed": count, "at": grid_path.stat().st_mtime,
                        "worlds": len(grid["rows"]), "posted": (session, cid, group) in posted, "ref": f"{session}/{cid}/{group}"})
    return sorted(out, key=lambda r: (-r["at"], r["session"], r["group"]))


def _hidden(folder):
    return _read(folder / "hidden.json")


RUN_FILES = ("judge5.py", "sim5.py", "run_trial5.py")  # These decide a run's result by themselves, so they must match exactly. So must the controller.
PHYSICS_CHECK_S = 120
REPLAY_PROCS = 6
STORED_RUN_FILES = ("actions.jsonl.gz", "result.json")  # What a replay reads. The bounty keeps its own copy, so a payout can replay the runs it rests on.
PHYSICS_CHECK = """
import json, sys
sys.path.insert(0, sys.argv[1])
import compile5 as C, world5 as W
print("same" if all(C.physics_hash(W.validate(w["world"])) == w["physics"] for w in json.load(sys.stdin)) else "changed")
"""


def _is_stale(folder, worlds, pack, base_sha, code_root=POLICY, tick=None):
    """A stored run from other code or other physics says nothing about the code frozen now. It covers every world the bounty uses, public and hidden. Anything missing counts as stale.
    The files that build a world may gain new kinds of object, so those are judged by each world's compiled physics hash, and every stored action log must replay on the code here, since sim code in those files reaches no hash.
    An inspection run has no action log, so its stored run must name the exact bytes of every frozen file."""
    try:
        now = frozen_shas(pack, code_root)
    except OSError:
        return True
    if not worlds:
        return True
    if os.environ.get("CRASHLAB_HOSTED") == "1" and pack == "window":
        return not _same_bytes_as_recorded(folder, now, base_sha)
    checks, replays = [], []
    for w in worlds:
        if not w.get("hash"):
            return True
        checks.append({"world": w["world"], "physics": w["hash"]})
        if w["held_back"]:  # A held-back world has no stored run. The proof runs it on both sides.
            continue
        run = Path(F.latest_run5(folder, w["index"]))
        if pack == "inspection":
            job = _read(run / "job_result.json") if (run / "job_result.json").is_file() else {}
            code = job.get("code_sha256") or {}
            if any(code.get(name) != sha for name, sha in now.items()) or (job.get("controller_sha256") or code.get("packs/inspection/controller.py")) != base_sha:
                return True
            continue
        if not (run / "run" / "result.json").is_file():
            return True
        stored = _read(run / "run" / "result.json")
        code = stored.get("code_sha256") or {}
        if stored.get("physics_sha256") != w["hash"] or any(code.get(name) != now.get(f"highrise5/{name}") for name in RUN_FILES):
            return True
        job = _read(run / "job_result.json") if (run / "job_result.json").is_file() else {}
        if (job.get("controller_sha256") or code.get("controller5.py")) != base_sha:
            return True
        replays.append((w, run, job))
    if pack == "inspection":
        return False
    return not (_same_physics(checks, Path(code_root) / "highrise5") and _replays_same(replays, code_root, tick))


def _same_physics(worlds, code):
    """In its own process, so it reads the code on disk now. Any error counts as changed."""
    try:
        done = subprocess.run([str(PYTHON), "-c", PHYSICS_CHECK, str(code)], input=json.dumps(worlds), capture_output=True, text=True, timeout=PHYSICS_CHECK_S)
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0 and done.stdout.strip() == "same"


def _same_bytes_as_recorded(folder, now, base_sha):
    """The hosted site runs no simulation, so it replays nothing. A recorded campaign counts only if its worlds, its controller and every frozen file are the exact bytes of the recorded real run."""
    try:
        key = _read(POLICY / "runs" / "demo" / "window" / "stored_proof.json")["key"]
        plan = hashlib.sha256((Path(folder) / "scenarios.json").read_bytes()).hexdigest()
    except (OSError, ValueError, KeyError):
        return False
    return plan == key["plan"] and base_sha == key["controller"] and now == key["frozen"]


def _replays_same(replays, code_root, tick=None):
    """Each stored action log through the judge outside the sandbox, on the code on disk now. It must give the stored states, result and verdict. No reply counts as changed."""
    def same(entry):
        world, run, job = entry
        judged = F.rejudge5("window", None, world["world"], world["seed"], run.resolve(), code_root)
        if tick:
            tick()
        return bool(judged) and judged.get("matches") is True and judged["verdict"] == job.get("verdict") and judged["passed"] == job.get("passed")
    with ThreadPoolExecutor(REPLAY_PROCS) as pool:
        return all(pool.map(same, replays))


def _public_world(world, row, result):
    return {"index": world["index"], "name": world["name"], "scenario": world["group"], "changes": world["changes"], "seed": world["seed"], "world": world["world"],
            "verdict": row["verdict"], "status": row["status"], "reason": row["verdict_reason"], "numbers": result.get("numbers", {}), "events": result.get("events", [])}


def _export_public(pack, campaign, index, out):
    """The recorded run of one public world, for the engineer. export5 refuses a run that no longer replays."""
    run = F.latest_run5(campaign, index) / "run"
    if pack != "window" or not run.is_dir():
        return False
    done = subprocess.run([str(F.PY), str(F.HIGHRISE5 / "export5.py"), str(run), f"w{index}", f"World {index}", "--out", str(out)], capture_output=True, timeout=120)
    return done.returncode == 0


CHECK_DIR = ".postcheck"  # In the campaign folder, outside every wNNN. A sandboxed run writes only inside its own run folder, and no route writes here, so only this server can.
CHECK_SCHEMA = 1
CHECK_CODE = ("highrise5/*.py", "packs/__init__.py", "packs/window/*.py", "packs/inspection/*.py", "bounty/rejudge.py", "server/pack_job.py")  # What a replay or an export imports.
STALE_REASON = "A stored run no longer matches or no longer replays. The sim, the judge, this controller or a world's physics changed after it ran. Run those worlds again before you post it."
WARM_LOOK_S = 2
WARM_SETTLE_S = 1  # The lab writes other files just after the grid. A check that starts sooner would see them change, and save nothing.
CHECKS = {}
CHECKS_LOCK = threading.Lock()
CHECK_TURN = threading.Lock()  # One check at a time, since each one fills every core.


def _postable(session, cid, group, runs):
    """Every refusal a post can give before the stale rule, and what the rule and the post then need."""
    if not (isinstance(group, str) and GROUP.fullmatch(group)):
        raise B.BoardError("bad_group", "The failure group is not valid.")
    source = _campaign(session, cid, runs)
    grid, plan = _read(source / "grid.json"), _read(source / "scenarios.json")
    pack = grid["pack"]
    if grid.get("running") or pack not in FROZEN_FILES:
        raise B.BoardError("bad_campaign", "This campaign is still running, or its robot has no fix bounty.")
    if group not in _fixable_groups(pack, grid["rows"]):
        raise B.BoardError("not_fixable", "This campaign has no world with this failure that a controller change could fix.")
    rows = {r["index"]: r for r in grid["rows"]}
    target = [w for w in plan["worlds"] if not w["held_back"] and rows[w["index"]]["verdict"] == group and rows[w["index"]]["status"] in ("failed", "stuck")]
    held_back = [w for w in plan["worlds"] if w["held_back"]]
    if (source / "zg_evidence.json").is_file():
        raise B.BoardError("campaign_published", "This campaign's passed worlds are already public on 0G Storage, so they cannot stay hidden in a bounty. Post the bounty first, then upload.")
    if not held_back:
        raise B.BoardError("no_hidden_worlds", "This campaign has no held-back worlds, so a fix could not be proved on worlds it never saw.")
    session_copy = source.parent.parent / "code" / F.PACK5[pack]["file"].name
    base = session_copy if session_copy.is_file() else F.PACK5[pack]["file"]
    base_text = base.read_text()
    return SimpleNamespace(source=source, plan=plan, pack=pack, rows=rows, target=target, held_back=held_back, base=base, base_text=base_text, base_sha=hashlib.sha256(base_text.encode()).hexdigest())


def _file_sha(path):
    """A run folder is hostile data. It may hold a pipe or a link, so this opens without blocking and reads only a regular file."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return "unreadable"
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return "not_a_file"
        digest = hashlib.sha256()
        while chunk := f.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_shas(folder):
    out = {}
    for base, dirs, files in os.walk(folder):
        for name in dirs + files:
            out[os.path.relpath(os.path.join(base, name), folder)] = _file_sha(os.path.join(base, name))
    return out


def _check_key(p, code_root=POLICY):
    """Over everything the stale rule and the exports read, plus the code of the rule itself. Any change gives another key, so a good result counts only for these exact bytes."""
    code_root = Path(code_root)
    python = Path(F.PACK5[p.pack]["python"])
    runs = {}
    for w in p.plan["worlds"]:
        if not w["held_back"]:
            run = F.latest_run5(p.source, w["index"])
            runs[w["index"]] = {"folder": os.path.relpath(run, p.source), "job": _file_sha(run / "job_result.json"), "run": _tree_shas(run / "run")}
    parts = {"schema": CHECK_SCHEMA, "pack": p.pack, "code_root": str(code_root), "controller": p.base_sha, "plan": _file_sha(p.source / "scenarios.json"), "grid": _file_sha(p.source / "grid.json"), "runs": runs,
             "frozen": {name: _file_sha(code_root / name) for name in FROZEN_FILES[p.pack]}, "code": {str(f.relative_to(code_root)): _file_sha(f) for pattern in CHECK_CODE for f in sorted(code_root.glob(pattern))},
             "rule": [_file_sha(__file__), _file_sha(F.__file__)], "python": [os.path.realpath(python), sorted(f.name for f in python.parent.parent.glob("lib/python*/site-packages/*.dist-info"))]}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _cached_good(source, key):
    try:
        return _read(source / CHECK_DIR / key / "good.json")["key"] == key
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _store_good(source, key):
    """Only a check that passed reaches this. Older results go, since their key can never match again unless the same bytes come back, and then a new check costs only time."""
    folder = source / CHECK_DIR
    folder.mkdir(mode=0o700, exist_ok=True)
    for old in folder.iterdir():
        if old.name != key:
            shutil.rmtree(old, ignore_errors=True)
    (folder / key).mkdir(mode=0o700, exist_ok=True)
    B.write_json(folder / key / "good.json", {"key": key, "checked_at": time.time()})


def _store_exports(job, p):
    folder = p.source / CHECK_DIR / job.key / "public"
    wanted = [w["index"] for w in p.target[:MAX_PUBLIC_REPLAYS] if not (folder / f"w{w['index']:03d}").is_dir()] if p.pack == "window" else []
    job.phase, job.done, job.total = "export", 0, len(wanted)

    def one(index):
        tmp = folder / f".new-w{index:03d}"
        shutil.rmtree(tmp, ignore_errors=True)
        if _export_public(p.pack, p.source, index, tmp):
            os.rename(tmp, folder / f"w{index:03d}")
        shutil.rmtree(tmp, ignore_errors=True)
        job.tick()
    folder.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(MAX_PUBLIC_REPLAYS) as pool:
        list(pool.map(one, wanted))


class _Check:
    def __init__(self, key, total):
        self.key, self.total, self.done, self.state, self.phase, self.good, self.error = key, total, 0, "waiting", "replay", False, None
        self.finished = threading.Event()
        self.count = threading.Lock()

    def tick(self):
        with self.count:
            self.done += 1

    def view(self):
        return {"state": self.state, "phase": self.phase, "done": self.done, "total": self.total}


def _run_check(job, p, code_root):
    try:
        with CHECK_TURN:
            job.state = "running"
            if not _cached_good(p.source, job.key):
                if _is_stale(p.source, p.plan["worlds"], p.pack, p.base_sha, code_root, job.tick) or _check_key(p, code_root) != job.key:  # A file that changed during the check was not the file it read.
                    job.state = "stale"
                    return
                try:
                    _store_good(p.source, job.key)
                except OSError:  # No cache, so the next post checks in full. This one passed.
                    pass
            job.good = True
            try:
                _store_exports(job, p)
            except OSError:  # The post makes any export that is not here.
                pass
            job.state = "good"
    except Exception as e:  # noqa: BLE001 The post that waits on this raises it, as if the post had run the check itself.
        job.error, job.state = e, "failed"
    finally:
        job.finished.set()


def _begin_check(p, code_root):
    """The check for these exact bytes: the one still running, or a new one. A new one that finds a good result on disk only makes the missing exports. Returns the job, and whether this call began it."""
    key = _check_key(p, code_root)
    with CHECKS_LOCK:
        job = CHECKS.get((str(p.source), str(code_root)))
        if job and job.key == key and not job.finished.is_set():
            return job, False
        job = CHECKS[(str(p.source), str(code_root))] = _Check(key, sum(not w["held_back"] for w in p.plan["worlds"]) if p.pack == "window" else 0)
    threading.Thread(target=_run_check, args=(job, p, code_root), daemon=True).start()
    return job, True


def start_check(session, cid, group, runs=SERVER_RUNS, code_root=POLICY):
    """Begins the check in the background when a company opens the post dialog, so the press finds it done."""
    return _begin_check(_postable(session, cid, group, runs), code_root)[0].view()


def check_view(session, cid, runs=SERVER_RUNS, code_root=POLICY):
    """Counts only, for the post button."""
    job = CHECKS.get((str(_campaign(session, cid, runs)), str(code_root)))
    return job.view() if job else {"state": "idle", "phase": "replay", "done": 0, "total": 0}


def warm_campaign(session, cid, runs=SERVER_RUNS, code_root=POLICY):
    """The check and every group's exports, one group at a time, so the first press finds them saved. A refusal here saves nothing, and the post still decides for itself."""
    try:
        grid = _read(_campaign(session, cid, runs) / "grid.json")
        for group in _fixable_groups(grid["pack"], grid["rows"]):
            job = _begin_check(_postable(session, cid, group, runs), code_root)[0]
            job.finished.wait()
            if not job.good:
                return
    except (B.BoardError, OSError, ValueError, KeyError, TypeError):
        return


def warm_finished(since, seen, runs=SERVER_RUNS, code_root=POLICY):
    """One look for campaigns that finished after this board started. The lab is another process, so the board reads the time on each grid.json. Another write to a grid counts as new."""
    for path in Path(runs).glob("*/campaigns/*/grid.json"):
        try:
            changed = path.stat().st_mtime
            if changed <= since or seen.get(path) == changed or time.time() - changed < WARM_SETTLE_S or _read(path).get("running"):
                continue
        except (OSError, ValueError, AttributeError):
            continue
        seen[path] = changed
        warm_campaign(path.parent.parent.parent.name, path.parent.name, runs, code_root)


def watch_campaigns(session=None, cid=None):
    """Runs for the life of the board. With a session, it warms that stored campaign first, so a recorded demo is ready when the page opens."""
    since, seen = time.time(), {}
    if session:
        warm_campaign(session, cid)
    while True:
        warm_finished(since, seen)
        time.sleep(WARM_LOOK_S)


def _checked(p, code_root):
    """The stale rule for one post. Only a check this call began decides, so a post that joined one still running asks again: a pass then comes from disk, and a failure runs in full. Returns the key."""
    while True:
        job, mine = _begin_check(p, code_root)
        job.finished.wait()
        if mine:
            break
    if job.error:
        raise job.error
    if not job.good:
        raise B.BoardError("campaign_stale", STALE_REASON)
    return job.key


def _public_replay(pack, source, key, index, out):
    """The export the check kept for this key, or a new one as a last resort."""
    kept = source / CHECK_DIR / key / "public" / f"w{index:03d}"
    if kept.is_dir():
        try:
            shutil.copytree(kept, out)
            return True
        except OSError:
            shutil.rmtree(out, ignore_errors=True)
    return _export_public(pack, source, index, out)


def post(session, cid, group, title, company, pay, window=B.ledger_module.MIN_DISPUTE_WINDOW, posted_by="company", root=B.ROOT, runs=SERVER_RUNS, code_root=POLICY):
    """Makes one fix bounty from one failure group. cap = pay, so one fix can win. Returns the public view."""
    title, company = B._text(title, "The title", 120), B._text(company, "The company", 80)
    pay, window = B._amount(pay, "The pay"), B._amount(window, "The dispute window", B.MAX_WINDOW_S)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    p = _postable(session, cid, group, runs)
    source, plan, pack, rows, target, held_back, base, base_text = p.source, p.plan, p.pack, p.rows, p.target, p.held_back, p.base, p.base_text
    passed = [w for w in plan["worlds"] if not w["held_back"] and rows[w["index"]]["status"] in ("passed", "held")]
    other = [w for w in plan["worlds"] if not w["held_back"] and w not in target and w not in passed]
    key = _checked(p, code_root)

    with B.locked(root / ".lock"):
        for p in root.glob("*/hidden.json"):
            if _hidden(p.parent)["source"] == [session, cid, group]:
                raise B.BoardError("already_posted", f"Bounty {p.parent.name} already holds this failure group.")
        bounty_id = 1 + max((int(p.name) for p in root.iterdir() if p.name.isdigit()), default=0)
        tmp = root / f".newfix-{bounty_id}"
        shutil.rmtree(tmp, ignore_errors=True)
        (tmp / "fixes").mkdir(parents=True)
        try:
            campaign = tmp / "campaign"
            campaign.mkdir(mode=0o700)
            shutil.copyfile(source / "scenarios.json", campaign / "scenarios.json")
            shutil.copyfile(source / "grid.json", campaign / "grid.json")
            for w in plan["worlds"]:
                stored = F.latest_run5(source, w["index"]) / "job_result.json"
                if not w["held_back"] and stored.is_file():
                    (campaign / f"w{w['index']:03d}").mkdir()
                    shutil.copyfile(stored, campaign / f"w{w['index']:03d}" / "job_result.json")
                    if pack == "window":
                        (campaign / f"w{w['index']:03d}" / "run").mkdir()
                        for name in STORED_RUN_FILES:
                            shutil.copyfile(stored.parent / "run" / name, campaign / f"w{w['index']:03d}" / "run" / name)
            (tmp / F.PACK5[pack]["file"].name).write_text(base_text)
            public = []
            with ThreadPoolExecutor(MAX_PUBLIC_REPLAYS) as pool:
                exported = list(pool.map(lambda w: _public_replay(pack, source, key, w["index"], tmp / "public" / f"w{w['index']:03d}"), target[:MAX_PUBLIC_REPLAYS]))
            for n, w in enumerate(target):
                stored = F.latest_run5(source, w["index"]) / "job_result.json"
                entry = _public_world(w, rows[w["index"]], _read(stored) if stored.is_file() else {})
                entry["replay"] = n < MAX_PUBLIC_REPLAYS and exported[n]
                public.append(entry)
            hidden = {"held_back": held_back, "passed_before": passed, "other_failed": other, "plan_sha256": hashlib.sha256((source / "scenarios.json").read_bytes()).hexdigest(), "source": [session, cid, group]}
            fd = os.open(tmp / "hidden.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(hidden, f)
            info = {"schema": SCHEMA, "kind": "fix_failure", "id": bounty_id, "title": title, "company": company, "pack": pack, "robot": ROBOT_NAME[pack], "group": group, "posted_by": posted_by, "posted_at": time.time(),
                    "controller": {"file": base.name, "sha256": hashlib.sha256(base_text.encode()).hexdigest()}, "frozen": frozen_shas(pack, code_root), "public_worlds": public,
                    "hidden_counts": {"held_back": len(held_back), "passed_before": len(passed), "other_failed": len(other)}, "pay": pay, "cap": pay, "window_s": window, "scope": SCOPE[pack], "replay_rejudge": True}
            B.write_json(tmp / "pack.json", info)
            spec_hash = "0x" + G.sha256_hex(G.canonical(info))
            book = B.ledger_module.Ledger(tmp / "ledger.json")
            book.fund(spec_hash, pay, pay, window, B.COMPANY, B.RESOLVER, B.ARBITER)
            saved = _read(book.path)
            saved["bounty"]["id"] = bounty_id
            B.write_json(book.path, saved)
        except B.ledger_module.LedgerError as e:
            shutil.rmtree(tmp)
            raise B.BoardError("bad_bounty", f"The ledger refused this bounty: {e}.") from None
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        os.rename(tmp, root / str(bounty_id))
    return view(bounty_id, root)


def folder_of(bounty_id, root=B.ROOT):
    folder = Path(root) / str(bounty_id)
    if not (isinstance(bounty_id, int) and (folder / "pack.json").is_file()):
        raise B.BoardError("unknown_bounty", "There is no fix bounty with this id.")
    return folder


def is_fix(bounty_id, root=B.ROOT):
    return (Path(root) / str(bounty_id) / "pack.json").is_file()


def _rows(folder):
    return [_read(p / "fix.json") for p in sorted((folder / "fixes").iterdir(), key=lambda p: int(p.name))]


def view(bounty_id, root=B.ROOT):
    """The only form of a fix bounty that leaves this machine's disk. It holds no hidden world."""
    folder = folder_of(bounty_id, root)
    with B.locked(folder / ".lock"):
        book = B._ledger(folder)
        rows = _rows(folder)
    info = _read(folder / "pack.json")
    money = book.bounty
    won = next((f for f in book.failures.values() if f["status"] != "Rejected"), None)
    arc = _arc_of(folder)
    status = _arc_status(arc) or (won["status"].lower() if won else "open")
    return {**info, "status": status, "arc": arc, "spec_hash": money["spec_hash"], "per_failure": money["per_failure"], "available": money["available"], "dispute_window_s": money["dispute_window_s"],
            "unit": "test units", "failures": book.failures, "balance": B._balance(money, book.failures, [r for r in rows if r.get("payout")]), "submissions": len(rows), "checking": sum(r["state"] in ("queued", "running", "awaiting_company") for r in rows), "now": time.time(),
            "ledger_label": B.LEDGER_LABEL, "world_id_label": B.WORLD_ID_LABEL, "sim_label": SIM_LABEL, "sandbox_label": SANDBOX_LABEL, "chain_mirror": _mirror_of(folder), "evidence": _evidence_of(folder)}


def _arc_of(folder):
    """What arc_wallet.py saved after it read each receipt from the chain. No file means nothing is funded on chain."""
    path = folder / "arc_funding.json"
    if not path.is_file():
        return None
    return {**_read(path), "fixes": {p.parent.name: _read(p) for p in (folder / "fixes").glob("*/arc_steps.json")}}


def _arc_status(arc):
    """The chain's word for this bounty, once a fix is on chain. Before that the local gate's word stands."""
    states = [row.get("state") for _, row in sorted((arc or {}).get("fixes", {}).items(), key=lambda kv: int(kv[0]))]
    return {"Pending": "pending", "Finalized": "finalized", "Claimed": "claimed", "Rejected": "open"}.get(states[-1]) if states else None


def _mirror_of(folder):
    path = folder / "chain_mirror.json"
    if not path.is_file():
        return None
    saved = _read(path)
    return {k: saved.get(k) for k in ("label", "chain_id", "txs", "tx_links", "fingerprint", "balances_after_claim", "contract", "chain_bounty", "state", "paid", "message", "dispute_ends_at", "pay_base_units")}


def _evidence_of(folder):
    """The root hash of this bounty's public evidence on 0G Storage, if someone uploaded it. policy/crashlab/zg_storage.py writes the file."""
    path = folder / "zg_evidence.json"
    return _read(path) if path.is_file() else None


def list_views(root=B.ROOT):
    root = Path(root)
    if not root.is_dir():
        return []
    return [view(i, root) for i in sorted(int(p.name) for p in root.iterdir() if p.name.isdigit() and (p / "pack.json").is_file())]


COULD_NOT_RUN = "could_not_run"
FREE_STATES = ("interrupted", COULD_NOT_RUN)  # The board failed, not the tester, so these cost no submission.
FIX_KEYS = ("n", "bounty_id", "tester", "source_sha256", "state", "submitted_at", "result", "payout", "wall_s", "used_before", "wallet")


def fix_view(row):
    return {k: row.get(k) for k in FIX_KEYS}


def list_fixes(bounty_id, root=B.ROOT):
    return [fix_view(r) for r in _rows(folder_of(bounty_id, root))]


def get_fix(bounty_id, n, root=B.ROOT):
    path = folder_of(bounty_id, root) / "fixes" / str(n) / "fix.json"
    if not path.is_file():
        raise B.BoardError("unknown_submission", "There is no fix with this number.")
    return {**fix_view(_read(path)), "now": time.time()}


def save_fix(row, root=B.ROOT):
    B.write_json(folder_of(row["bounty_id"], root) / "fixes" / str(row["n"]) / "fix.json", row)


def reserve(bounty_id, tester, source, root=B.ROOT, secret=None):
    """Counts one submission in the bounty's lock, so two requests cannot both take the last place. The source stays on disk at 0600 and is never served.
    Only the hash of secret goes on disk. With no secret, nobody can ever claim this fix."""
    folder = folder_of(bounty_id, root)
    key = B.tester_key(tester)
    if not isinstance(source, str) or not source.strip():
        raise B.BoardError("bad_source", "The source must be the text of one Python file.")
    data = source.encode("utf-8", "replace")
    if len(data) > F.MAX_SOURCE_BYTES:
        raise B.BoardError("source_too_large", f"The source is larger than {F.MAX_SOURCE_BYTES} bytes.")
    sha = hashlib.sha256(data).hexdigest()
    with B.locked(folder / ".lock"):
        rows = _rows(folder)
        book = B._ledger(folder)
        if book.bounty["available"] < book.bounty["per_failure"]:
            raise B.BoardError("cap_reached", "A fix already holds this bounty's pay. If it gets rejected, the bounty opens again.")
        used = sum(r["tester"] == key and r["state"] not in FREE_STATES for r in rows)
        if used >= B.MAX_PER_TESTER:
            raise B.BoardError("tester_cap", f"{key} already used {used} of {B.MAX_PER_TESTER} submissions for this bounty. {B.WORLD_ID_LABEL}, so this cap counts names and not people.")
        if any(r["source_sha256"] == sha and r["state"] not in FREE_STATES for r in rows):
            raise B.BoardError("same_source", "This exact source was already submitted to this bounty, so it gets no new run.")
        n = 1 + max((r["n"] for r in rows), default=0)
        row = {"n": n, "bounty_id": bounty_id, "tester": key, "source_sha256": sha, "state": "queued", "submitted_at": time.time(), "result": None, "payout": None, "used_before": used, "claim_sha256": B.claim_hash(secret) if secret else None}
        (folder / "fixes" / str(n)).mkdir()
        fd = os.open(folder / "fixes" / str(n) / "source.py", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        save_fix(row, root)
    return row


def _settle_budget(info, amount, root, what):
    """A claim on an agent-posted bounty moves the budget's hold to spent. Only this code path does."""
    if info.get("posted_by") == "agent":
        import budget
        budget.spend(info["id"], amount, what, root)


def ledger_step(bounty_id, n, step, tester=None, root=B.ROOT, secret=None):
    """One step on the local ledger, with the contract's rules. No account exists, so anyone who can reach the board can press reject and finalize.
    Claim needs the name and the secret that submit returned once. The claim and the budget settle in one lock: if the budget refuses, the ledger goes back and the claim fails."""
    folder = folder_of(bounty_id, root)
    caller = B.tester_address(B.tester_key(tester)) if step == "claim" else None
    with B.locked(folder / ".lock"):
        path = folder / "fixes" / str(n) / "fix.json"
        if not path.is_file():
            raise B.BoardError("unknown_submission", "There is no fix with this number.")
        row = _read(path)
        fingerprint = (row.get("payout") or {}).get("fingerprint")
        if not fingerprint:
            raise B.BoardError("ledger_refused", "This fix holds nothing on the ledger.")
        if step == "claim":
            B.check_claim_secret(row, secret)
        book = B._ledger(folder)
        before = book.path.read_bytes()
        try:
            {"reject": book.reject, "finalize": book.finalize, "chain_reject": book.reject_from_chain}[step](fingerprint) if step != "claim" else book.claim(fingerprint, caller)
        except B.ledger_module.LedgerError as e:
            raise B.BoardError("ledger_refused", f"The ledger refused this: {e}.") from None
        entry = book.failures[fingerprint]
        if step == "claim":
            try:
                _settle_budget(_read(folder / "pack.json"), entry["amount"], root, f"claim of fix {n}")
            except BaseException:
                book.path.write_bytes(before)
                raise
        row["payout"] = {**row["payout"], **entry}
        save_fix(row, root)
    return row


def fingerprint_of(bounty_id, patched_sha):
    """The local ledger's key. The chain mirror uses keccak256(bountyId, patched sha). Both keep one payout per fix."""
    return "0x" + hashlib.sha256(f"crashlab.board.fix|{bounty_id}|{patched_sha}".encode()).hexdigest()
