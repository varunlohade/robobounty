"""Numbered pass or fail requirements, read from the judge. requirements.py <campaign dir> writes requirements.json before the first trial.

It fails loudly if the judge has a rule this table does not know, so the list cannot drift from what the judge enforces.
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "highrise"))
import judge as J


def build():
    table = {
        "detach": ("critical", f"The body stays on the glass: gap under {J.DETACH_GAP_M} m, or over it for less than {J.DETACH_HOLD_S} s, with its centre on the glass."),
        "tether_load": ("critical", f"Tether load stays at or under {J.TETHER_LOAD_LIMIT_N:.0f} N."),
        "slip_distance": ("high", f"No single slide on the glass goes further than {J.SLIP_LIMIT_M} m."),
        "false_done": ("high", f"When the robot reports done, reported coverage is within {J.FALSE_DONE_GAP} of true coverage."),
        "coverage": ("medium", f"True coverage is at least {J.COVERAGE_REQUIRED}, unless the run ends in a safe hold."),
        "time_limit": ("medium", f"The robot finishes within {J.TIME_LIMIT_S:.0f} s, or holds still on the glass for the last {J.HOLD_MIN_S:.0f} s for a stated reason: wind or low battery."),
    }
    table["stalled"] = ("high", f"The robot does not stop on the glass with no reason: not {J.WIND_CALM_MIN_S:.0f} s of wind under {J.WIND_CALM_MS} m/s without a battery reason.")
    if set(table) != set(J.RULES):
        raise SystemExit(f"judge rules changed: {sorted(set(J.RULES) ^ set(table))}")
    rows = [{"id": f"R{n}", "rule": rule, "severity": table[rule][0], "text": table[rule][1]} for n, rule in enumerate(table, 1)]
    return {"schema": "crashlab.requirements.v1", "requirements": rows, "judge_sha256": hashlib.sha256(Path(J.__file__).read_bytes()).hexdigest(),
            "holds": "wind_hold and battery_stop are their own outcomes: not a failure and not a pass.", "limits": "Simulation only. Limits are assumptions, see PARAMETERS.md."}


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    report = {**build(), "written_before_campaign": not (out / "results.jsonl").exists()}
    (out / "requirements.json").write_text(json.dumps(report, indent=1) + "\n")
    print(f"{len(report['requirements'])} requirements, written_before_campaign={report['written_before_campaign']}")


if __name__ == "__main__":
    main()
