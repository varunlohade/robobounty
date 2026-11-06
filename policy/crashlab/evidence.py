"""Writes docs/evidence/: small JSON summaries of the runs behind the headline numbers. policy/runs is gitignored, so this is what outsiders can check.

evidence.py   needs policy/runs. Copies summaries, adds one hash row per trial, and writes the drift comparison. No videos and no per-step logs.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "policy" / "runs"
HIGHRISE = RUNS / "highrise"
FINAL = HIGHRISE / "campaign_dubai_final"
V4 = HIGHRISE / "campaign_dubai_v4"
OUT = ROOT / "docs" / "evidence"
RERUN = RUNS / "reexport_0e36d3bf" / "worlds"
LIVE = RUNS / "server" / "d73b2152b3294f198d8b9e1a3d86ff2b" / "scenarios_1" / "batch_1" / "campaign" / "fix"
HASHES = ("seed", "passed", "failure", "outcome", "world_sha256", "model_sha256", "final_state_sha256", "action_chain_head")


def trial_rows(campaign):
    rows = {}
    for row in map(json.loads, (campaign / "results.jsonl").read_text().splitlines()):
        r = json.loads((campaign / row["trial"] / "result.json").read_text())
        rows[row["trial"]] = {**{k: r[k] for k in HASHES}, "sim_sha256": r["code_sha256"]["sim.py"]}
    return rows


def code_shas(folder):
    return sorted({json.loads(p.read_text())["code_sha256"]["sim.py"] for p in folder.rglob("result.json")})


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for src, name in ((FINAL / "results.jsonl", "results.jsonl"), (FINAL / "diagnosis.json", "diagnosis.json"), (FINAL / "requirements.json", "requirements.json"), (FINAL / "campaign.json", "campaign.json"), (FINAL / "table.txt", "table.txt"),
                      (RUNS / "scenarios" / "dubai_final" / "scenarios.json", "scenarios.json"),
                      (V4 / "fix" / "report.json", "fix_report.json"), (V4 / "fix" / "try_2" / "report.json", "fix_try_2_report.json"), (V4 / "fix" / "try_2" / "patch.diff", "fix_try_2_patch.diff"),
                      (V4 / "fix" / "retest_2026-11-06" / "report.json", "retest_report.json"), (V4 / "fix" / "retest_2026-11-06" / "PLAN.md", "retest_PLAN.md"),
                      (LIVE / "report.json", "live_fix_report.json")):
        shutil.copyfile(src, OUT / name)
    final, v4 = trial_rows(FINAL), trial_rows(V4)
    (OUT / "trial_hashes.json").write_text(json.dumps(final, indent=0) + "\n")
    (OUT / "trial_hashes_v4.json").write_text(json.dumps(v4, indent=0) + "\n")
    rerun = {}
    for folder in sorted(RERUN.iterdir()):
        r = json.loads((folder / "result.json").read_text())
        rerun[folder.name] = {**{k: r[k] for k in HASHES}, "sim_sha256": r["code_sha256"]["sim.py"]}
    (OUT / "trial_hashes_seed1000_rerun.json").write_text(json.dumps(rerun, indent=0) + "\n")
    (OUT / "sim_of_each_run_set.json").write_text(json.dumps({
        "campaign_dubai_final": code_shas(FINAL), "campaign_dubai_v4": sorted({r["sim_sha256"] for r in v4.values()}), "seed1000_rerun": sorted({r["sim_sha256"] for r in rerun.values()}),
        "retest_2026-11-06": code_shas(V4 / "fix" / "retest_2026-11-06" / "runs"), "fix_try_2": code_shas(V4 / "fix" / "try_2" / "runs"), "live_fix_session_campaign": code_shas(LIVE.parent / "t0000"),
    }, indent=1) + "\n")
    print("evidence written to", OUT)


if __name__ == "__main__":
    main()
