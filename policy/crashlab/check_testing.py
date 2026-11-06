"""Checks operating limits, the boundary search and the regression suite on both robots. No AI call: it reads stored replies and the stored batches in policy/runs/demo.

.venv/bin/python crashlab/check_testing.py          stored data and a scripted runner, under a minute.
.venv/bin/python crashlab/check_testing.py --real   also real sim runs on both robots: real boundaries, each checked by direct runs on each side, and a real suite re-run.
--save-demo copies the real results to policy/runs/demo/<pack>, for the recorded server. Results are simulated.
"""
import argparse
import copy
import gzip
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent
sys.path[:0] = [str(HERE), str(POLICY / "server"), str(POLICY / "bounty")]
import boundary as B
import limits as L
import pack_job
import regressions as REG
import scenarios_pack as SP
import testing_runs as TR

PACKS = ("window", "inspection")
failed = [0]


def check(name, ok, detail=""):
    failed[0] += not ok
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""), flush=True)


def stored(pack):
    folder = POLICY / "runs" / "demo" / pack
    with gzip.open(folder / "scenarios.json.gz", "rt") as f:
        plan = json.load(f)
    with gzip.open(folder / "timeline.json.gz", "rt") as f:
        return plan, json.load(f)[-1]


def validate_for(pack):
    return lambda world: pack_job.ask(pack, "validate", {"world": world})


def check_limits(pack, tmp):
    print(f"--- limits, {pack}")
    plan, grid = stored(pack)
    start = pack_job.ask(pack, "start", {})["world"]
    d = L.defaults(pack)
    check("each factor's default sits inside what the physics allows", all(f["allowed"][0] <= f["default"][0] < f["default"][1] <= f["allowed"][1] for f in L.factors(pack)))
    check("the start world is inside the default limits", not L.outside(pack, start, d))
    wanted = {"window": {"wind", "gust", "wetness", "dust", "temperature", "suction", "leak"}, "inspection": {"friction", "obstacle", "step", "payload"}}[pack]
    check("the factors are the ones asked for", {f["key"] for f in L.factors(pack)} == wanted)
    key = L.factors(pack)[0]["key"]
    lo, hi = L.factor(pack, key)["allowed"]
    good = L.set_limits(pack, d, {"factor": key, "low": lo, "high": hi})
    check("set_limits takes a valid range", good["result"] == "ok" and good["limits"][key] == [lo, hi])
    for args, code in (({"factor": "nonsense", "low": 0, "high": 1}, "unknown_factor"), ({"factor": key, "low": hi, "high": lo}, "low_above_high"), ({"factor": key, "low": lo - 100, "high": hi}, "out_of_range"), ({"factor": key, "low": "a", "high": hi}, "bad_args"),
                       ({"factor": key, "low": float("nan"), "high": hi}, "bad_args"), ({"factor": key}, "bad_args"), ("wind 5", "bad_args")):
        out = L.set_limits(pack, d, args)
        check(f"set_limits refuses {str(args)[:44]}", out["result"] == f"cannot_set:{code}" and out["limits"] is d, out["result"])
    import testing_lab as TL
    word, other = ("wind", "payload") if pack == "window" else ("payload", "wind")
    for said, want in ((f"set the {word} limit to 0 to 12", (word, 0.0, 12.0)), (f"{word} limit up to 9", None), (f"{word} limit between 1 and 9", (word, 1.0, 9.0))):
        calls = TL.parse_limits(pack, said, d)
        check(f"the chat parser reads: {said}", len(calls) == 1 and (want is None or (calls[0]["args"]["factor"], calls[0]["args"]["low"], calls[0]["args"]["high"]) == want) and calls[0]["args"]["high"] in (12.0, 9.0), json.dumps(calls))
    check("the parser reads two factors in one message", len(TL.parse_limits(pack, f"{L.factors(pack)[0]['words']} limit 0 to 9 and {L.factors(pack)[1]['words']} limit 0 to 0.2", d)) == 2)
    check("a factor of the other robot makes no call", not TL.parse_limits(pack, f"{other} limit 0 to 9", d) or pack == "inspection")
    check("a chat about the limits goes to set_limits", TL.asks_limits("what are the limits") and TL.asks_limits(f"{word} limit 0 to 9"))
    check("a route's time limit stays a world edit", not TL.asks_limits("set the time limit to 60 s"))
    check("a pack with no factors has no limits", L.defaults("no_such_pack") == {} and L.factors("no_such_pack") == [])
    row = L.catalog_row(pack)
    check("set_limits has a typed entry like an engine function", row["name"] == "set_limits" and row["args"]["required"] == ["factor", "low", "high"])
    for f in L.factors(pack):
        mid = sum(f["default"]) / 2
        if f["key"] in ("obstacle", "step"):
            continue  # These need a thing in the world, checked below on a stored world.
        w = L.with_value(pack, f["key"], start, mid)
        back = pack_job.ask(pack, "validate", {"world": w})["world"]
        check(f"{f['key']} goes in and reads back through the pack's checks", L.value(pack, f["key"], back) == mid)

    fixture = json.loads((POLICY / "server" / "fixtures" / f"scenarios_{pack}.json").read_text())
    tight = copy.deepcopy(d)
    report = SP.run({"pack": pack, "world": start, "words": "", "out": str(tmp / f"plan_{pack}"), "reply": fixture, "limits": d})
    check("a stored reply stays a real list", report["count"] > 20, f"{report['count']} worlds, dropped {report['dropped']}")
    check("each kept world is inside the limits", all(not L.outside(pack, w["world"], d) for w in report["worlds"]))
    check("a world outside is dropped with a reason", bool(report["off_limits"]) and all(re.search(r"(above|below) the (high|low) limit", o["reason"]) for o in report["off_limits"]), report["off_limits"][0]["reason"] if report["off_limits"] else "")
    check("the drop count names the factor", all(k.split(":")[1] in wanted for k in report["dropped"] if k.startswith("outside_limits:")) and sum(v for k, v in report["dropped"].items() if k.startswith("outside_limits:")) == len(report["off_limits"]))
    disk = json.loads((tmp / f"plan_{pack}" / "scenarios.json").read_text())
    check("the limits are stored with the campaign", disk["limits"] == d and disk["base_world"] == start)
    tight[key] = [L.factor(pack, key)["default"][0], L.value(pack, key, start)] if pack == "window" else [L.value(pack, key, start), L.factor(pack, key)["allowed"][1]]
    narrower = SP.run({"pack": pack, "world": start, "words": "", "out": str(tmp / f"plan2_{pack}"), "reply": fixture, "limits": tight})
    check("a narrower limit drops more", len(narrower["off_limits"]) > len(report["off_limits"]), f"{len(report['off_limits'])} to {len(narrower['off_limits'])}")

    cover = L.coverage(pack, plan, grid["rows"], base=start)
    ran = [w for w in plan["worlds"] if not w["held_back"]]
    ended = {r["index"] for r in grid["rows"] if r["status"] in L.ENDED}
    check("coverage counts only worlds that ran", cover["runs"] == sum(w["index"] in ended for w in ran), str(cover["runs"]))
    for f in cover["factors"]:
        values = [L.value(pack, f["key"], w["world"]) for w in ran if w["index"] in ended]
        inside = [v for v in values if f["low"] <= v <= f["high"]]
        bands = {min(L.BANDS - 1, int((v - f["low"]) / (f["high"] - f["low"]) * L.BANDS)) for v in inside}
        check(f"{f['key']} coverage matches a count by hand", f["tested_low"] == min(inside) and f["tested_high"] == max(inside) and f["bands_touched"] == len(bands) and f["outside"] == len(values) - len(inside), f["words"])
    text = json.dumps([f["words"] for f in cover["factors"]])
    check("coverage says tested and never calls a range safe", "tested" in text.lower() or "not varied" in text.lower())
    check("no factor line says safe", not re.search(r"\bsafe\b", text, re.I))
    check("the note says tested does not mean safe", "does not mean the robot is safe" in cover["note"])
    check("an old batch says its limits are today's defaults", not cover["limits_stored"] and "before limits" in cover["limits_words"])
    held_cover = L.coverage(pack, {**plan, "limits": d}, [{**r, "status": "queued"} for r in grid["rows"]], base=start)
    check("no finished run means no coverage", held_cover["bands_touched"] == 0 and held_cover["runs"] == 0)

    import agent_post as AP
    fields = {"wind_ms": ("wind", "steady_ms"), "wet": ("weather", "wetness"), "dust": ("weather", "dust_gm2")} if pack == "window" else None
    if fields:
        ranges = AP.limits_of(disk, fields)
        by_field = {"wind_ms": "wind", "wet": "wetness", "dust": "dust"}
        check("a bounty's ranges come from the campaign, so they sit inside the limits", all(d[by_field[k]][0] <= v[0] and v[1] <= d[by_field[k]][1] for k, v in ranges.items()), json.dumps(ranges))


class Scripted:
    """Stands in for the sim: a run fails when the factor is past a line. The search and its counting stay real."""

    def __init__(self, pack, key, line, fail_when_high, verdict="slip_distance", disagree=False):
        self.pack, self.key, self.line, self.high, self.verdict, self.disagree = pack, key, line, fail_when_high, verdict, disagree
        self.jobs = []

    def __call__(self, jobs, live):
        self.jobs.extend(jobs)
        rows = []
        for j in jobs:
            v = L.value(self.pack, self.key, j["world"])
            bad = v > self.line if self.high else v < self.line
            if self.disagree and j["seed"] == 4100:  # One extra seed goes the other way.
                bad = not bad
            rows.append({"status": "failed" if bad else "passed", "verdict": self.verdict if bad else "passed", "reason": "scripted", "seed": j["seed"], "numbers": {}})
        live([{"status": r["status"], "verdict": r["verdict"]} for r in rows])
        return rows


def one_world_plan(pack, start, key, far):
    world = L.with_value(pack, key, start, far)
    return {"worlds": [{"index": 0, "name": "scripted", "group": "g", "seed": 3100, "held_back": False, "world": world, "hash": "h" * 64, "outline": {}, "t_limit": 30, "changes": []}], "limits": L.defaults(pack), "base_world": start}, [{"index": 0, "status": "failed", "verdict": "slip_distance", "verdict_reason": "x"}]


def check_boundary_logic(pack):
    print(f"--- boundary logic with a scripted runner, {pack}")
    start = pack_job.ask(pack, "start", {})["world"]
    key, far, line, high = ("wind", 15.0, 10.7, True) if pack == "window" else ("payload", 20.0, 11.3, True)
    plan, rows = one_world_plan(pack, start, key, far)
    fake = lambda w: {"world": w, "hash": "h", "outline": {}, "t_limit": 30}
    states = []
    run = Scripted(pack, key, line, high)
    state = B.find(pack, plan, rows, run, publish=lambda s: states.append(json.dumps(s)), validate=fake)
    one = state["groups"][0]["searches"][0]
    check("a clean line gives a clean boundary", one["clean"] is True, one["words"])
    check("the two values hold the true line", one["pass_value"] < line < one["fail_value"], f"{one['pass_value']} to {one['fail_value']}")
    check("the words name both values, the verdict and the seeds", re.search(rf"between {re.escape(L.factor(pack, key)['words'])} {L.plain(one['pass_value'])} and {L.plain(one['fail_value'])}", one["words"]) and "slip distance" in one["words"] and "3 of 3 seeds" in one["words"])
    check("at most 12 runs per factor", len(run.jobs) <= B.MAX_RUNS_PER_FACTOR, str(len(run.jobs)))
    same = [r for r in one["runs"] if not r["role"].startswith("seed")]
    check("bisection keeps one seed", {r["seed"] for r in same} == {3100} and len(same) >= 3)
    extra = [r for r in one["runs"] if r["role"].startswith("seed")]
    check("3 extra seeds on each side, all new", len(extra) == 6 and 3100 not in {r["seed"] for r in extra} and len({r["seed"] for r in extra}) == 3)
    check("live state came as it ran", len(states) > 5 and any('"running": true' in s for s in states))
    check("the state ends not running", state["running"] is False)

    wet = L.with_value(pack, key, start, far)
    other = "wetness" if pack == "window" else "friction"
    wet = L.with_value(pack, other, wet, 0.35)
    plan2 = {**plan, "worlds": [{**plan["worlds"][0], "world": wet}]}
    both = B.find(pack, plan2, rows, Scripted(pack, key, line, high), validate=fake)
    words = [s["words"] for s in both["groups"][0]["searches"] if s["factor"] == key][0]
    check("another changed factor is named as the context", words.startswith("With ") and "0.35" in words, words)

    run = Scripted(pack, key, line, high, disagree=True)
    state = B.find(pack, plan, rows, run, validate=fake)
    one = state["groups"][0]["searches"][0]
    check("seeds that disagree are said plainly", one["clean"] is False and "seeds disagree" in one["words"].lower() and "No clean boundary" in one["words"], one["words"])

    run = Scripted(pack, key, -1000.0, True)
    one = B.find(pack, plan, rows, run, validate=fake)["groups"][0]["searches"][0]
    check("a world that fails at the start value too has no boundary", one["clean"] is False and "start value" in one["words"] and len(run.jobs) == 2, one["words"])

    run = Scripted(pack, key, 1000.0, True)
    one = B.find(pack, plan, rows, run, validate=fake)["groups"][0]["searches"][0]
    check("a failure that does not come back has no boundary", one["clean"] is False and "did not fail" in one["words"], one["words"])

    crash = lambda jobs, live: [{"status": "failed", "verdict": "process_crashed", "reason": "x", "seed": j["seed"], "numbers": {}} for j in jobs]
    one = B.find(pack, plan, rows, crash, validate=fake)["groups"][0]["searches"][0]
    check("a crashed child is not read as a robot failure", one["clean"] is False and "before the judge" in one["words"], one["words"])

    untouched = {**plan, "worlds": [{**plan["worlds"][0], "world": start}]}
    group = B.find(pack, untouched, rows, Scripted(pack, key, line, high), validate=fake)["groups"][0]
    check("a group with no moved factor says so and runs nothing", group["world"] is None and "No clean boundary" in group["words"], group["words"])
    check("no failures means no search", B.find(pack, plan, [{"index": 0, "status": "passed", "verdict": "passed"}], Scripted(pack, key, line, high), validate=fake)["words"].startswith("There is no failure"))

    stored_plan, grid = stored(pack)
    groups = B.pick_groups(grid["rows"])
    counts = {}
    for r in grid["rows"]:
        if r["status"] in B.FAILED:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    check("the default is the 3 largest failure groups, from a stored batch", len(groups) == min(3, len(counts)) and all(counts[g] >= c for g in groups for k, c in counts.items() if k not in groups), json.dumps(counts))
    check("a user's pick wins", B.pick_groups(grid["rows"], [list(counts)[-1]]) == [list(counts)[-1]])
    check("a user's pick is capped at 3 groups", len(B.pick_groups(grid["rows"], list(counts)[:5])) <= B.MAX_GROUPS)
    sample = next(w for w in stored_plan["worlds"] if not w["held_back"] and B.moved_factors(pack, start, w["world"]))
    key2 = B.moved_factors(pack, start, sample["world"])[0]
    moved = L.with_value(pack, key2, sample["world"], L.value(pack, key2, start))
    check("a stored world with one factor changed passes the pack's real checks", pack_job.ask(pack, "validate", {"world": moved})["hash"] != sample["hash"])
    if pack == "inspection":
        for key3, expect in (("step", 0.1), ("obstacle", 0.1)):
            w = next(x["world"] for x in stored_plan["worlds"] if L.value(pack, key3, x["world"]) > L.value(pack, key3, start))
            got = pack_job.ask(pack, "validate", {"world": L.with_value(pack, key3, w, expect)})["world"]
            check(f"{key3} height goes in and reads back through the pack's checks", abs(L.value(pack, key3, got) - expect) < 1e-9)
    else:
        w = next(x["world"] for x in stored_plan["worlds"] if any(o["kind"] == "wet_patch" for o in x["world"]["objects"]))
        got = pack_job.ask(pack, "validate", {"world": L.with_value(pack, "wetness", w, 0.8)})["world"]
        check("a wet patch counts as the wettest glass, and goes in through the pack's checks", L.value(pack, "wetness", got) == 0.8)


def check_regressions(pack, tmp):
    print(f"--- regressions, {pack}")
    os.environ[REG.ROOT_ENV] = str(tmp / "suite")
    plan, grid = stored(pack)
    rows = {r["index"]: r for r in grid["rows"]}
    failures = [w for w in plan["worlds"] if not w["held_back"] and rows[w["index"]]["status"] in REG.FAILED]
    got = REG.ingest_campaign(pack, plan, grid["rows"], "a" * 64, "sim x", {"session": "batch", "campaign": pack})
    check("every failed world of a stored batch is saved", got["added"] == len(failures) and got["total"] == len(failures), json.dumps(got))
    again = REG.ingest_campaign(pack, plan, grid["rows"], "a" * 64, "sim x", {"session": "batch", "campaign": pack})
    check("the same batch again adds nothing", again["added"] == 0 and again["known"] == len(failures), json.dumps(again))
    suite = REG.load(pack)
    entry = suite["entries"][0]
    check("each entry has pack, world, seed, code sha and verdict", all(entry[k] for k in ("pack", "world", "seed", "hash")) and entry["first"]["code_sha"] == "a" * 64 and entry["first"]["verdict"])
    check("no held-back world enters the suite", not ({e["name"] for e in suite["entries"]} & {w["name"] for w in plan["worlds"] if w["held_back"]}))
    other_seed = {**failures[0], "seed": failures[0]["seed"] + 1, "status": "failed", "verdict": "fell", "reason": "x"}
    check("the same world on another seed is its own entry", REG.ingest(pack, [other_seed], "a" * 64, None, {})["added"] == 1)
    crash = {**failures[1], "hash": "f" * 64, "status": "failed", "verdict": "process_crashed", "reason": "x"}
    check("a crashed child stays out", REG.ingest(pack, [crash], "a" * 64, None, {})["added"] == 0)

    A, C = "a" * 64, "c" * 64
    bad = {"status": "failed", "verdict": "fell", "code_sha": A}
    good = {"status": "passed", "verdict": "passed", "code_sha": A}
    now_good, now_bad = {"status": "passed", "verdict": "passed"}, {"status": "failed", "verdict": "fell"}
    check("new code, same seed, same world, no failure: fixed", REG.classify(bad, now_good, 7, 7, C, True) == "fixed")
    check("a pass on a different seed is never fixed, whatever the code", REG.classify(bad, now_good, 7, 8, C, True) == "could_not_run" and REG.classify(bad, now_good, 7, 8, A, True) == "could_not_run")
    check("a pass on the same code is never fixed", REG.classify(bad, now_good, 7, 7, A, True) == "passes_same_code")
    check("a pass after the world's physics changed is never fixed", REG.classify(bad, now_good, 7, 7, C, False) == "world_changed")
    check("still failing", REG.classify(bad, now_bad, 7, 7, C, True) == "still_failing")
    check("a new failure against the last result", REG.classify(good, now_bad, 7, 7, C, True) == "new_failure")
    check("a crashed re-run is not fixed or failing", REG.classify(bad, {"status": "failed", "verdict": "process_crashed"}, 7, 7, C, True) == "could_not_run")
    check("a safe hold is not a failure", REG.classify(bad, {"status": "held", "verdict": "wind_hold"}, 7, 7, C, True) == "fixed")

    # A scripted suite run, then a real pack check of each stored world. Same code first, then new code that passes one world, then one that fails again.
    os.environ[REG.ROOT_ENV] = str(tmp / "suite2")
    REG.ingest_campaign(pack, plan, grid["rows"], A, "sim x", {"session": "batch", "campaign": pack})
    n = len(REG.load(pack)["entries"])
    fake = lambda w: {"world": w, "hash": REG_HASH[json.dumps(w, sort_keys=True)], "outline": {}, "t_limit": 30}
    REG_HASH = {json.dumps(e["world"], sort_keys=True): e["hash"] for e in REG.load(pack)["entries"]}
    fails = lambda jobs, live: [{"status": "failed", "verdict": "fell", "reason": "x", "seed": j["seed"], "numbers": {}} for j in jobs]
    state = REG.run_suite(pack, A, fails, fake)
    check("same code, same failures: all still failing, no fix claimed", state["counts"]["still_failing"] == n and state["counts"]["fixed"] == 0, state["words"])
    first = REG.load(pack)["entries"][0]["name"]
    partly = lambda jobs, live: [{"status": "passed" if j["name"] == first else "failed", "verdict": "passed" if j["name"] == first else "fell", "reason": "x", "seed": j["seed"], "numbers": {}} for j in jobs]
    state = REG.run_suite(pack, C, partly, fake)
    check("new code fixes one world: 1 fixed, the rest still failing", state["counts"]["fixed"] == 1 and state["counts"]["still_failing"] == n - 1, state["words"])
    state = REG.run_suite(pack, "d" * 64, fails, fake)
    check("that world failing again is a new failure", state["counts"]["new_failure"] == 1 and state["counts"]["fixed"] == 0, state["words"])
    public = REG.public(pack)
    check("history is kept per world and per run", len(public["runs"]) == 3 and len(public["entries"][0]["history"]) == 3 and "world" not in public["entries"][0])
    swapped = lambda jobs, live: [{"status": "passed", "verdict": "passed", "reason": "x", "seed": j["seed"] + 1, "numbers": {}} for j in jobs]
    state = REG.run_suite(pack, "e" * 64, swapped, fake)
    check("a runner that used another seed reports no fix", state["counts"]["fixed"] == 0 and state["counts"]["could_not_run"] == n, state["words"])
    empty = tmp / "suite3"
    os.environ[REG.ROOT_ENV] = str(empty)
    check("an empty suite says so", "empty" in REG.run_suite(pack, A, fails, fake)["words"])
    os.environ[REG.ROOT_ENV] = str(tmp / "suite4")
    REG.ingest_campaign(pack, plan, grid["rows"], A, "sim x", {"session": "batch", "campaign": pack})
    real_hash = validate_for(pack)
    entry = REG.load(pack)["entries"][0]
    check("a stored world still loads through the pack's own checks", real_hash(entry["world"])["hash"] == entry["hash"])


def direct(pack, world, seed, folder):
    """One run outside the search, through the pack's job, as the last word on each side."""
    return pack_job.ask(pack, "run", {"world": world, "seed": seed, "out": str(folder)}, timeout=900)


def check_real(pack, tmp, save):
    print(f"--- real runs, {pack}")
    plan, grid = stored(pack)
    start = pack_job.ask(pack, "start", {})["world"]
    out = tmp / f"real_{pack}"
    n = [0]

    def run_many(jobs, live):
        n[0] += 1
        return TR.run_jobs(pack, jobs, out / f"b{n[0]:03d}", on_rows=live, **TR.local_kit())
    t0 = time.perf_counter()
    state = B.find(pack, plan, grid["rows"], run_many, base=start)
    check("a real search ran", bool(state["groups"]), f"{time.perf_counter() - t0:.0f} s")
    # Then every other limit factor that a failed world moved on its own, so a noisy top group does not hide a clean line on another factor.
    searched = {s["factor"] for g in state["groups"] for s in g["searches"]}
    by_index = {r["index"]: r for r in grid["rows"]}
    for w in plan["worlds"]:
        row = by_index[w["index"]]
        moved = B.moved_factors(pack, start, w["world"])
        if not w["held_back"] and row["status"] in B.FAILED and len(moved) == 1 and moved[0] not in searched:
            searched.add(moved[0])
            state["groups"] += B.find(pack, plan, grid["rows"], run_many, base=start, wanted=[row["verdict"]], index=w["index"])["groups"]
    os.environ.setdefault(pack_job.NO_FRAMES_ENV, "1")
    clean = 0
    for g in state["groups"]:
        print(f"group {g['verdict']} ({g['count']} worlds), from {g['world']}, seed {g['seed']}")
        if g["words"]:
            print("  " + g["words"])
        world = next((w["world"] for w in plan["worlds"] if w["name"] == g["world"]), None)
        for s in g["searches"]:
            print("  " + s["words"])
            print("    " + ", ".join(f"{r['value']:g}/{r['seed']}:{r['verdict']}" for r in s["runs"]))
            check(f"{s['factor']}: at most 12 runs", len(s["runs"]) <= B.MAX_RUNS_PER_FACTOR, str(len(s["runs"])))
            validate = validate_for(pack)
            side = {}
            if not s["clean"]:
                check(f"{s['factor']}: no clean boundary is said plainly", s["words"].startswith("No clean boundary"))
                if s.get("pass_value") is None:
                    continue
                recorded = {r["value"]: r["verdict"] for r in s["runs"] if r["seed"] == g["seed"]}
                for value in (s["pass_value"], s["fail_value"]):
                    again = direct(pack, validate(L.with_value(pack, s["factor"], world, value))["world"], g["seed"], out / f"again_{g['verdict']}_{s['factor']}_{value:g}")
                    check(f"{s['factor']}: a direct run at {value:g}, seed {g['seed']}, gives the search's verdict", again["verdict"] == recorded[value], f"{recorded[value]}, then {again['verdict']}")
                continue
            clean += 1
            for name, value in (("pass", s["pass_value"]), ("fail", s["fail_value"])):
                side[name] = direct(pack, validate(L.with_value(pack, s["factor"], world, value))["world"], g["seed"], out / f"direct_{g['verdict']}_{s['factor']}_{name}")
            check(f"{s['factor']}: a direct run just inside does not fail", side["pass"]["passed"] or side["pass"].get("safe_hold"), f"{s['pass_value']:g}: {side['pass']['verdict']}")
            check(f"{s['factor']}: a direct run just outside fails", not side["fail"]["passed"] and not side["fail"].get("safe_hold"), f"{s['fail_value']:g}: {side['fail']['verdict']}")
    print(f"{clean} clean boundaries on {pack}. A clean line is a finding, and no check may require one.", flush=True)
    os.environ[REG.ROOT_ENV] = str(tmp / f"real_suite_{pack}")
    os.environ.pop(pack_job.NO_FRAMES_ENV, None)
    sha = __import__("hashlib").sha256(Path(pack_job.ask(pack, "catalog", {})["controller_files"][0]).read_bytes()).hexdigest()
    REG.ingest_campaign(pack, {**plan, "worlds": [w for w in plan["worlds"] if rows_failed(grid, w)]}, grid["rows"], sha, None, {"session": "check", "campaign": pack})
    n[0] = 100
    suite = REG.run_suite(pack, sha, run_many, validate_for(pack))
    print("  " + suite["words"])
    for r in suite["rows"]:
        print(f"    {r['name']}, seed {r['seed']}: was {r['was']['verdict']}, now {r['verdict']}: {r['words']}")
    check("a real suite run on unchanged code claims no fix", suite["counts"]["fixed"] == 0, json.dumps(suite["counts"]))
    if save:
        folder = POLICY / "runs" / "demo" / pack
        (folder / "boundary.json").write_text(json.dumps(state, indent=1))
        (folder / "regressions.json").write_text(json.dumps(suite, indent=1))
        (folder / "suite.json").write_text(json.dumps(REG.public(pack), indent=1))
        print("saved boundary.json, regressions.json and suite.json in", folder)


def rows_failed(grid, w):
    row = {r["index"]: r for r in grid["rows"]}[w["index"]]
    return not w["held_back"] and row["status"] in REG.FAILED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--save-demo", action="store_true")
    ap.add_argument("--pack", choices=PACKS, action="append")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="check-testing-") as d:
        tmp = Path(d)
        for pack in a.pack or PACKS:
            check_limits(pack, tmp)
            check_boundary_logic(pack)
            check_regressions(pack, tmp)
            if a.real:
                check_real(pack, tmp, a.save_demo)
    print("ALL PASS" if not failed[0] else f"{failed[0]} FAILED", flush=True)
    return 1 if failed[0] else 0


if __name__ == "__main__":
    sys.exit(main())
