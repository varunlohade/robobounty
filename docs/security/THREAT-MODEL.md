# CrashLab threat model (2026-11-06, design stage)

Written by the security-researcher agent (Claude Opus). Nothing is deployed. Basis: "proven" = run or read in code; "inferred" = design judgement.
No fresh agent refuted these findings. No scanner ran (gitleaks, osv-scanner and semgrep are not installed).

Limit we cannot fix: a policy-by-link result proves only what that endpoint did on that day. A human or a swapped model can sit behind the URL.

| # | Risk (basis) | Severity | Fix | Before demo |
|---|---|---|---|---|
| 1 | One resolver key pays instantly (inferred) | Critical | propose(resultHash), dispute window, finalize. Named arbiter. Key out of web and LLM processes. | Yes |
| 2 | `new Function` runs solver code, src/challenges/acme.ts:44 (PoC forged a pass) | Critical if kept | Remove compile() from server paths. | Yes |
| 3 | Pickle in lerobot.async_inference (sink proven; grpc absent) | Critical if reused | Own JSON-only client. Ban that module. | Yes |
| 4 | Scenes known in advance (stock list proven) | High | Derive scenes from keccak(companySalt, policyCommit, future blockhash). No stock states. Fresh re-test before finalize. | Yes |
| 5 | "Scene + seed replays" is false for a linked policy (proven: sampled noise, MuJoCo 3.8.1 vs 3.16.0) | High | Store scene, action log, hash chain, MuJoCo version. Resolver-signed roots on-chain. Never mix LIBERO with browser replay. | Yes |
| 6 | SSRF through policy URL (inferred) | High | Demo: host allowlist. Later: HTTPS, pin IP, block non-public IPs, no redirects, isolated process. | Yes |
| 7 | Stuck funds and payout griefing (docs + inferred) | High | Pull claim(), checks-effects-interactions, guard, one 6-decimal ERC-20 interface, refund after deadline. | Yes |
| 8 | Company rigs bounty or refunds early (rigging proven) | High | Lock until deadline + grace. Spec hash on-chain. Reference controller must pass at posting. | Yes |
| 9 | "New" failure is farmable (PoC: seeds 1, 1+2^32, 1.00001 replay the same) | High | Fingerprint (policy version, scene bucket, reason). Integer seeds, 3 of 3 jittered re-runs, reference must pass, payout cap. | Yes |
| 10 | Company MJCF upload (WASM proven; native not run) | High | Demo: curated robots only. Later: allowlist elements, hashed assets, capped worker. | Yes |
| 11 | Solver and human collude (inferred) | High | Deduct failure rewards from solver payout. Cap the pool. | Yes |
| 12 | World ID replay or sybil (docs; rental inferred) | High | One fixed action, UNIQUE(nullifier, action), bind wallet in signal, enforce on backend. | Yes |
| 13 | AI tester injection, unsafe BDDL (eval sink proven, bddl_utils.py:36) | High | LLM returns numeric JSON only. Clamp. Our template builds the scene. No tools or keys. Spend cap. | Yes |
| 14 | Action checks cover target only, src/sim/core.ts:154 (PoC) | Medium | Strict schema: exact fields, finite, in range. Violation fails the run. np.clip keeps NaN, so check first. | Yes |
| 15 | Huge or slow responses (inferred) | Medium | No Content-Encoding, byte cap, per-call and per-episode timeouts, one run per solver. | Yes |
| 16 | 0G receipts overclaimed (docs) | Medium | Call processResponse ourselves. Commit call count and hashes. State what receipts do not prove. | Yes |
| 17 | Solver proxies a rival's URL (inferred) | Medium | Endpoint signs a per-run challenge with payout wallet. | Cheap |
| 18 | Model load trusts Hub files (read, not run) | Medium; Critical for solver repos | HF_HUB_OFFLINE=1 after download, pin revision, lockfile, never load solver repos or init files. | Pin yes |
| 19 | Repo hygiene (proven) | Low | Ignore policy/runs and policy/.libero. Render library text with textContent. | No |

Unknown: replay across machines; native MuJoCo file access; MJCF parser memory bugs; World ID on-chain on Arc/Hedera; usable blockhash on Arc/Hedera; 0G trace id lookup; policy_preprocessor.json in the model repo.
