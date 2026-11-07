# CrashLab x402: pay per crash test on Hedera

An AI-free test agent finds a crash test API, pays for each run in testnet HBAR, stops at its budget and writes a spend report. No human approves a payment. Entry for "AI Agents That Pay: x402 on Hedera".

All results are simulated. A result of `fail` means the simulated window robot failed in a hand-built MuJoCo model. It is not a real robot failure.

## Settled payment

Testnet, 0.02 HBAR, agent `0.0.11347656` to merchant `0.0.11347685`. Blocky402 (`0.0.7162784`) paid the network fee.

- Transaction ID: `0.0.7162784@1794012063.937691606`
- HashScan: https://hashscan.io/testnet/transaction/1794012072.275315104?tid=0.0.7162784-1794012063-937691606
- Audit topic: https://hashscan.io/testnet/topic/0.0.11347686

## Run it

From the repo root, after setup:

```
node policy/x402/run.mjs --budget 0.05
```

This starts the API, runs the agent and stops the API. It takes about 25 seconds. `reports/film-output.txt` holds the real output of the run above, and `reports/spend-report.json` holds its report.

## Setup

You need Node 26 and `policy/.venv` with `mujoco` 3.8.1 and `numpy` 2.2.6.

```
cd policy/x402 && npm ci
node setup.mjs                # makes a key, prints the address to fund
                              # send it testnet HBAR at https://portal.hedera.com/faucet
node setup.mjs                # makes the merchant account and the audit topic
node check_spend_policy.mjs   # offline checks of the spending rules
node check_server.mjs         # live refusal checks; spends 0.01 testnet HBAR
```

Setup keeps two testnet-only ECDSA keys in `~/.crashlab-hedera` (mode 600). The repo never holds a key, and no command prints one.

## Architecture

| File | Job |
|---|---|
| `server.mjs` | The API: `GET /.well-known/x402` (free list of scenarios and prices) and `GET /x402/crash-test?scenario=...` (paid) |
| `agent.mjs` | The agent: finds, picks, pays, checks the chain, logs to HCS, reports |
| `spend_policy.mjs` | Spending rules as plain code, with no AI and no chain access |
| `run.mjs` | The one command |
| `setup.mjs` | One-time testnet setup |

The packages are `@x402/hedera` and `@x402/core` (x402 v2, `exact` scheme) and `@hiero-ledger/sdk`. The facilitator is Blocky402 testnet, `https://api.testnet.blocky402.com`. Set `X402_FACILITATOR` to use another.

## Payment flow

1. The agent reads `/.well-known/x402` and ranks scenarios by stress per tinybar.
2. It requests a scenario with no payment. The API answers `402` with a price quote in the `PAYMENT-REQUIRED` header.
3. The agent checks the quote against its rules. If a rule fails, it skips the scenario and signs nothing.
4. The agent signs a `TransferTransaction` with the facilitator as fee payer, and sends the request again with a `PAYMENT-SIGNATURE` header.
5. The API checks that the payment matches this quote and has not been used, then asks the facilitator to verify it.
6. The API runs the simulation. If the simulation fails, the API does not settle, so the agent pays nothing.
7. The API asks the facilitator to settle, then returns the result with the transaction ID.
8. The agent reads the transaction from the mirror node. It counts the run as settled only when the chain shows `SUCCESS` and the exact amount moved from agent to merchant.
9. The agent writes the payment to the HCS topic and moves to the next scenario.

## Spending controls

The agent refuses a quote that breaks any of these rules:

- The run would pass the total budget (`--budget`).
- The price passes the per-call limit (`--max-per-call`, 0.03 HBAR by default).
- The merchant is not on the allowlist, or the asset or network is wrong.
- The quote differs from the listed price.

The agent counts a payment as spent when it signs. If a request dies, the budget stays spent and the agent stops, because that payment may still settle.

Each HCS message carries the sha256 of the message before it, so a reader can detect a change to the log. Only the agent's key can write to the topic.

## What is real and what is not

Real:

- The payments. They settle on Hedera testnet through Blocky402, and the agent confirms each one on the mirror node.
- The simulations. Each paid request runs `policy/highrise5/run_trial5.py` live, one at a time, in about 5 seconds or less. The API returns no stored results.
- The HCS audit log and the spending rules.

Not real, or not done:

- The money. This is testnet HBAR with no value. The flow does not use USDC, because the Circle faucet needs a person.
- The robot. Results come from a simulation, not hardware, and nobody has checked them against a real robot here.
- Public hosting. The API runs on `127.0.0.1`, and the agent needs its base URL (`--base`). The agent finds the scenarios and prices itself, but no registry or marketplace lists the API.
- Identity, reputation and agent-to-agent negotiation. None of these exist here.

The audit log does not hold the payments from `check_server.mjs`, because that check is not the agent. Its first run settled `0.0.7162784@1794012011.092658003`.
