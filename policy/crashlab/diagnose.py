"""Diagnosis of one high-rise campaign: diagnose.py <campaign dir> [--word] [--retest] [--oracle] [--max-reruns N]

Writes <campaign>/diagnosis.json. Needs linetrace.py to have run first. Every table is computed from stored runs. Nothing here tunes a scene.
--retest  sets the top factor of each failure type back to nominal, same seed, and counts what changes.
--oracle  gives the controller the true pressure in place of its estimate, same worlds and seeds, and counts what changes.
--reproduce  re-runs each failure 3 times with a new sensor seed and 0.5% world jitter. A failure that does not come back in 2 of 3 is flaky: counted, then excluded.
--word    one LLM call words the table. check_words rejects any number not in the table and any file:line not in the trace.
All findings hold in this simulation only. The physics is uncalibrated.
"""
import argparse
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import re
import sys
from bisect import bisect_right
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
HIGHRISE = HERE.parent / "highrise"
sys.path.insert(0, str(HIGHRISE))  # ahead of this folder, which holds other files named sim.py and world.py
sys.path.append(str(HERE))
import controller as controller_module
import judge as judge_module
import numpy as np
import requirements as requirements_module
import run_trial
import sim as S
import world as W

MAX_PROCS = 4
MIN_CASES = 5
HOLDS = {"wind_hold", "battery_stop", "safe_hold"}  # outcomes that stayed on the glass: not a pass and not a failure
JUDGED_DURING_RUN = {"detach", "slip_distance", "tether_load"}  # every other label is decided when the run stops
TOP_FACTORS = 5
ALPHA = 0.05
SLIDE_GAP_STEPS = 20  # same gap the judge uses to end a slide
LIMITS = ["In this simulation only. The physics is hand-built and not calibrated to a real robot.",
          "A factor table shows association. Only a retest row changes one value and holds the rest.",
          "Tether peaks after a detach are not quoted, because that part of the model is crude."]
FILE = "policy/highrise/controller.py"
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_FILE_LINE = re.compile(r"[\w./-]*\.py:(\d+)")
_SPELLED = re.compile(r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
                      r"|hundred|thousand|half|third|quarter|percent|twice|double|majority|most)\b", re.I)
_MARKUP = re.compile(r"[<>{}\[\]`$\\|^~*#@&\"]|://")


def fisher_p(a, b, c, d):
    from scipy.stats import fisher_exact
    return float(fisher_exact([[a, b], [c, d]])[1])


def read_gz(path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def load(campaign):
    rows = [json.loads(l) for l in (campaign / "results.jsonl").read_text().splitlines()]
    rows.sort(key=lambda r: r["trial"])
    for r in rows:  # A run with no fired rule that still did not pass carries its own outcome, such as safe_hold.
        r["failure"] = r["failure"] or (None if r["passed"] else r.get("outcome"))
    return [r for r in rows if r["failure"] != "sim_diverged"], [r["trial"] for r in rows if r["failure"] == "sim_diverged"]


def derived(world):
    """Values that follow from a world alone. The wind law uses speed squared, whichever way it blows."""
    gust = world["gust_speed_ms"] if world["gust_count"] > 0 else 0.0
    peak = max(world["steady_wind_ms"], gust)
    return {"peak_wind_ms": peak, "wind_out_of_wall_ms": round(peak * max(0.0, -math.sin(math.radians(world["wind_dir_deg"]))), 4)}


def factor_values(rows):
    values = {}
    for r in rows:
        for k, v in {**{k: v for k, v in r["world"].items() if k != "schema"}, **derived(r["world"])}.items():
            values.setdefault(k, []).append(v)
    return {k: v for k, v in values.items() if len(set(v)) > 1 and k != "sun_level"}


def factor_table(varied, controls, types):
    """Equal-count thirds of each varied factor, with counts of each failure type. No threshold search."""
    values = factor_values(varied)
    tests = max(1, len(values) * len(types))
    table = {}
    for t in types:
        hit = [r["failure"] == t for r in varied]
        rows = []
        for name, v in values.items():
            ordered = sorted(v)
            cut1, cut2 = ordered[len(v) // 3], ordered[2 * len(v) // 3]
            bins = {"low": [], "mid": [], "high": []}
            for x, h in zip(v, hit):
                bins["low" if x < cut1 else "mid" if x < cut2 else "high"].append(h)
            lo, hi = bins["low"], bins["high"]
            p = fisher_p(sum(lo), len(lo) - sum(lo), sum(hi), len(hi) - sum(hi)) if lo and hi else 1.0
            rows.append({"factor": name, "cut_low": cut1, "cut_high": cut2, "low": [sum(lo), len(lo)], "mid": [sum(bins["mid"]), len(bins["mid"])],
                         "high": [sum(hi), len(hi)], "fisher_p_low_vs_high": round(p, 5), "adjusted_p": round(min(1.0, p * tests), 5),
                         "direction": "higher" if sum(hi) * max(1, len(lo)) > sum(lo) * max(1, len(hi)) else "lower"})
        rows.sort(key=lambda x: x["fisher_p_low_vs_high"])
        table[t] = {"cases": sum(hit), "of": len(hit), "controls": [sum(r["failure"] == t for r in controls), len(controls)],
                    "tests_adjusted_for": tests, "factors": rows[:TOP_FACTORS]}
    return table


class Lines:
    def __init__(self, path):
        log = read_gz(path)
        self.sha = log["code_sha256"]
        self.runs, self.transitions, self.sets = log["runs"], log["transitions"], log["sets"]
        self.starts = [r[0] for r in self.runs]

    def at(self, i):
        run = self.runs[max(0, bisect_right(self.starts, i) - 1)]
        return run[1], run[2]

    def occupancy(self, steps):
        out = Counter()
        for n, run in enumerate(self.runs):
            end = self.runs[n + 1][0] if n + 1 < len(self.runs) else steps
            out[(run[1], run[2])] += end - run[0]
        return out


def trace_rows(run_dir):
    t = read_gz(run_dir / "trace.json.gz")
    return {c: n for n, c in enumerate(t["columns"])}, t["rows"]


def onset_index(failure, fire_i, cols, rows):
    """The start of what the judge fired on, read from sim state. None when there is no such start."""
    if failure == "slip_distance":
        i, gap = fire_i, 0
        start = fire_i
        while i >= 0 and gap <= SLIDE_GAP_STEPS:
            if rows[i][cols["slip_rate"]] > S.SLIP_FLOOR_MS:
                start, gap = i, 0
            else:
                gap += 1
            i -= 1
        return start
    if failure == "detach":
        for i in range(fire_i, -1, -1):
            if rows[i][cols["dp"]] >= controller_module.LOW_PRESSURE_PA:
                return min(i + 1, fire_i)
    return None


def failure_lines(campaign, varied, controls, passed, types, source):
    known = {f"{FILE}:{n}" for n in range(1, len(source) + 1)}
    report, trace_lines = {}, set()
    base = Counter()
    base_steps = 0
    for r in controls:
        lines = Lines(campaign / r["trial"] / "lines.json.gz")
        steps = int(round(r["time_s"] * S.CONTROL_HZ))
        base += lines.occupancy(steps)
        base_steps += steps
    groups = {t: [r for r in varied if r["failure"] == t] for t in types}
    for t, cases in groups.items():
        at_fire, at_onset, end_of_run = Counter(), Counter(), 0
        into = Counter()
        with_line = Counter()
        for r in cases:
            run = campaign / r["trial"]
            lines = Lines(run / "lines.json.gz")
            if lines.sha != hashlib.sha256((HIGHRISE / "controller.py").read_bytes()).hexdigest():
                raise SystemExit(f"{r['trial']}: line log is from other code")
            cols, rows = trace_rows(run)
            fired = r["fired"]
            fire_t = fired[t]["t"] if isinstance(fired, dict) and t in fired else r["first_t"] or r["time_s"]
            i = min(len(rows) - 1, max(0, int(round(fire_t * S.CONTROL_HZ)) - 1))
            end_of_run += t not in JUDGED_DURING_RUN
            at_fire[tuple(lines.at(i))] += 1
            j = onset_index(t, i, cols, rows)
            if j is not None:
                at_onset[tuple(lines.at(j))] += 1
            prior = [x for x in lines.transitions if x["i"] <= i]
            if prior:
                into[(prior[-1]["to"], prior[-1]["line"], prior[-1]["wind_hold"])] += 1
            for ln in {x["line"] for x in lines.transitions}:
                with_line[ln] += 1
            trace_lines.update(x["line"] for x in lines.transitions)
            trace_lines.update(line for _, line in lines.occupancy(len(rows)) if line)

        def moment(counter):
            rows_out = []
            for (phase, line), n in counter.most_common(6):
                share = base[(phase, line)]
                rows_out.append({"phase": phase, "file_line": f"{FILE}:{line}" if line else None, "code": source[line - 1].strip() if line else None,
                                 "trials": n, "control_step_share": round(share / max(1, base_steps), 4)})
            return rows_out
        passed_with, control_with = Counter(), Counter()
        for pool, into_counter in ((passed, passed_with), (controls, control_with)):
            for r in pool:
                for ln in {x["line"] for x in Lines(campaign / r["trial"] / "lines.json.gz").transitions}:
                    into_counter[ln] += 1
        enriched = [{"file_line": f"{FILE}:{ln}", "code": source[ln - 1].strip(), "this_failure": [n, len(cases)], "passed_worlds": [passed_with[ln], len(passed)],
                     "controls": [control_with[ln], len(controls)]}
                    for ln, n in with_line.most_common() if ln and n * max(1, len(passed)) > passed_with[ln] * len(cases)][:6]
        report[t] = {"cases": len(cases), "fires_at_end_of_run": end_of_run, "moment": "end of run, so the line shows where the run stopped, not a cause" if end_of_run == len(cases) else "when the judge fired",
                     "at_fire": moment(at_fire), "at_onset": moment(at_onset),
                     "phase_entered_by": [{"phase": p, "file_line": f"{FILE}:{ln}", "wind_hold": w, "trials": n} for (p, ln, w), n in into.most_common(6) if ln],
                     "transition_lines_more_common_than_in_passes": enriched}
    return report, sorted(f"{FILE}:{n}" for n in trace_lines if f"{FILE}:{n}" in known)


def guard_floor():
    """Runs the real estimator across impeller speeds at very high power, its low end, and at zero power, its high end."""
    mission = {"area": {"x0": 0.0, "x1": 2.4, "z0": 135.0, "z1": 138.0}, "anchor": (0.0, -0.3, 160.0), "start_x": 0.0, "start_z": 138.0}
    ctl = controller_module.Controller(mission)
    rows, blind_from = [], None
    for k in range(50, 101):
        ctl.speed_est = k / 100
        ctl.current_avg = 1e6
        floor = ctl._pressure_estimate({"battery_volts": 15.0})
        ctl.current_avg = 0.0
        ceiling = ctl._pressure_estimate({"battery_volts": 15.0})
        if floor >= controller_module.LOW_PRESSURE_PA and blind_from is None:
            blind_from = k / 100
        if k in (70, 85, 89, 90, 100):
            rows.append({"speed": k / 100, "lowest_estimate_pa": round(floor, 1), "estimate_at_zero_power_pa": round(ceiling, 1)})
    return {"low_pressure_pa": controller_module.LOW_PRESSURE_PA, "blind_from_speed_measured": blind_from,
            "blind_from_speed_exact": round(math.sqrt(controller_module.LOW_PRESSURE_PA / (controller_module.DESIGN_P_MAX * 2 / 3)), 3),
            "suction_clean": controller_module.SUCTION_CLEAN, "suction_max": controller_module.SUCTION_MAX, "samples": rows,
            "file_lines": [f"{FILE}:36", f"{FILE}:108"]}


def dead_phase(campaign, rows):
    """Trials where a line set the phase to None. No branch of the phase chain then runs, so the robot stops acting for good."""
    hits = Counter()
    trials = []
    for r in rows:
        for x in Lines(campaign / r["trial"] / "lines.json.gz").transitions:
            if x["to"] is None and x["line"]:
                hits[x["line"]] += 1
                trials.append(r["trial"])
                break
    return {"trials": len(trials), "of": len(rows), "file_lines": [f"{FILE}:{n}" for n in hits], "trial_ids": trials,
            "outcomes": dict(Counter((r["failure"] or r.get("outcome")) for r in rows if r["trial"] in trials))}


def pressure_lead(campaign, varied):
    """True pressure against the estimate, in every step of every varied trial, then at each detach."""
    low = controller_module.LOW_PRESSURE_PA
    steps_low = seen_low = 0
    detaches, by_phase = [], Counter()
    for r in varied:
        cols, rows = trace_rows(campaign / r["trial"])
        est_col = cols.get("estimate_pa", cols.get("est_fraction"))
        moved = False
        for row in rows:
            if row[cols["dp"]] < low and not moved:
                steps_low += 1
                seen_low += row[est_col] < low
            if row[cols["dp"]] <= 0:
                moved = True
        if r["failure"] != "detach":
            continue
        fired = r["fired"]
        fire_t = fired["detach"]["t"] if isinstance(fired, dict) else r["first_t"]
        i = min(len(rows) - 1, max(0, int(round(fire_t * S.CONTROL_HZ)) - 1))
        j = onset_index("detach", i, cols, rows)
        row, onset = rows[i], rows[j] if j is not None else None
        by_phase[onset[cols["phase"]] if onset else "below limit from the start"] += 1
        detaches.append({"trial": r["trial"], "t": fire_t, "true_pa": row[cols["dp"]], "estimate_pa": row[est_col], "phase": row[cols["phase"]],
                         "estimate_above_guard": row[est_col] >= low, "true_below_guard": row[cols["dp"]] < low,
                         "seconds_true_below_guard_before_detach": round((i - j) / S.CONTROL_HZ, 2) if j is not None else None})
    return {"steps_true_pressure_below_guard": steps_low, "of_those_estimate_below_guard": seen_low,
            "detach_trials": len(detaches), "detach_estimate_above_guard_while_true_below": sum(d["estimate_above_guard"] and d["true_below_guard"] for d in detaches),
            "phase_when_true_pressure_fell_below_guard": dict(by_phase), "per_trial": detaches}


class OracleSim(S.Sim):
    latest = None

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        OracleSim.latest = self


class OracleController(controller_module.Controller):
    def _pressure_estimate(self, o):
        return OracleSim.latest.dp


def _rerun(job):
    world, seed, oracle = job
    if oracle:
        run_trial.S.Sim, keep = OracleSim, run_trial.S.Sim
        run_trial.controller_module = SimpleNamespace(Controller=OracleController)
        try:
            r = run_trial.run(world, seed)
        finally:
            run_trial.S.Sim = keep
            run_trial.controller_module = controller_module
    else:
        r = run_trial.run(world, seed)
    return {"passed": r["passed"], "failure": r["failure"], "outcome": r.get("outcome")}


def oracle_test(pool, varied, controls, limit):
    detached = [r for r in varied if r["failure"] == "detach"]
    cases = detached + [r for r in varied if r["failure"] != "detach"][:limit] + controls
    done = pool.map(_rerun, [(r["world"], r["seed"], True) for r in cases], chunksize=2)
    pairs = list(zip(cases, done))
    v = [p for p in pairs if p[0]["kind"] == "varied"]
    return {"n": len(v), "passed_with_estimate": sum(a["passed"] for a, _ in v), "passed_with_true_pressure": sum(b["passed"] for _, b in v),
            "fail_to_pass": sum(not a["passed"] and b["passed"] for a, b in v), "pass_to_fail": sum(a["passed"] and not b["passed"] for a, b in v),
            "detach_with_estimate": sum(a["failure"] == "detach" for a, _ in v), "detach_with_true_pressure": sum(b["failure"] == "detach" for _, b in v),
            "controls_passed_with_true_pressure": [sum(b["passed"] for a, b in pairs if a["kind"] == "control"), len(controls)]}


def retest(pool, table, varied, nominal, limit):
    out = []
    for t, row in table.items():
        cases = [r for r in varied if r["failure"] == t][:limit]
        if len(cases) < MIN_CASES or not row["factors"] or row["factors"][0]["adjusted_p"] > ALPHA:
            continue
        name = row["factors"][0]["factor"]
        if name == "peak_wind_ms":
            change = {"steady_wind_ms": nominal["steady_wind_ms"], "gust_count": 0}
        elif name == "wind_out_of_wall_ms":
            change = {"wind_dir_deg": nominal["wind_dir_deg"]}
        else:
            change = {name: nominal[name]}
        done = pool.map(_rerun, [({**r["world"], **change}, r["seed"], False) for r in cases], chunksize=2)
        out.append({"failure": t, "factor": name, "set_to_nominal": change, "worlds": len(cases), "still_this_failure": sum(d["failure"] == t for d in done),
                    "now_pass": sum(d["passed"] for d in done), "other_failure": sum(not d["passed"] and d["failure"] != t for d in done)})
    return out


JITTER = 0.005
REPRODUCE_RUNS = 3
REPRODUCE_NEEDED = 2
WORST = {"detach": ("first_t", min), "slip_distance": ("slip_m", max), "tether_load": ("first_t", min), "false_done": ("coverage", min),
         "coverage": ("coverage", min), "time_limit": ("coverage", min), "safe_hold": ("coverage", min)}


def jitter_world(world, r_seed, k):
    rng = np.random.default_rng([r_seed % 2**31, k, 7])
    out = dict(world)
    for name, (lo, hi) in W.FIELDS.items():
        if name not in W.INTEGER_FIELDS:
            out[name] = min(hi, max(lo, round(world[name] * (1 + rng.uniform(-JITTER, JITTER)), 5)))
    return W.validate(out)


def reproduce(pool, failing):
    jobs = [(jitter_world(r["world"], r["seed"], k), r["seed"] + 100000 * (k + 1), False) for r in failing for k in range(REPRODUCE_RUNS)]
    done = pool.map(_rerun, jobs, chunksize=2)
    rows = []
    for n, r in enumerate(failing):
        kept = done[n * REPRODUCE_RUNS:(n + 1) * REPRODUCE_RUNS]
        labels = [d["failure"] or d["outcome"] for d in kept]
        same = sum(x == r["failure"] for x in labels)
        rows.append({"trial": r["trial"], "failure": r["failure"], "same_failure_runs": same, "of": REPRODUCE_RUNS, "reruns": labels, "reproduced": same >= REPRODUCE_NEEDED})
    return rows


def margin_at(run_dir, index):
    """The command at that step. Stopped at full suction means the controller had no more force to ask for."""
    with gzip.open(run_dir / "actions.jsonl.gz", "rt") as f:
        rows = [json.loads(l) for l in f]
    a = rows[min(index + 1, len(rows) - 1)]["a"]
    return {"stopped_at_full_suction": a[2] >= controller_module.SUCTION_MAX - 1e-9 and abs(a[0]) < 1e-9 and abs(a[1]) < 1e-9,
            "left_speed": a[0], "right_speed": a[1], "suction": a[2]}


def failure_types(campaign, varied, table, lines):
    """A few types: one per judge requirement that failed. Worst world by the measure named in WORST."""
    reqs = requirements_module.build()
    by_rule = {r["rule"]: r for r in reqs["requirements"]}
    out = []
    for t in table:
        cases = [r for r in varied if r["failure"] == t]
        req = by_rule.get(t)
        metric, pick = WORST.get(t, ("coverage", min))
        worst = pick(cases, key=lambda r: r.get(metric) if r.get(metric) is not None else r["time_s"])
        margin = []
        for r in cases:
            run = campaign / r["trial"]
            cols, rows = trace_rows(run)
            fired = r["fired"]
            fire_t = fired[t]["t"] if isinstance(fired, dict) and t in fired else r["first_t"] or r["time_s"]
            i = min(len(rows) - 1, max(0, int(round(fire_t * S.CONTROL_HZ)) - 1))
            j = onset_index(t, i, cols, rows)
            margin.append(margin_at(run, j if j is not None else i)["stopped_at_full_suction"])
        fl = lines[t]
        top = (fl["at_onset"] or fl["at_fire"] or [{}])[0]
        out.append({"type": t, "is_failure": t not in HOLDS, "requirement": req["id"] if req else None, "severity": req["severity"] if req else "info", "count": len(cases),
                    "worst_world": {"trial": worst["trial"], "measure": metric, "value": worst.get(metric)}, "code_line": top.get("file_line"), "code": top.get("code"),
                    "phase": top.get("phase"), "code_line_trials": top.get("trials"), "stopped_at_full_suction": [sum(margin), len(margin)],
                    "trials": [r["trial"] for r in cases]})
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    return sorted(out, key=lambda x: (order[x["severity"]], -x["count"]))


def follow_ups(types, oracle):
    """Failures the code probably cannot fix: the robot was already stopped at full suction when it began. A flag for a person, not a proof."""
    out = []
    for f in types:
        k, n = f["stopped_at_full_suction"]
        if f["type"] in ("detach", "slip_distance", "tether_load") and n and k * 2 >= n:
            out.append({"id": f"F{len(out) + 1}", "failure_type": f["type"], "requirement": f["requirement"], "severity": f["severity"], "trials": f["trials"],
                        "evidence": {"stopped_at_full_suction": [k, n], "true_pressure_oracle": oracle},
                        "why": "When this failure began, the robot had already stopped with suction at full, so the controller had no more force to command.",
                        "needs": "A hardware or physical-limit decision: suction, tracks or tether. Or a work limit on wind.",
                        "route": "bounty_or_owner", "caveat": "Simulation only. An earlier reaction by the controller is not ruled out."})
    return out


def check_words(text, table_numbers, trace_lines, is_hold=False):
    """Returns a list of reasons, empty when the text passes."""
    bad = []
    if is_hold and re.search(r"\bfail", text, re.I):
        bad.append("calls a hold a failure")
    if _MARKUP.search(text):
        bad.append("markup")
    if _SPELLED.search(text):
        bad.append(f"spelled number or vague amount: {_SPELLED.search(text)[0]}")
    allowed = {Decimal(str(n)).normalize() for n in table_numbers}
    lines = {int(x.rsplit(":", 1)[1]) for x in trace_lines}
    for m in _FILE_LINE.finditer(text):
        if int(m[1]) not in lines:
            bad.append(f"file line not in the trace: {m[0]}")
    plain = _FILE_LINE.sub(" ", text)
    for m in _NUMBER.finditer(plain):
        if Decimal(m[0]).normalize() not in allowed:
            bad.append(f"number not in the table: {m[0]}")
    return bad


def numbers_in(value):
    return [Decimal(m) for m in _NUMBER.findall(json.dumps(value))]


def word(summary, trace_lines):
    import llm
    schema = {"type": "object", "additionalProperties": False, "required": ["findings"], "properties": {"findings": {"type": "array", "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False, "required": ["failure_type", "text"],
        "properties": {"failure_type": {"type": "string", "maxLength": 40}, "text": {"type": "string", "maxLength": 500}}}}}}
    prompt = ("Word this robot simulation diagnosis in plain short sentences, one finding per type. wind_hold and battery_stop are holds on the glass: never call them failures. Use only numbers exactly as they appear in the table, and "
              "write counts as k of n. Compute nothing new: no percentages, no sums, no spelled-out numbers and no words like most or half. Cite code only as "
              "policy/highrise/controller.py:LINE, using a file_line in the table. Say what the evidence shows and no more. A factor table is association; only a retest "
              "or oracle row is a controlled change. Say so. Every finding holds in this simulation only.\n\nTable:\n" + json.dumps(summary))
    reply = llm.complete_json(prompt, schema)
    allowed = numbers_in(summary)
    out = []
    for item in reply["findings"]:
        out.append({"failure_type": item["failure_type"], "text": item["text"],
                    "rejected_because": check_words(item["text"], allowed, trace_lines, item["failure_type"] in HOLDS)})
    return out


def summary_of(report):
    """The small table the LLM sees. It holds no world text, only our field names and numbers."""
    lines = {}
    for t, row in report["failure_lines"].items():
        lines[t] = {"cases": row["cases"], "fires_at_end_of_run": row["fires_at_end_of_run"], "at_fire": row["at_fire"][:2], "at_onset": row["at_onset"][:2],
                    "phase_entered_by": row["phase_entered_by"][:2], "transition_lines": row["transition_lines_more_common_than_in_passes"][:2]}
    return {"counts": report["counts"], "factors": {t: {**{k: v for k, v in r.items() if k != "factors"}, "factors": r["factors"][:2]} for t, r in report["factor_table"].items()},
            "lines": lines, "guard": report["guard"], "pressure": {k: v for k, v in report["pressure_lead"].items() if k != "per_trial"},
            "retest": report["retest"], "oracle": report["oracle"], "dead_phase": {k: report["dead_phase"][k] for k in ("trials", "of", "file_lines", "outcomes")}, "flaky_excluded": report["reproduce"]["flaky_excluded"], "reproduced": report["reproduce"]["reproduced"],
            "failure_types": [{k: f[k] for k in ("type", "requirement", "severity", "count", "code_line", "stopped_at_full_suction")} for f in report["failure_types"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--word", action="store_true")
    ap.add_argument("--retest", action="store_true")
    ap.add_argument("--oracle", action="store_true")
    ap.add_argument("--reproduce", action="store_true")
    ap.add_argument("--max-reruns", type=int, default=20)
    ap.add_argument("--procs", type=int, default=MAX_PROCS)
    a = ap.parse_args()
    campaign = Path(a.campaign)
    rows, diverged = load(campaign)
    varied = [r for r in rows if r["kind"] == "varied"]
    controls = [r for r in rows if r["kind"] == "control"]
    stored = json.loads((campaign / rows[0]["trial"] / "result.json").read_text())["code_sha256"]
    now = run_trial.code_hashes()
    if (a.retest or a.oracle or a.reproduce) and stored != now:
        raise SystemExit(f"reruns refused: {sorted(k for k in now if stored.get(k) != now[k])} changed since this campaign ran, so a paired rerun would not be paired")
    reproduced, flaky = [], []
    if a.reproduce:
        with mp.Pool(min(a.procs, MAX_PROCS)) as pool:
            reproduced = reproduce(pool, [r for r in varied if not r["passed"]])
        flaky = [x for x in reproduced if not x["reproduced"]]
        drop = {x["trial"] for x in flaky}
        varied = [r for r in varied if r["trial"] not in drop]
    passed = [r for r in varied if r["passed"]]
    types = [t for t, _ in Counter(r["failure"] for r in varied if not r["passed"]).most_common()]
    source = (HIGHRISE / "controller.py").read_text().splitlines()
    report = {"schema": "crashlab.diagnosis.v1", "campaign": campaign.name, "limits": LIMITS, "code_matches_campaign": stored == now,
              "code_changed_since_campaign": sorted(k for k in now if stored.get(k) != now[k]),
              "counts": {"varied": len(varied), "varied_passed": len(passed), "controls": len(controls), "controls_passed": sum(r["passed"] for r in controls),
                         "diverged": len(diverged), "first_failure": dict(Counter(r["failure"] for r in varied if not r["passed"] and r["failure"] not in HOLDS)),
                         "holds": dict(Counter(r["failure"] for r in varied if r["failure"] in HOLDS))},
              "groups": {g: {"passed": sum(r["passed"] for r in varied if r.get("group") == g), "worlds": sum(r.get("group") == g for r in varied),
                             "first_failure": dict(Counter(r["failure"] for r in varied if r.get("group") == g and not r["passed"]))}
                         for g in sorted({r["group"] for r in varied if r.get("group")})},
              "factor_table": factor_table(varied, controls, types), "guard": guard_floor(), "pressure_lead": pressure_lead(campaign, varied),
              "reproduce": {"runs_per_failure": REPRODUCE_RUNS, "needed": REPRODUCE_NEEDED, "jitter": JITTER, "ran": bool(a.reproduce), "reproduced": sum(x["reproduced"] for x in reproduced),
                            "flaky_excluded": len(flaky), "flaky": flaky, "per_trial": reproduced},
              "retest": [], "oracle": None, "wording": None, "wording_error": None}
    report["failure_lines"], report["trace_lines"] = failure_lines(campaign, varied, controls, passed, types, source)
    if a.retest or a.oracle:
        nominal = W.load(HIGHRISE / "worlds" / "nominal.json")
        with mp.Pool(min(a.procs, MAX_PROCS)) as pool:
            if a.retest:
                report["retest"] = retest(pool, report["factor_table"], varied, nominal, a.max_reruns)
            if a.oracle:
                report["oracle"] = oracle_test(pool, varied, controls, a.max_reruns)
    req_path = campaign / "requirements.json"
    report["requirements"] = json.loads(req_path.read_text()) if req_path.exists() else {**requirements_module.build(), "written_before_campaign": False}
    report["dead_phase"] = dead_phase(campaign, [r for r in rows if r["kind"] == "varied"])
    report["failure_types"] = failure_types(campaign, varied, report["factor_table"], report["failure_lines"])
    report["follow_ups"] = follow_ups(report["failure_types"], report["oracle"])
    if a.word:
        import llm
        try:
            report["wording"] = word(summary_of(report), report["trace_lines"])
        except llm.LLMError as e:
            report["wording_error"] = str(e)
    (campaign / "diagnosis.json").write_text(json.dumps(report, indent=1, allow_nan=False) + "\n")
    print(json.dumps({k: report[k] for k in ("counts", "guard", "retest", "oracle", "code_changed_since_campaign")}, indent=1))
    print(json.dumps({k: v for k, v in report["pressure_lead"].items() if k != "per_trial"}))
    for t, row in report["factor_table"].items():
        print(t, row["cases"], "of", row["of"], "controls", row["controls"], [(f["factor"], f["low"], f["high"], f["adjusted_p"]) for f in row["factors"][:3]])
        fl = report["failure_lines"][t]
        print("  fire", [(m["phase"], m["file_line"], m["trials"], m["control_step_share"]) for m in fl["at_fire"][:3]], "end_of_run", fl["fires_at_end_of_run"])
        print("  onset", [(m["phase"], m["file_line"], m["trials"]) for m in fl["at_onset"][:3]])
        print("  entered", [(m["phase"], m["file_line"], m["wind_hold"], m["trials"]) for m in fl["phase_entered_by"][:3]])
        print("  enriched", [(m["file_line"], m["this_failure"], m["passed_worlds"], m["controls"]) for m in fl["transition_lines_more_common_than_in_passes"][:3]])
    print("FAILURE TYPES", json.dumps([{k: f[k] for k in ("type", "requirement", "severity", "count", "worst_world", "code_line", "stopped_at_full_suction")} for f in report["failure_types"]]))
    print("DEAD PHASE", json.dumps(report["dead_phase"]))
    print("FLAKY", report["reproduce"]["flaky_excluded"], "REPRODUCED", report["reproduce"]["reproduced"], "FOLLOW UPS", [(x["id"], x["failure_type"], len(x["trials"])) for x in report["follow_ups"]])
    for w in report["wording"] or []:
        print("WORDED", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
