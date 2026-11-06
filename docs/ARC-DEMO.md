# Filming the bounty on Arc testnet

This is the shortest path to a film with real wallet popups and real transactions. Test USDC only. It is not real money.

**What is real on Arc:** the deposit, the proposal, the dispute window, the finalize and the payout.

**What is recorded:** the gate's result. The film uses one stored proof, from a real run of the same fix on the same worlds. The page says "Recorded proof" and "The result comes from a recorded batch. The chain transactions are real." Say the same in the film. Results stay simulated.

## Who holds what

| Role | Wallet | Popups |
|---|---|---|
| Company | Your browser wallet, account 1 | Connect, switch network, approve, create bounty |
| Engineer | Your browser wallet, account 2 | Connect, sign once |
| CrashLab agent (resolver) | `~/.crashlab-arc/resolver`, on the server | None. It proposes, finalizes and pays |
| Arbiter | `~/.crashlab-arc/arbiter`, on the server | None. It sends a rejection the company signed |

The contract lets only the arbiter reject, and the company cannot be its own arbiter. So the company signs in its wallet, and the server's arbiter key sends. The `company` and `tester` keystores in that folder stay unused.

The agent's code decides from the gate's result. No AI decides a payout.

## Owner steps, once

1. In MetaMask or Rabby, make two new accounts. Name them Company and Engineer. Never use an account that holds real money.
2. At https://faucet.circle.com, choose Arc testnet, and send test USDC to:
   - Company: it pays the bounty and its gas. A 1 USDC bounty needs a little more than 1.
   - Resolver and arbiter need no faucet now. Each held 20 test USDC when this was written, for gas.
   - Engineer needs nothing, so the film shows the balance rising from 0.
3. Add these to `.env`:

       ARC_RPC_URL=https://rpc.testnet.arc.io
       ARC_WALLET_DIR=/Users/varun/.crashlab-arc
       ARC_CAP_USDC=5

4. Steve deploys. The first command prints the plan and sends nothing. The owner approves it, then the second sends. It costs gas only.

       set -a; . ./.env; set +a
       policy/.venv/bin/python policy/bounty/arc_wallet.py deploy --root "$PWD/policy/runs/film"
       policy/.venv/bin/python policy/bounty/arc_wallet.py deploy --root "$PWD/policy/runs/film" --yes

Do not run `arc_mirror.py serve` as well. It is the older path, in which the server holds every key.

## Each take

    set -a; . ./.env; set +a
    npm run demo -- --recorded --arc --board-root "$PWD/policy/runs/film"

This starts the four servers and the agent. If the agent cannot start, it prints why, and nothing starts.

A failure group posts once per board folder. For a new take, make a new folder with the same contract:

    mkdir policy/runs/film2 && cp policy/runs/film/arc.json policy/runs/film2/

Then pass `--board-root "$PWD/policy/runs/film2"`.

## The film, about 2 minutes

1. **Company.** On the login page, press Demo company. Open Bounties. Press Connect wallet, and accept the connection and the Arc network. The page shows the address, the balance and "Arc testnet. Test USDC, not real money."
2. Press Post a bounty. The stored failure is already picked. Keep pay at 1. Press Post the bounty. This takes about 30 s, because the board replays every stored run.
3. Press Fund from my wallet. **Popup: approve. Popup: create bounty.** The Funded row shows both transaction links.
4. **Engineer.** Switch the wallet to account 2. Sign out, and press Demo engineer. Press Save this wallet. **Popup: sign.** The side bar shows the wallet with "signature checked".
5. Press Submit a fix, Use the stored good fix, then Run check, then simulation. The recorded proof still replays the stored runs, which takes about 30 s.
6. The CrashLab agent proposes. A 60 s countdown runs on the Dispute window row. Open a link in the explorer here if you want.
7. The agent finalizes and pays. The Paid row shows its link, and the engineer's balance rises by 1 test USDC, read from the chain. The engineer presses nothing.

To film a rejection, press Reject as the company during the window, with the funding wallet connected. **Popup: sign.** The arbiter sends the rejection, and the page shows its link.

## If something goes wrong

| On screen | Meaning |
|---|---|
| No browser wallet found | Install MetaMask or Rabby, then reload |
| Your wallet is on another network | Press Switch network |
| You rejected ... | You pressed reject in the wallet. Nothing moved. Press the button again |
| ... reverted on chain | The transaction failed, and the page does not mark the step as done |
| ... ARC_CAP_USDC | This board's limit is used up. Raise it in `.env`, or use a new board folder |
| A red line under the steps | The agent's message, such as too little gas. It tries again every 2 s |

If the agent stays stuck on a finalized fix, the engineer gets a Claim from my wallet button. The contract's `claim` still works, so a stuck agent cannot trap the money.

## Local check, no keys and no Arc call

    node src/board/tools/check_wallet.mjs

It runs the whole flow on anvil with a test wallet in headless Chrome. It uses anvil's public dev accounts on the local chain only, and the server refuses those accounts on Arc.

## What only anvil has shown

The whole flow ran on anvil with a mock USDC at Arc's address. Real Arc may differ here:

- A real wallet's popups, and how it treats the fee the page suggests. Arc drops any transaction under 20 Gwei with no error, so the page sets the fee.
- Arc's real USDC contract, including its blocklist.
- Explorer links opening on `explorer.testnet.arc.io/tx/`.
- Faucet limits.
