# CrashLab bounty gate

A tester submits a world file that claims to break the robot. `gate.py` decides if it counts as a new, valid failure, and writes `verdict.json`. An accepted verdict holds the exact arguments for `propose` in `contracts/src/FailureBounty.sol`. The gate sends nothing on chain. It needs no key, account or network.

All results hold in this simulation only. The physics is hand-built and not calibrated to a real robot.

```
policy/.venv/bin/python policy/bounty/gate.py --world W.json --spec SPEC.json --paid PAID.json --salt-file SALT.hex --submitter 0x... [--seed N]
policy/.venv/bin/python policy/bounty/check_gate.py          # real runs, about 3 to 5 minutes
policy/.venv/bin/python policy/bounty/check_gate.py --fast   # the checks that need no sim
```

Output goes to `policy/runs/bounty/<submission hash>/`: `verdict.json`, plus `claim`, `rerun0`, `rerun1`, `rerun2` and `reference` folders. Each holds the normal run files, so `policy/highrise/replay.py` can check it. The gate never deletes a run. It uses at most 2 worker processes at low priority.

## Inputs

- **World:** a numeric world file. The file limit is 16 KB. The gate rejects a link, a repeated key, NaN, a huge number and any unknown field. `world.py` then validates it. Text from the file never reaches a verdict. Scene `elements` are rejected, because company limits have no rows for them.
- **Spec:** `bounty_id`, `limits` (`[lo, hi]` for every world field), `reference_world`, `salt_commit`, and `frozen` (the SHA-256 of each sim file and `gate.py`, plus the MuJoCo and numpy versions). `spec_hash` in the verdict is the value for `specHash` in `createBounty`.
- **Paid list:** a JSON list of fingerprints. Include pending proposals, not only paid ones. A rejected proposal should leave the list.
- **Salt:** at least 32 secret bytes in hex. The spec holds only its hash.

## Steps

1. Check the spec, paid list, salt, submitter and seed.
2. Validate the world, then check it against the company limits.
3. Hardware check: see "Validity control".
4. Check that the code on disk matches the frozen hashes. Each run checks this again.
5. Claim run: the exact world and the tester's seed. A pass, a safe hold or a sim breakdown ends the gate here, so a weak claim costs one run.
6. Fingerprint and duplicate check on the claim's failure type, so a paid failure costs no more runs.
7. Three re-runs with hidden jitter. All 3 must end in the same failure type as the claim.
8. Reference twin run. It must pass.
9. Write the result hash and the `propose` arguments.

## Jitter

Today the jitter comes from `HMAC-SHA256(salt, "crashlab.bounty.jitter.v1|" + submission hash + "|" + label)`. The submission hash covers the world, claim seed, submitter and bounty id. Each re-run gets its own seed. Each float field moves by up to 1% of its schema range, and stays inside the company limits.

The tester knows the code but not the salt, so the tester cannot compute the jitter. The company can, because it holds the salt. This covers the tester only. To let others check the jitter later, reveal the salt after the deadline. The spec's `salt_commit` holds the company to that salt.

**On-chain later** (threat model risk 4): `salt = keccak256(companySalt, policyCommit, blockhash(N))`, where N is a block after the tester commits the submission hash. The company reveals `companySalt` after N. This needs work that does not exist yet:

- FailureBounty has no commit step.
- The company could choose not to reveal, so the design needs a penalty for that.
- Arc: `PREVRANDAO` is always 0, and the docs do not state the direct `BLOCKHASH` opcode text. Hedera: `BLOCKHASH` behaviour is unknown.
- Validator bias on the blockhash is unknown on both chains. See `docs/research/sponsors.md`.

`propose` takes its hashes as opaque values, so SHA-256 fits today. Changing to keccak later changes only how the gate computes them.

## Validity control, and how weak it is

We have one controller and no gold-standard robot, so nothing here can prove that a world is fair. The gate runs two plain checks.

1. **Hardware check, no sim.** It compares full-fan adhesion on clean, flat glass with the outward wind load at peak wind, without turbulence. If the load wins, no controller can hold the robot on, so the gate rejects the world. Gusts under 2 s do not count, because the robot may ride them out.
2. **Reference twin, one sim run.** Each field moves back to 25% of its distance from the spec's `reference_world`. The twin must pass.

What these checks miss:

- The hardware check catches only one kind of impossible world. For example, it does not catch a robot too weak to grip, or dirt too heavy to clean.
- The twin shows that the robot works near this world. It says nothing about the world itself. A world that no robot could finish still gets accepted if its twin passes. For a world close to nominal, the twin is almost nominal and passes easily.
- The twin can also wrongly reject. This controller is fragile, so a real failure far from nominal can have a failing twin.
- The twin is one run, so a flaky twin result can decide a verdict.
- **The company limits do most of the real work.** Set them to conditions the robot should handle. The arbiter is the human check on the rest.
- The gate does not check that `reference_world` passes when the bounty opens (threat model risk 8). If it fails, or the controller is broken everywhere, the gate rejects every twin. `check_gate.py` runs the passing case only for its own fixture.

## Fingerprint

`sha256(version, controller.py hash, failure type, buckets)`. Buckets are 10 physical values, each cut into 3 to 6 bands: peak wind, wind into the wall, grip, full-fan pressure, joint leak, area, edge margin, usable battery, dirt per pad force, and ledge in the path. The table is `FACTORS` in `gate.py`.

We use these values and not the 29 raw fields, for two reasons:

- Raw fields give an endless grid. A tester could change `sun_level` or a far-away ledge and claim a new failure. These fields now have no effect.
- Different fields with the same physics collapse. Wet glass and condensation both land in the same grip band.

The seed is not in the fingerprint. A value close to a band edge could still flip a band, so the gate also computes every fingerprint within jitter reach of the world (1% of each field's range). A paid match in that set makes the world a duplicate. The set stays small because there are only 10 factors.

### Ways to farm this that still work

- **Walking the bands.** A real change of more than about 2% of a range across a band edge gets a new fingerprint. There are at most about 1.1 million cells for each failure type. A tester can walk one root cause through many cells, for example the same detach bug at 3 wind bands. Only the cap limits this. The fingerprint does not know root cause.
- **Failure type changes.** The same world region can give different first failures after small changes, and each type pays once.
- **Re-rolling a flaky world.** A new seed or a tiny change gives new jitter, so a world that fails 70% of the time passes the claim and 3 of 3 in about one try in four. The world still failed, but this breaks the meaning of "repeats". It also costs us sim time. Fix: limit submissions per verified human.
- **Sybils and collusion** (risks 11 and 12). The gate does not check World ID. A company can pay itself as a submitter.
- **Front-running.** The first submission wins a bucket. The gate has no commit step, so anyone who sees a world can submit it first.
- **A new controller opens every bucket.** The controller hash is in the fingerprint, and each new bounty starts empty. A controller edit with no effect needs a new spec, and the same worlds can pay again in the new bounty.
- **Unmodelled fields.** `gust_start_s`, `gust_count`, `mullion_spacing_m` and `mullion_offset_m` are not factors. A failure that really depends on them collapses into an old fingerprint, so an honest tester gets nothing. This errs against the tester, not the company.
- **Fixed band edges.** They are guesses, chosen by hand and not checked against failure data.
- **Knowing the code.** A tester can search locally for robust failures. We want this, and it is not an attack.

## Result hash

Start with `sha256(version, spec hash, submission hash)`. For each run in order, hash in the run name, seed, world hash, action chain head and label. The gate reads each chain head from the action log on disk and checks the log's chain first. `result_hash_of` in `gate.py` rebuilds it from `verdict.json`.

## What the gate does not check

World ID, collusion, the money left in the bounty and its deadline. `isTopPrize` is always false, because a top prize is the company's choice. Each verdict lists these in `not_checked`.

## Fixtures, and what the check proves

**We searched for the fixtures so that each one gives the wanted result.** So `check_gate.py` shows that the gate's logic does the right thing on these worlds. It does not measure how well the gate sorts worlds in general. All fixtures use a public salt, so their jitter is fixed.

How we found them, with a public test salt and the same jitter code as the gate:

- **Candidates:** we shuffled the failed trials of three earlier campaigns (`campaign_moderate_42`, `campaign_wind_41`, `campaign_dubai_v4`), then ran the first 12 of a planned 34. We stopped the rest early.
- **Failing:** `dubai_t0024` from a later robustness run of 8 worlds, chosen because it gave the same failure in 6 of 6 draws and its twin passed. Our first choice, `t0030`, was accepted, then repeated only 1 of 3 with a new seed. That run is why we changed the fixture.
- **Flaky:** `t0149` at seed 4200171. We tried 37 world and seed pairs and stopped at the first with the claim failing and the re-runs giving exactly 1 failure and 2 passes.
- **Twin fails:** `t0015`, seen in the 12 candidates.
- **Edge:** the failing world with `edge_margin_m` set to the 1.5 band edge, plus or minus 1e-6. It needed no search of its own.
- **Passing:** `nominal.json`, seed 2001. One seed, not searched.

### The less flattering numbers

Of the 12 candidates, with no selection among them: 7 not repeatable, 2 reference failed, 3 accepted. All 12 had already failed once in a campaign, and this is one draw each, so these are not rates for real submissions.

**3 of 3 lets flaky worlds through.** Two of those 3 accepted worlds were not stable: `t0030` and `t0091`. `t0091` gave `false_done` in only 4 of 6 later draws, so a world like it passes 3 of 3 about 30% of the time on one draw. An accepted verdict means "repeated on these three draws". It does not mean "always fails".

The search scripts and raw output are in `policy/runs/bounty/fixture_search/`. That folder is not in git.
