"""Boundary search: after a campaign, where between a passing world and a failing world does this robot start to fail? Results are simulated.

For up to MAX_GROUPS failure groups, the user's or the largest, it takes one failed world and varies one operating-limit factor at a time, with all else fixed. It bisects between the start value and the failing value on the same seed, then runs EXTRA_SEEDS more seeds on each side of the result. At most MAX_RUNS_PER_FACTOR runs per factor.
It says what it found in plain words. If the seeds disagree, the start value also fails, or the failure does not come back, it says there is no clean boundary. It assumes one crossing between the two ends, and only the seeds at the result test that.

Command line: boundary.py <pack> <campaign folder> --out DIR [--group VERDICT]... Needs a campaign's scenarios.json and grid.json.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import limits as L
import pack_job
import testing_runs as TR

MAX_GROUPS = 3
MAX_FACTORS = 2
MAX_RUNS_PER_FACTOR = 12
MAX_BISECT = 4
EXTRA_SEEDS = 3
NOTES = {"window": "Simulated with hand-built physics. Not checked against real hardware.", "inspection": "Simulated with hand-built worlds and upstream's walking policy. Not calibrated, and not checked against a real robot."}
VERDICT_WORDS = {"slip_distance": "slip distance", "false_done": "false finish", "time_limit": "time limit", "tether_load": "tether load", "timed_out": "timed out", "off_route": "off route", "coverage": "low coverage", "sim_failed": "sim failed", "sim_diverged": "sim failed", "controller_crashed": "controller crashed"}
FAILED = ("failed", "stuck")


def verdict_words(verdict):
    return VERDICT_WORDS.get(verdict, str(verdict).replace("_", " "))


def pick_groups(rows, wanted=None):
    """The failure groups to search: the user's, or the largest. A run no judge read is not a failure of the robot."""
    counts = Counter(r["verdict"] for r in rows if r["status"] in FAILED and r["verdict"] not in TR.INFRA)
    if wanted:
        return [v for v in wanted if v in counts][:MAX_GROUPS]
    return [v for v, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_GROUPS]]


def moved_factors(pack, base, world):
    """Limit factors this world moved from the start, largest move first."""
    out = []
    for f in L.factors(pack):
        was, now = L.value(pack, f["key"], base), L.value(pack, f["key"], world)
        if was != now:
            out.append((abs(now - was) / (f["allowed"][1] - f["allowed"][0]), f["key"]))
    return [key for _, key in sorted(out, reverse=True)]


def pick_world(pack, plan, rows, base, verdict, index=None):
    """The failed world to start from. The user's if it moved a factor, or else the one in the group that moved the fewest."""
    by_index = {w["index"]: w for w in plan["worlds"]}
    failed = [by_index[r["index"]] for r in rows if r["status"] in FAILED and r["verdict"] == verdict and not by_index[r["index"]]["held_back"]]
    chosen = next((w for w in failed if w["index"] == index and moved_factors(pack, base, w["world"])), None)
    if chosen:
        return chosen
    moving = [w for w in failed if moved_factors(pack, base, w["world"])]
    return min(moving, key=lambda w: (len(moved_factors(pack, base, w["world"])), w["index"])) if moving else None


def _context(pack, base, world, key):
    """What else this world holds different, in words."""
    moved = [f for f in L.factors(pack) if L.value(pack, f["key"], world) != L.value(pack, f["key"], base)]
    parts = [f"{f['words']} {L.plain(L.value(pack, f['key'], world), f)}" for f in moved if f["key"] != key]
    rebuilt = base
    for f in moved:
        rebuilt = L.with_value(pack, f["key"], rebuilt, L.value(pack, f["key"], world))
    if rebuilt != world:
        parts.append("this world's other changes")
    return f"With {' and '.join(parts)}" if parts else "In this world"


def _snap(v, step):
    return round(round(v / step) * step, 6)


def _is_fail(row):
    return row["status"] in FAILED and row["verdict"] not in TR.INFRA


def _no_result(row):
    return row["verdict"] in TR.INFRA


def disagree_words(name, a, b, seed, fails_far, fails_near):
    return f"No clean boundary for {name}. The seeds disagree near {a} to {b}. Seed {seed} failed at {b} and not at {a}. Of {EXTRA_SEEDS} more seeds, {fails_far} failed at {b} and {fails_near} failed at {a}."


class Search:
    """One factor. run(jobs) returns the rows. publish() shows the state so far."""

    def __init__(self, pack, world, seed, key, base, limits, run, validate, publish):
        self.pack, self.world, self.seed, self.key, self.base, self.limits, self.run_many, self.validate, self.publish = pack, world, seed, key, base, limits, run, validate, publish
        self.f = L.factor(pack, key)
        self.state = {"factor": key, "label": self.f["label"], "unit": self.f["unit"], "words": None, "clean": None, "status": "running", "runs": [], "pass_value": None, "fail_value": None}

    def _job(self, value, seed, role):
        checked = self.validate(L.with_value(self.pack, self.key, self.world, value))
        actual = L.value(self.pack, self.key, checked["world"])
        row = {"value": actual, "seed": seed, "role": role, "status": "queued", "verdict": None}
        self.state["runs"].append(row)
        return row, {"world": checked["world"], "seed": seed, "name": f"{self.key}_{actual:g}_{seed}", "outline": checked["outline"], "t_limit": checked["t_limit"]}

    def _go(self, pairs):
        rows, jobs = zip(*pairs)

        def live(states):
            for row, s in zip(rows, states):
                row.update(status=s["status"], verdict=s["verdict"])
            self.publish()
        self.publish()
        results = self.run_many(list(jobs), live)
        for row, r in zip(rows, results):
            row.update(status=r["status"], verdict=r["verdict"], reason=r["reason"])
        self.publish()
        return list(rows)

    def _end(self, clean, words, **fields):
        self.state.update(clean=clean, words=words, status="done", **fields)
        self.publish()
        return self.state

    def run(self):
        f, low_limit, high_limit = self.f, *self.limits[self.key]
        far = L.value(self.pack, self.key, self.world)
        near = min(high_limit, max(low_limit, L.value(self.pack, self.key, self.base)))
        name = f["words"]
        far_row, near_row = self._go([self._job(far, self.seed, "failing end"), self._job(near, self.seed, "passing end")])
        if _no_result(far_row) or _no_result(near_row):
            return self._end(False, f"No clean boundary for {name}: a run at one end stopped before the judge read it.")
        if not _is_fail(far_row):
            return self._end(False, f"No clean boundary for {name}: this world did not fail on the re-run at {L.plain(far_row['value'], f)}, seed {self.seed}. The code may have changed since the campaign.")
        if _is_fail(near_row):
            return self._end(False, f"No clean boundary for {name}: this world still fails at the start value, {L.plain(near_row['value'], f)}, with {verdict_words(near_row['verdict'])}. So {name} alone does not explain this failure.", fail_value=far_row["value"])
        good, bad = near_row, far_row
        for _ in range(MAX_BISECT):
            mid = _snap((good["value"] + bad["value"]) / 2, f["step"])
            if not min(good["value"], bad["value"]) < mid < max(good["value"], bad["value"]):
                break
            row = self._go([self._job(mid, self.seed, "bisect")])[0]
            if _no_result(row):
                return self._end(False, f"No clean boundary for {name}: a run at {L.plain(mid, f)} stopped before the judge read it.")
            if _is_fail(row):
                bad = row
            else:
                good = row
        self.state.update(pass_value=good["value"], fail_value=bad["value"], at_seed=self.seed)
        seeds = [self.seed + 1000 * (i + 1) for i in range(EXTRA_SEEDS)]
        rows = self._go([self._job(bad["value"], s, "seed, failing side") for s in seeds] + [self._job(good["value"], s, "seed, passing side") for s in seeds])
        fail_side, pass_side = rows[:EXTRA_SEEDS], rows[EXTRA_SEEDS:]
        if any(_no_result(r) for r in rows):
            return self._end(False, f"No clean boundary for {name}: a seed run stopped before the judge read it.")
        fails, passes = sum(_is_fail(r) for r in fail_side), sum(not _is_fail(r) for r in pass_side)
        verdicts = Counter(r["verdict"] for r in fail_side + [bad] if _is_fail(r))
        verdict = verdicts.most_common(1)[0][0]
        a, b = L.plain(good["value"]), L.plain(bad["value"], f)
        self.state.update(fail_seeds=[fails, EXTRA_SEEDS], pass_seeds=[passes, EXTRA_SEEDS], verdict=verdict, far_verdict=far_row["verdict"])
        if fails == EXTRA_SEEDS and passes == EXTRA_SEEDS:
            holds = sum(r["status"] == "held" for r in pass_side)
            inside = f"Just on the other side, {passes} of {EXTRA_SEEDS} seeds did not fail" + (f", and {holds} of those held safely." if holds else ".")
            further = f" Further out, at {L.plain(far, f)}, the failure was {verdict_words(far_row['verdict'])}." if far_row["verdict"] != verdict else ""
            return self._end(True, f"{_context(self.pack, self.base, self.world, self.key)}, this robot starts failing between {name} {a} and {b}: {verdict_words(verdict)}. {fails} of {EXTRA_SEEDS} seeds. {inside}{further}")
        return self._end(False, disagree_words(name, a, b, self.seed, fails, EXTRA_SEEDS - passes))


def find(pack, plan, rows, run_many, publish=None, validate=None, base=None, wanted=None, index=None):
    """The whole search. run_many(jobs, live) gives rows. Returns the state, the same object publish() saw."""
    publish = publish or (lambda state: None)
    validate = validate or (lambda world: pack_job.ask(pack, "validate", {"world": world}))
    base = base or plan.get("base_world") or pack_job.ask(pack, "start", {})["world"]
    limits = plan.get("limits") or L.defaults(pack)
    state = {"kind": "boundary", "pack": pack, "running": True, "note": NOTES[pack], "groups": [], "limits_stored": bool(plan.get("limits"))}
    show = lambda: publish(state)
    chosen = pick_groups(rows, wanted)
    if not chosen:
        state.update(running=False, words="There is no failure group to search.")
        show()
        return state
    for verdict in chosen:
        world = pick_world(pack, plan, rows, base, verdict, index)
        group = {"verdict": verdict, "verdict_name": verdict_words(verdict), "count": sum(r["status"] in FAILED and r["verdict"] == verdict for r in rows), "world": world and world["name"], "index": world and world["index"], "seed": world and world["seed"], "searches": [], "words": None}
        state["groups"].append(group)
        if world is None:
            group["words"] = f"No clean boundary for {verdict_words(verdict)}: no world in this group moved a factor in the limits. These worlds changed objects or settings the limits do not name."
            show()
            continue
        for key in moved_factors(pack, base, world["world"])[:MAX_FACTORS]:
            one = Search(pack, world["world"], world["seed"], key, base, limits, run_many, validate, show)
            group["searches"].append(one.state)
            try:
                one.run()
            except RuntimeError as e:  # The pack's validate refused a value: the factor cannot reach it in this world.
                one._end(False, f"No clean boundary for {one.f['words']}: this world cannot take a value in that range. {str(e)[-120:]}")
    state["running"] = False
    show()
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack", choices=sorted(pack_job.PACKS))
    ap.add_argument("campaign")
    ap.add_argument("--out", required=True)
    ap.add_argument("--group", action="append")
    a = ap.parse_args()
    folder, out = Path(a.campaign), Path(a.out)
    plan, grid = json.loads((folder / "scenarios.json").read_text()), json.loads((folder / "grid.json").read_text())
    batches = [0]

    def run_many(jobs, live):
        batches[0] += 1
        return TR.run_jobs(a.pack, jobs, out / f"b{batches[0]:03d}", on_rows=live, **TR.local_kit())
    state = find(a.pack, plan, grid["rows"], run_many, wanted=a.group)
    (out / "boundary.json").write_text(json.dumps(state, indent=1))
    print(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
