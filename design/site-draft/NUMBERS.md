# Numbers on the page, and where each one comes from

Paths start at the repo root. `E` means `docs/evidence`, the committed copy of the summaries. `E/results.jsonl` and `E/diagnosis.json` come from `campaign_dubai_final`, on commit 325b798 and sim 0e36d3bf. Every value on the page also has a comment beside it in `index.html`.

To check every number below: `python3 policy/crashlab/check_numbers.py --evidence`. With `policy/runs` present, drop the flag and it reads the raw files too.

## Hero and Dubai run

| On the page | Value | Source |
|---|---|---|
| Squares in the hero, one per world | 52 | `E/results.jsonl` (`kind` not control), flaky list from `E/diagnosis.json` `reproduce.flaky` |
| Worlds and groups | 52, 8 | `E/scenarios.json` `total_worlds`, `groups` |
| Per-group counts (6, 7, 3, 2, 6, 3, 9, 2) | see page | `E/results.jsonl`, checked against `E/diagnosis.json` `groups` |
| Requirements, written before the run | 7 | `E/requirements.json` |
| Failed | 31 | `E/diagnosis.json` `counts.first_failure`: 17+9+3+1+1 |
| Stopped and held | 13 | `E/diagnosis.json` `counts.holds`: 9+4 |
| Flaky, left out | 5 | `E/diagnosis.json` `reproduce.flaky_excluded` |
| Passed | 3 | `E/diagnosis.json` `counts.varied_passed` |
| Normal-condition runs passed | 10 of 10 | `E/diagnosis.json` `counts.controls_passed`, `controls` |

## Failure table

| On the page | Value | Source |
|---|---|---|
| Slid too far | 17, `controller.py:240` in 8 of 17 | `E/diagnosis.json` `failure_types` |
| Came off the glass | 9, `controller.py:250` in 4 of 9 | same |
| Said done, was not | 3, `controller.py:261` in 3 of 3 | same |
| Stopped for no reason | 1, `controller.py:260` in 1 of 1 | same |
| Ran out of time | 1, `controller.py:250` in 1 of 1 | same |
| Limits in the rule text | 0.3 m, 0.1, 600 s | `E/requirements.json` R3, R4, R6 |
| Pause speed in the audit note | 10 m/s | `docs/security/SIM-AUDIT-2026-11-06.md` item 2 |

## What held up, the AI fix, what needs a person

| On the page | Value | Source |
|---|---|---|
| Guard blind above fan speed | 0.896 | `docs/security/SIM-AUDIT-2026-11-06.md` item 6; `E/diagnosis.json` `guard.blind_from_speed_exact` |
| Estimate read safe at each time it came off | 9 | `E/diagnosis.json` `pressure_lead.detach_estimate_above_guard_while_true_below` |
| True-pressure re-runs; came off with estimate and with true pressure | 29; 9, 8 | `E/diagnosis.json` `oracle` |
| Patch: suction while cleaning | 0.85 to 0.9 | `E/retest_PLAN.md` |
| New worlds | 104 | `E/retest_report.json` `fresh.n` |
| Passed before, after | 11, 17 | same, `fresh.A.pass`, `fresh.B.pass` |
| Failed before, after | 67, 60 | same, `fresh.A.fail`, `fresh.B.fail` |
| Normal runs passed before, after | 20 of 20, 20 of 20 | same, `controls` |
| Changed from failed to passed | 6 to pass: 3 from a slide, 3 from a false done | same, `per_world`, `better_by_change` |
| Changed from stalled to a battery stop, not a pass | 1 | same, `per_world`, `better_by_change` |
| Moved from a slide to a stall | 1 | same, `per_world`. The plan's ranking counts this as the same |
| Worse | 0 | same, `fresh.worse` |
| The report's "7 better" | 6 + 1, as above. The page gives the parts | same, `fresh.better` |
| Sim of this test | 0e36d3bf. An older test of the patch ran on aac6648b | `E/sim_of_each_run_set.json` |
| Removed the guard while cleaning, not applied | text | same, `conclusion`, `applied`, `blind_point` |
| Live AI try, small check run | 0 better, 0 worse, did not help | `E/live_fix_report.json` `tries[0].ab`, screen `policy/runs/app_v2_check/v3_live/09-fix-result.png` |
| Already stopped with suction at full | 5 of 9 | `E/diagnosis.json` `failure_types` detach `stopped_at_full_suction`, `follow_ups` F1 |

## Bounty

| On the page | Value | Source |
|---|---|---|
| Re-runs with a hidden change | three | `policy/bounty/README.md`, Steps |
| Twin moved most of the way back to normal | 25% of the distance left | `policy/bounty/README.md`, Validity control |
| Items left out of the Dubai run | 5 | `E/scenarios.json` `not_tested` |

## Numbers inside the app screen image

The screen is `app.html?recorded=1` at 1440x900, cropped at 796 px high: the Recorded run mode. Its counts are the Dubai counts above, read from `public/trials/worlds.json`, and `check_numbers.py` checks that file. Nothing ran live for this screen.

## For the owner to check

- The hero sentence is word for word from `policy/crashlab/loop.sh`. Its hash matches `chat_sha256` in `scenarios.json`. Which phrase leads to which group is our reading of each group's reason. The agent's file does not state it.
- The screen is cropped at 796 px high, to the same height as before.
- The gate judges only worlds the simulator can run. The product spec says any gap can go to a bounty. The page says a gap with no physics stays on the not-tested list. Decide which you want.
- The film is from a recorded run. `design/render/clip.mp4` does not name its run, so the page names none.
