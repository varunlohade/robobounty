# FailureBounty

The contract pays testers for new robot failures, in a 6-decimal USDC-style token. It runs on a local test EVM only. Nothing here is deployed, and no human or outside firm has audited it.

## Run the tests

```
brew install foundry
cd contracts
forge install foundry-rs/forge-std@v1.17.0 --no-git
forge test
```

The result on 2026-11-06, with Foundry 1.9.0: 41 test functions pass, 0 fail. One of the 41 runs three invariants over 128 random runs of 64 calls. `forge test` uses an in-process EVM and its throwaway addresses. It needs no RPC, key or wallet.

As a check on the tests, we broke the contract in 17 ways, one at a time, on a temporary copy. The tests caught all 17. Examples: no reentrancy guard, no duplicate check, refund takes the whole balance.

## Rules

1. The company calls `createBounty` and pays the full cap. It names a resolver and an arbiter, and commits a spec hash. These values never change.
2. The company, resolver and arbiter must be three different addresses.
3. Until the deadline, the resolver calls `propose(bountyId, submitter, fingerprint, resultHash, isTopPrize)`. This call reserves the money.
4. The arbiter can call `reject` until the dispute window ends. A rejection frees the money, and the fingerprint can be proposed again.
5. After the window, anyone can call `finalize`. Only the named submitter can call `claim`.
6. Each fingerprint pays once per bounty.
7. The top prize replaces the per-failure amount for that one failure. A bounty has one live top prize.
8. After deadline plus grace, the company can call `refund`. It gets only money that no proposal holds.
9. Grace must be at least the dispute window, so each window ends before a refund opens.
10. No function accepts native value. The constructor rejects a token whose `decimals()` is not 6.

## Threat-model walk

Risk numbers come from `docs/security/THREAT-MODEL.md`.

| # | Risk | Status | What covers it, and what does not |
|---|---|---|---|
| 1 | One resolver key pays instantly | Covered in the contract | Propose, window, finalize and a named arbiter stop an instant payout. A stolen resolver key can still propose up to the cap, so the arbiter must watch. The key must stay out of web and LLM processes. The contract cannot enforce that. |
| 7 | Stuck funds, payout griefing | Mostly covered | Pull claim, checks-effects-interactions, a guard and safe token calls. A blocklisted winner blocks only their own payout. **Their money stays in the contract until the block lifts, because no function can move it.** A lost winner wallet has the same result. |
| 8 | Company rigs or refunds early | Partly covered | Funds lock until deadline plus grace. The spec hash is on-chain. The company cannot be the arbiter or the resolver. **The company can still control all three through different addresses.** "Reference must pass at posting" is an off-chain check. |
| 9 | Farmed "new" failures | Partly covered | One payout per fingerprint, and the cap. The contract treats a fingerprint as an opaque hash. The resolver must compute it well, with integer seeds and 3 of 3 re-runs. |
| 11 | Solver and human collude | Partly covered | The cap limits the loss. **Deducting failure rewards from a solver payout is not built.** This contract has no solver payout. It also does not stop a company that pays itself as a submitter. |
| 12 | World ID replay or sybil | Not covered | The contract has no World ID check. The backend must enforce it before the resolver proposes. See `docs/research/sponsors.md`. |
| 16 | 0G receipts overclaimed | Storage only | `resultHash` can commit to call counts and receipt hashes. The contract does not read or check them. |
| 17 | Solver proxies a rival's URL | Not covered | The endpoint challenge is off-chain work. `resultHash` can commit to the signed challenge. |

## Known limits

- The arbiter can reject everything. It is a trusted role, so testers must check who it is before they work.
- `MIN_DISPUTE_WINDOW` is 60 seconds, to suit a live demo. A real bounty needs hours or days.
- The token is fixed per deployment. This is one contract with many bounties, all in one token.
- We tested on the standard Foundry EVM, not on `arc-forge --network arc`. Arc docs say standard tools do not mimic Arc behaviour. Run this before any testnet step.
