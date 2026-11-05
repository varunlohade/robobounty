"""Logs the controller line that decides each step, without changing the controller or run_trial.py.

linetrace.py <campaign dir> [--procs P]    re-runs every trial traced and writes <trial>/lines.json.gz and <campaign>/lines_check.json

sys.settrace watches Controller.step only. It reads self.phase and a few numbers and writes nothing back, and it draws no random
numbers. A trial counts as unchanged only if its action hash chain, which covers every action and every sim state, equals the stored one.
"""
import argparse
import ast
import gzip
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import controller as controller_module
import replay as replay_module
import run_trial
import world as W

MAX_PROCS = 4
COMPARED = ("action_chain_head", "final_state_sha256", "start_state_sha256", "model_sha256", "failure", "passed", "fired",
            "coverage", "time_s", "steps")
REPLAY_SAMPLE = 12


def decision_chain(source):
    """First and last line of the if-chain on self.phase in Controller.step."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "step":
            for stmt in node.body:
                if isinstance(stmt, ast.If) and "self.phase" in ast.unparse(stmt.test):
                    return stmt.lineno, stmt.end_lineno
    raise ValueError("no phase chain in Controller.step")


def traced(module):
    """A Controller subclass that keeps a line log in .log. The parent's step runs unmodified."""
    path = Path(module.__file__)
    first, last = decision_chain(path.read_text())
    step_code = module.Controller.step.__code__

    class Traced(module.Controller):
        def __init__(self, mission):
            super().__init__(mission)
            self.log = {"runs": [], "sets": [], "transitions": []}
            self._set_ids = {}
            self._i = -1

        def _local(self, frame, event, arg):
            if self.phase != self._phase_seen:
                self.log["transitions"].append({"i": self._i, "line": self._line, "from": self._phase_seen, "to": self.phase,
                                                "wind_hold": self.wind_hold, "retreats": self.retreats, "lane": self.lane,
                                                "estimate_pa": round(self.estimate, 1)})
                self._phase_seen = self.phase
            if event == "line":
                self._line = frame.f_lineno
                self._hit.add(frame.f_lineno)
                if first <= frame.f_lineno <= last:
                    self._active = frame.f_lineno
            return self._local

        def _global(self, frame, event, arg):
            return self._local if frame.f_code is step_code else None

        def step(self, o):
            self._i += 1
            self._phase_seen, self._line, self._active, self._hit = self.phase, None, None, set()
            sys.settrace(self._global)
            try:
                action = module.Controller.step(self, o)
            finally:
                sys.settrace(None)
            key = tuple(sorted(self._hit))
            if key not in self._set_ids:
                self._set_ids[key] = len(self.log["sets"])
                self.log["sets"].append(list(key))
            row = [self.phase, self._active, self._set_ids[key]]
            runs = self.log["runs"]
            if not runs or runs[-1][1:] != row:
                runs.append([self._i, *row])
            return action
    return Traced


def run_traced(world, seed, module=controller_module):
    """Returns (result, log). The controller class holding the log is caught as it is built."""
    made = []
    cls = traced(module)

    def build(mission):
        made.append(cls(mission))
        return made[-1]
    saved = run_trial.controller_module
    run_trial.controller_module = SimpleNamespace(Controller=build)
    try:
        result = run_trial.run(world, seed)
    finally:
        run_trial.controller_module = saved
    source = Path(module.__file__).read_bytes()
    log = {"schema": "crashlab.lines.v1", "file": f"policy/highrise/{Path(module.__file__).name}",
           "code_sha256": hashlib.sha256(source).hexdigest(), "hz": 20, "run_columns": ["start_i", "phase", "active_line", "set_index"],
           "decision_chain": decision_chain(source.decode()), **made[-1].log}
    return result, log


def trace_one(run_dir):
    run_dir = Path(run_dir)
    stored = json.loads((run_dir / "result.json").read_text())
    t0 = time.time()
    result, log = run_traced(W.load(run_dir / "world.json"), stored["seed"])
    wall = time.time() - t0
    differs = [k for k in COMPARED if result[k] != stored[k]]
    with gzip.GzipFile(run_dir / "lines.json.gz", "wb", mtime=0) as f:
        f.write(json.dumps(log, separators=(",", ":")).encode())
    return {"trial": run_dir.name, "same": not differs, "differs": differs, "steps": result["steps"], "wall_s": round(wall, 2),
            "untraced_wall_s": stored["wall_s"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--procs", type=int, default=MAX_PROCS)
    a = ap.parse_args()
    campaign = Path(a.campaign)
    dirs = sorted(str(p.parent) for p in campaign.glob("*/result.json"))
    with mp.Pool(min(a.procs, MAX_PROCS)) as pool:
        rows = pool.map(trace_one, dirs, chunksize=4)
        sample = dirs[:: max(1, len(dirs) // REPLAY_SAMPLE)][:REPLAY_SAMPLE]
        replays = pool.map(replay_module.replay, sample)
    stored_code = {json.loads((Path(d) / "result.json").read_text())["code_sha256"]["controller.py"] for d in dirs}
    report = {"trials": len(rows), "same_chain_and_result": sum(r["same"] for r in rows), "differs": [r for r in rows if not r["same"]],
              "replayed_from_stored_actions": len(replays), "replay_match": sum(bool(r["match"]) for r in replays),
              "controller_sha256_now": hashlib.sha256((HERE / "controller.py").read_bytes()).hexdigest(),
              "controller_sha256_stored": sorted(stored_code),
              "traced_wall_s": round(sum(r["wall_s"] for r in rows), 1), "untraced_wall_s": round(sum(r["untraced_wall_s"] for r in rows), 1)}
    (campaign / "lines_check.json").write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(report, indent=1))
    ok = report["same_chain_and_result"] == report["trials"] and report["replay_match"] == report["replayed_from_stored_actions"] \
        and report["controller_sha256_stored"] == [report["controller_sha256_now"]]
    print("UNCHANGED" if ok else "CHANGED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
