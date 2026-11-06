"""The stored fix result, for the run server's "Show the recorded result" and for the app's Recorded run. Reads stored reports only. No AI call and no sim."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
STORED_FIX = ROOT / "policy" / "runs" / "highrise" / "campaign_dubai_v4" / "fix"
LIVE_FIX_REPORT = ROOT / "docs" / "evidence" / "live_fix_report.json"


def ab_rows(ab, names):
    """One table row per world set, from fix.py's own counts."""
    rows = []
    for key, label in names:
        b = ab.get(key)
        if b:
            rows.append({"set": label, "n": b["n"], "pass_a": b["A"]["pass"], "pass_b": b["B"]["pass"], "fail_a": b["A"]["fail"], "fail_b": b["B"]["fail"], "better": b["better"], "worse": b["worse"],
                         "same": b["same"], "p": b["sign_test_p_one_sided"], "limits_hit": b["limits_hit_B"], "replay_mismatch": b["replay_mismatch_B"]})
    return rows


def retest_conclusion(r):
    """The three conclusions fixed in retest_2026-11-06/PLAN.md, before the run."""
    required = r["sign_test_pass"] and r["controls_all_pass"] and not r["detach_or_slip_rose"]
    floor = r["blind_point"]["floor"]
    if not required:
        return "did not help"
    if floor["lowest_estimate_pa"] >= floor["guard_pa"]:
        return "helped on the counts but removed the low-pressure guard in the clean phase. Not recommended as it stands."
    return "helped on the counts and kept the guard"


def changes(retest):
    """Each world whose result changed, and what the change was. "Better" in the report is the plan's ranking: pass over hold over failure."""
    moved = [{"world": w["trial"], "before": w["A_failure"] or w["A"], "after": w["B_failure"] or w["B"], "was_pass": w["A"] == "pass", "now_pass": w["B"] == "pass"}
             for w in retest["per_world"] if (w["A_failure"] or w["A"]) != (w["B_failure"] or w["B"])]
    now_pass = [m for m in moved if m["now_pass"] and not m["was_pass"]]
    to_hold = [m for m in moved if not m["now_pass"] and not m["was_pass"] and m["after"] in ("battery_stop", "wind_hold", "safe_hold")]
    other = [m for m in moved if m not in now_pass and m not in to_hold]
    return moved, now_pass, to_hold, other


def plain_words(retest):
    """What the patch did, with no shorthand. Every count comes from the per-world rows."""
    moved, now_pass, to_hold, other = changes(retest)
    fresh = retest["fresh"]
    if len(now_pass) + len(to_hold) != fresh["better"]:
        raise ValueError("the per-world rows do not add up to the report's better count")
    holds = Counter(f"{m['before']} to {m['after']}" for m in to_hold)
    stops = ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in holds.items())
    side = ", ".join(f"{m['before']} to {m['after']}".replace("_", " ") for m in other)
    return (f"On {fresh['n']} new worlds: {len(now_pass)} failed and now pass. {len(to_hold)} did not pass either way, and changed: {stops}. "
            f"That is the report's {fresh['better']} better. {len(other)} moved between failure types ({side}). {fresh['worse']} got worse. "
            "The patch removes the low-pressure guard while cleaning, and we have not applied it.")


def live_words():
    """The only time the live fix step ran in the app, on a small check run. It found nothing better."""
    live = json.loads(LIVE_FIX_REPORT.read_text())
    ab = live["tries"][0]["ab"]
    return (f"Separately, a live AI fix try in the app, on a {live['seen_worlds']}-world check run and {live['fresh_worlds']} held-back worlds, "
            f"found {ab['fresh']['better']} better and {ab['fresh']['worse']} worse, and it did not help.")


def recorded_fix(sim_now):
    """The payload of the app's fix page, its one-line summary, and the short log line."""
    retest = json.loads((STORED_FIX / "retest_2026-11-06" / "report.json").read_text())
    overall = json.loads((STORED_FIX / "report.json").read_text())
    attempt = json.loads((STORED_FIX / "try_2" / "report.json").read_text())
    conclusion = retest_conclusion(retest)
    floor = retest["blind_point"]["floor"]
    moved, now_pass, to_hold, other = changes(retest)
    fresh = retest["fresh"]
    words = plain_words(retest)
    payload = {
        "title": "Recorded result",
        "source": "campaign_dubai_v4, try 2, then the larger test written down in retest_2026-11-06/PLAN.md before it ran. No AI call was made now.",
        "tables": [{"head": "Larger test, new held-back worlds, sim 0e36d3bf", "rows": ab_rows(retest, (("fresh", "Held-back worlds"), ("controls", "Controls")))},
                   {"head": "First test of the same patch, older sim aac6648b", "rows": ab_rows(attempt["ab"], (("seen", "Seen worlds"), ("fresh", "Held-back worlds"), ("controls", "Controls")))}],
        "failing_base": retest["baseline_failing_worlds"], "conclusion": conclusion, "plain": words,
        "first_verdict": attempt["verdict"]["reasons"], "first_status": overall["status"],
        "caveats": [f"The patch raises clean-phase suction to {floor['suction_clean']}. At that speed the lowest pressure estimate is {floor['lowest_estimate_pa']} Pa, and the guard fires only under {floor['guard_pa']} Pa. So the low-pressure guard can no longer fire in the clean phase.",
                    *overall["notes"], live_words()],
        "sandbox": {"validation": attempt["validation"] or ["AST check passed"], "limits_hit": fresh["limits_hit_B"], "replay_mismatch": fresh["replay_mismatch_B"], "held_back_shown_to_ai": overall["held_back_worlds_shown_to_llm"],
                    "note": overall["limits"][1]},
        "changed": [{"world": m["world"], "before": m["before"], "after": m["after"]} for m in moved], "limits": overall["limits"][0], "sim_recorded": "0e36d3bf", "sim_now": sim_now[:8],
    }
    summary = f"Recorded result. {words} Conclusion: {conclusion}"
    log_line = json.dumps({"failed_now_pass": len(now_pass), "stalled_to_battery_stop": len(to_hold), "between_failures": len(other), "better": fresh["better"], "worse": fresh["worse"], "p": fresh["sign_test_p_one_sided"],
                           "controls": f"{retest['controls']['B']['pass']}/{retest['controls']['n']}", "applied": retest["applied"]})
    return payload, summary, log_line
