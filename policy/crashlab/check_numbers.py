"""Recomputes every headline number from raw files, then checks each place that shows it. Stops nowhere: prints every row, exits 1 on any mismatch.

check_numbers.py            raw files from policy/runs, and checks that docs/evidence matches them.
check_numbers.py --evidence raw files from docs/evidence only, for anyone without policy/runs.
No sim, no AI and no network. Standard library only.
"""
import hashlib
import html
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
EV = ROOT / "docs" / "evidence"
RUNS = ROOT / "policy" / "runs" / "highrise"
USE_RAW = "--evidence" not in sys.argv
SIM = "0e36d3bf"
SEED_BASE = 3100000
HOLDS = {"wind_hold", "battery_stop", "safe_hold"}
bad = 0


def row(name, shown, want):
    global bad
    ok = shown == want
    bad += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {shown}" + ("" if ok else f" (raw says {want})"))


def load(name):
    return json.loads((EV / name).read_text())


# 1. Raw inputs.
rows = {r["trial"]: r for r in map(json.loads, (EV / "results.jsonl").read_text().splitlines())}
diagnosis, requirements, plan = load("diagnosis.json"), load("requirements.json"), load("scenarios.json")
hashes, hashes_v4, rerun = load("trial_hashes.json"), load("trial_hashes_v4.json"), load("trial_hashes_seed1000_rerun.json")
retest, live, sims = load("retest_report.json"), load("live_fix_report.json"), load("sim_of_each_run_set.json")

if USE_RAW:
    FINAL = RUNS / "campaign_dubai_final"
    for ev, raw in (("results.jsonl", FINAL / "results.jsonl"), ("diagnosis.json", FINAL / "diagnosis.json"), ("requirements.json", FINAL / "requirements.json"),
                    ("retest_report.json", RUNS / "campaign_dubai_v4" / "fix" / "retest_2026-11-06" / "report.json")):
        row(f"docs/evidence/{ev} equals its raw file", (EV / ev).read_bytes() == raw.read_bytes(), True)
    per_trial = {t: json.loads((FINAL / t / "result.json").read_text()) for t in rows}
    row("raw result.json files, one per trial", len(per_trial), 62)
    row("raw sim hash of every trial", sorted({r["code_sha256"]["sim.py"][:8] for r in per_trial.values()}), [SIM])
    row("evidence hash rows equal raw", all(hashes[t]["final_state_sha256"] == r["final_state_sha256"] for t, r in per_trial.items()), True)
    row("sim.py on disk", hashlib.sha256((ROOT / "policy/highrise/sim.py").read_bytes()).hexdigest()[:8], SIM)

# 2. Recompute the Dubai counts from per-trial rows and the re-runs alone.
varied = {t: r for t, r in rows.items() if r["kind"] == "varied"}
controls = {t: r for t, r in rows.items() if r["kind"] == "control"}
rerun_rows = {p["trial"]: p for p in diagnosis["reproduce"]["per_trial"]}
flaky = sorted(t for t, p in rerun_rows.items() if sum(x == p["failure"] for x in p["reruns"]) < diagnosis["reproduce"]["needed"])


def state(t):
    r = varied[t]
    if t in flaky:
        return "flaky"
    if r["passed"]:
        return "passed"
    return "held" if r["outcome"] in HOLDS and not r["failure"] else "failed"


states = {t: state(t) for t in varied}
n = Counter(states.values())
types = Counter(varied[t]["failure"] or varied[t]["outcome"] for t in states if states[t] == "failed")
groups = {g["name"]: Counter(states[t] for t in varied if varied[t]["group"] == g["name"]) for g in plan["groups"]}
TOTAL, FAILED, HELD, FLAKY, PASSED = len(varied), n["failed"], n["held"], n["flaky"], n["passed"]
print(f"Recomputed: {TOTAL} worlds: {FAILED} failed, {HELD} held, {FLAKY} flaky, {PASSED} passed. Controls {sum(r['passed'] for r in controls.values())}/{len(controls)}. Types {dict(types)}.")
row("states add up", FAILED + HELD + FLAKY + PASSED, TOTAL)
row("plan world count", plan["total_worlds"], TOTAL)
row("plan group count", len(plan["groups"]), len({r["group"] for r in varied.values()}))
row("diagnosis flaky list", sorted(f["trial"] for f in diagnosis["reproduce"]["flaky"]), flaky)
row("diagnosis passed", diagnosis["counts"]["varied_passed"], PASSED)
row("diagnosis failure counts", {f["type"]: f["count"] for f in diagnosis["failure_types"] if f["is_failure"]}, dict(types))
row("seeds are campaign seeds", all(r["seed"] == SEED_BASE + int(t[1:]) for t, r in varied.items()), True)
row("all trial hash rows on sim", sorted({h["sim_sha256"][:8] for h in hashes.values()}), [SIM])
holds = Counter(varied[t]["outcome"] for t in states if states[t] == "held")
detach = next(f for f in diagnosis["failure_types"] if f["type"] == "detach")
oracle, lead = diagnosis["oracle"], diagnosis["pressure_lead"]

# 3. Why numbers moved between run sets.
same_state = sum(hashes[t]["final_state_sha256"] == hashes_v4[t]["final_state_sha256"] for t in hashes)
row("final vs v4: sim differs, seed same, final states identical", same_state, len(hashes))
row("v4 ran on", [s[:8] for s in sims["campaign_dubai_v4"]], ["aac6648b"])
label = lambda r: r["failure"] or ("pass" if r["passed"] else r["outcome"])
moved = {f"world_{int(t[1:]):03d}": (rerun[f"world_{int(t[1:]):03d}"]["seed"], label(rerun[f"world_{int(t[1:]):03d}"]), r["seed"], label(r)) for t, r in hashes.items() if t in varied and label(rerun[f"world_{int(t[1:]):03d}"]) != label(r)}
row("seed-1000 re-run sim is the same sim", [s[:8] for s in sims["seed1000_rerun"]], [SIM])
row("seed-1000 re-run: worlds whose outcome differs (seed only)", sorted(moved), ["world_008", "world_030", "world_050"])
for k, v in moved.items():
    print(f"     {k}: seed {v[0]} {v[1]}; seed {v[2]} {v[3]}")

# 4. The fix: recompute from the per-world rows.
pw = retest["per_world"]
a_pass, b_pass = sum(w["A"] == "pass" for w in pw), sum(w["B"] == "pass" for w in pw)
got_pass = [w for w in pw if w["A"] != "pass" and w["B"] == "pass"]
to_battery = [w for w in pw if w["A_failure"] and not w["B_failure"] and w["B"] != "pass"]
across = [w for w in pw if w["A_failure"] and w["B_failure"] and w["A_failure"] != w["B_failure"]]
rank = lambda w, s: 2 if w[s] == "pass" else 1 if not w[f"{s}_failure"] else 0
worse = sum(rank(w, "B") < rank(w, "A") for w in pw)
better = sum(rank(w, "B") > rank(w, "A") for w in pw)
FA, FB = sum(bool(w["A_failure"]) for w in pw), sum(bool(w["B_failure"]) for w in pw)
print(f"Recomputed fix: {len(pw)} worlds, passed {a_pass} to {b_pass}, failed {FA} to {FB}, better {better} = {len(got_pass)} now pass + {len(to_battery)} to a hold, {len(across)} between failures, worse {worse}.")
row("report better", retest["fresh"]["better"], better)
row("report worse", retest["fresh"]["worse"], worse)
row("report pass A, B", (retest["fresh"]["A"]["pass"], retest["fresh"]["B"]["pass"]), (a_pass, b_pass))
row("report fail A, B", (retest["fresh"]["A"]["fail"], retest["fresh"]["B"]["fail"]), (FA, FB))
row("controls A, B", (retest["controls"]["A"]["pass"], retest["controls"]["B"]["pass"], retest["controls"]["n"]), (20, 20, 20))
row("patch is not applied", retest["applied"], False)
row("patch removes the guard in the clean phase", retest["blind_point"]["guard_still_can_fire_in_clean"], False)
row("retest ran on", [s[:8] for s in sims["retest_2026-11-06"]], [SIM])
row("first test of the patch ran on", [s[:8] for s in sims["fix_try_2"]], ["aac6648b"])
row("controller.py sha still the base", hashlib.sha256((ROOT / "policy/highrise/controller.py").read_bytes()).hexdigest(), retest["base_sha256"])
lab = live["tries"][0]["ab"]
row("live fix try: better, worse, status", (lab["fresh"]["better"], lab["fresh"]["worse"], lab["seen"]["better"], live["status"]), (0, 0, 0, "no_fix_helped"))
row("live fix ran on", [s[:8] for s in sims["live_fix_session_campaign"]], [SIM])

# 5. The app's data file.
app = json.loads((ROOT / "public/trials/worlds.json").read_text())
world = {w["campaign_trial"]: w for w in app["worlds"]}
row("app campaign", app["campaign"], "campaign_dubai_final")
row("app sim", app["sim_sha256"][:8], SIM)
row("app worlds", len(app["worlds"]), TOTAL)
row("app seeds are the campaign's", all(world[t]["seed"] == varied[t]["seed"] for t in varied), True)
row("app outcome of each world", {t: (world[t]["failure"], world[t]["passed"], world[t]["outcome"]) for t in varied}, {t: (varied[t]["failure"], varied[t]["passed"], varied[t]["outcome"]) for t in varied})
row("app flaky", sorted(t for t, w in world.items() if w["flaky"]), flaky)
row("app failed, by the page's rule", sum(not w["passed"] and bool(w["failure"]) and not w["flaky"] for w in app["worlds"]), FAILED)
row("app failure types", {t["rule"]: t["count"] for t in app["failures"]["types"]}, dict(types))
row("app excluded", sorted(e["name"] for e in app["failures"]["excluded"]), sorted(world[t]["name"] for t in flaky))
row("app controls", (app["controls"]["passed"], app["controls"]["n"]), (sum(r["passed"] for r in controls.values()), len(controls)))
row("app requirements", len(app["requirements"]), len(requirements["requirements"]))
row("app fix words", (f"{len(got_pass)} failed and now pass" in app["fix"]["plain"], "stalled to battery stop" in app["fix"]["plain"], "have not applied" in app["fix"]["plain"], "0 better" in " ".join(app["fix"]["caveats"])), (True, True, True, True))
index = json.loads((ROOT / "public/trials/index.json").read_text())
listed = [e["id"] for e in index]
linked = {w["trial"]: t for t, w in world.items() if w["trial"]}
row("headline replays are in the index", sorted(set(linked) - set(listed)), [])
row("index lists only the nominal run and headline replays", sorted(set(listed) - set(linked)), ["nominal-seed1"])
for rid, t in sorted(linked.items()):
    r = json.loads((ROOT / "public/trials" / rid / "result.json").read_text())
    row(f"replay {rid}: seed, failure, reproduced, sim", (r["seed"], r["failure"], states[t], r["code_sha256"]["sim.py"][:8]), (varied[t]["seed"], varied[t]["failure"], "failed", SIM))
row("replays with a repeat of 3 of 3", sorted(rerun_rows[t]["same_failure_runs"] for t in linked.values()), [3] * len(linked))

# 6. The site: the words a reader sees.
source = (ROOT / "design/site-draft/index.html").read_text()
no_comments = re.sub(r"<!--.*?-->", "", source, flags=re.S)
text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", no_comments)))
has = lambda phrase: phrase in text


def said(phrase):
    row(f"site says: {phrase}", has(phrase), True)


said(f"chose {TOTAL} worlds in {len(plan['groups'])} groups")
said(f"judged by {len(requirements['requirements'])} requirements")
said(f"The {FAILED} failures, by what went wrong")
counts = re.findall(r"<dd[^>]*>\s*([^<]+?)\s*</dd>", no_comments)
row("site count boxes", counts, [str(FAILED), str(HELD), str(FLAKY), str(PASSED), f"{sum(r['passed'] for r in controls.values())} of {len(controls)}"])
row("site strip", Counter(re.findall(r'<i class="([fhxp])"></i>', re.search(r'<div class="strip".*?</div>', no_comments, re.S).group(0))), Counter({"f": FAILED, "h": HELD, "x": FLAKY, "p": PASSED}))
row("site strip label", f'{TOTAL} worlds: {FAILED} failed, {HELD} stopped and held, {FLAKY} flaky and left out, {PASSED} passed' in no_comments, True)
hero = re.findall(r'<i class="w ([fhxp])" style="--i:\d+" title="(t\d{4}):', no_comments)
row("site hero squares", len(hero), TOTAL)
row("site hero state of each world", {t: {"f": "failed", "h": "held", "x": "flaky", "p": "passed"}[c] for c, t in hero}, states)
for name, c in groups.items():
    li = re.search(rf'<span class="g">{re.escape(name)}</span>.*?<span class="n[^"]*">([^<]+)</span>', no_comments, re.S).group(1)
    want = f"{c['failed']} failed" if c["failed"] else f"{c['held']} held" if c["held"] else f"{c['passed']} passed"
    row(f"site group {name}", li, want)
names = {"slip_distance": "Slid too far", "detach": "Came off the glass", "false_done": "Said done, was not", "stalled": "Stopped for no reason", "time_limit": "Ran out of time"}
for f in diagnosis["failure_types"]:
    if f["is_failure"]:
        file_line = f["code_line"].split("/")[-1]
        same_line = f["code_line_trials"]
        row(f"site failure row {names[f['type']]}", bool(re.search(rf'{names[f["type"]]}</th>.*?<code>{re.escape(file_line)}</code><span> in {same_line} of {f["count"]}</span></td><td class="ct fail">{f["count"]}</td>', no_comments)), True)
said(f"Each of the {lead['detach_estimate_above_guard_while_true_below']} times the robot came off the glass")
said(f"true pressure in {oracle['n']} re-runs, the robot came off {oracle['detach_with_true_pressure']} times, not {oracle['detach_with_estimate']}")
said(f"goes blind once fan speed passes {diagnosis['guard']['blind_from_speed_exact']}")
said(f"In {detach['stopped_at_full_suction'][0]} of those {detach['stopped_at_full_suction'][1]}")
said(f"tested it on {len(pw)} new worlds")
said(f"Passed {a_pass} {b_pass}")
said(f"Failed {FA} {FB}")
said("Normal runs passed 20 of 20 20 of 20")
said(f"{len(got_pass)} worlds went from failed to passed")
said("One went from stalled to a battery stop, which is not a pass")
said("One moved from a slide to a stall")
said("None got worse")
said("so we have not applied it")
said("0 better, 0 worse")
row("site has no stale stub or stored-brief claim", any(w in text for w in ("is a stub", "stored brief")), False)
row("site names no old campaign", "dubai_v4" in source, False)
numbers = (ROOT / "design/site-draft/NUMBERS.md").read_text()
for needle in (f"| {TOTAL}, {len(plan['groups'])} |", f"| Failed | {FAILED} |", f"| Stopped and held | {HELD} |", f"| Flaky, left out | {FLAKY} |", f"| Passed | {PASSED} |", f"| {TOTAL} |", "6 to pass", "campaign_dubai_final"):
    row(f"NUMBERS.md has {needle}", needle in numbers, True)
row("NUMBERS.md names no stale stub screen", "NOT-LIVE-EVIDENCE" in numbers, False)
size = sum(p.stat().st_size for p in EV.rglob("*") if p.is_file())
row("docs/evidence under 20 MB", size < 20 * 1024 * 1024, True)
print(f"docs/evidence is {size / 1e6:.1f} MB")
print(f"{bad} MISMATCHES" if bad else "ALL NUMBERS MATCH")
sys.exit(1 if bad else 0)
