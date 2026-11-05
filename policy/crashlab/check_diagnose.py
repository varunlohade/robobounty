"""Pass or fail check of the diagnosis word check, the factor table and the guard reading, with no LLM. Exits 0 on pass."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import diagnose as d

TABLE = {"detach": {"cases": 22, "of": 200, "low": [0, 66], "high": [20, 67], "true_pa": 181.0, "file_line": "policy/highrise/controller.py:215"}}
LINES = ["policy/highrise/controller.py:215", "policy/highrise/controller.py:203"]
NUMBERS = d.numbers_in(TABLE)

GOOD = ["Detach fired in 22 of 200 worlds in this simulation, at policy/highrise/controller.py:215.",
        "True pressure read 181 Pa.", "High gust worlds show 20 of 67 against 0 of 66."]
BAD = {"number not in table": "Detach fired in 23 of 200 worlds.",
       "derived percent": "Detach fired in 11 percent of worlds.",
       "derived number": "Detach fired in 11% of worlds.",
       "spelled number": "Detach fired in twenty worlds.",
       "vague amount": "Most worlds detached.",
       "file line not in trace": "The fault is at policy/highrise/controller.py:999.",
       "other file line": "The fault is at policy/highrise/sim.py:12.",
       "decimal not in table": "True pressure read 181.5 Pa.",
       "markup": "See <b>this</b> https://evil.example.",
       }


def main():
    failures = []
    for text in GOOD:
        reasons = d.check_words(text, NUMBERS, LINES)
        if reasons:
            failures.append(f"rejected good text: {text} {reasons}")
    for name, text in BAD.items():
        if not d.check_words(text, NUMBERS, LINES):
            failures.append(f"accepted: {name}")

    if not d.check_words("Wind hold was the first failure in 22 of 200.", NUMBERS, LINES, is_hold=True):
        failures.append("accepted: a hold called a failure")
    guard = d.guard_floor()
    if guard["blind_from_speed_measured"] is None or abs(guard["blind_from_speed_measured"] - guard["blind_from_speed_exact"]) > 0.011:
        failures.append(f"guard reading is off: {guard}")
    print(f"{len(BAD)} bad texts rejected, guard blind from speed {guard['blind_from_speed_measured']} (exact {guard['blind_from_speed_exact']})")

    world = {"steady_wind_ms": 2.0, "gust_speed_ms": 30.0, "gust_count": 0, "wind_dir_deg": -90.0}
    if d.derived(world)["peak_wind_ms"] != 2.0:
        failures.append("a world with no gusts reads as gusty")
    world["gust_count"] = 1
    if d.derived(world)["wind_out_of_wall_ms"] != 30.0:
        failures.append("wind out of the wall is wrong")
    rows = [{"failure": "detach" if i % 2 else None, "passed": not i % 2, "world": {"schema": "x", "a": float(i), "steady_wind_ms": 1.0, "gust_speed_ms": 1.0, "gust_count": 0, "wind_dir_deg": 0.0}} for i in range(30)]
    table = d.factor_table(rows, [], ["detach"])
    row = table["detach"]["factors"][0]
    if table["detach"]["cases"] != 15 or row["low"][1] + row["mid"][1] + row["high"][1] != 30:
        failures.append(f"factor table counts wrong: {json.dumps(table)}")
    built = d.requirements_module.build()
    if {r["rule"] for r in built["requirements"]} != set(d.judge_module.RULES) or [r["id"] for r in built["requirements"]][0] != "R1":
        failures.append("requirements do not match the judge rules")
    nominal = d.W.load(d.HIGHRISE / "worlds" / "nominal.json")
    jittered = d.jitter_world(nominal, 1, 0)
    if jittered == nominal or jittered != d.jitter_world(nominal, 1, 0) or abs(jittered["suction_pa"] / nominal["suction_pa"] - 1) > d.JITTER + 1e-6:
        failures.append("jitter is wrong")
    print("\n".join(failures) or "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
