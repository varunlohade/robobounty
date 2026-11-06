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
   - Company: it pays the bounty and its gas. A 1 USDC bounty cost 1.0063 on Arc, because gas is also USDC. Send 2.
   - Resolver and arbiter need no faucet now. The resolver held 17.94 and the arbiter 20 test USDC on 2026-11-07. One take costs the resolver about 0.0084.
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

1. **Company.** Open `login.html?seed=1`. Only this address shows the demo buttons. Press Demo company. Open Bounties. Press Connect wallet, and accept the connection and the Arc network. The page shows the address, the balance and "Arc testnet. Test USDC, not real money."
2. Press Post a bounty. The stored failure is already picked. Keep pay at 1. Press Post the bounty. This takes about 30 s, because the board replays every stored run.
3. Press Fund from my wallet. **Popup: approve. Popup: create bounty.** The Funded row shows both transaction links.
4. **Engineer.** Switch the wallet to account 2. Sign out. The plain login page has no demo buttons, so open `login.html?seed=1` again and press Demo engineer. Open Bounties. If the wallet line shows Connect wallet, press it and allow account 2. Press Save this wallet. **Popup: sign.** The side bar shows the wallet with "signature checked".
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

## Real Arc check, spends test USDC

    set -a; . ./.env; set +a
    node src/board/tools/check_wallet_arc.mjs

It runs this film path on Arc in headless Chrome. An injected wallet sends each request to Node, where `cast` signs with the `company` and `tester` keystores. No key enters the page. It reads each result from Arc with `cast`, and saves `design/arc-real/*.png`.

It spends 1 test USDC plus gas from `company`, which now holds 0.99. A new run needs more from the faucet and a new folder in the script. `--fork` rehearses on an anvil fork with RPC delay, and spends nothing. The fork swaps in a mock USDC, because Arc's USDC calls a native contract that anvil lacks.

## What the real run showed, 2026-11-07

The money path passed on contract `0xc3cc7807884049c97e024242d72be65b8811cfd8`, chain bounty 1. The engineer went from 0 to 1 test USDC, and the contract state is Claimed.

| Step | Transaction |
|---|---|
| Approve | https://explorer.testnet.arc.io/tx/0x03b87886d429c82caebe3e4f4768a4a7be3c27c3eb54a0eb7c2bdd6d79a7280e |
| Create bounty | https://explorer.testnet.arc.io/tx/0xf318f779f0ea1963fc9bc912c0c32e549a009cf530254ff25047181868d2fd8d |
| Propose | https://explorer.testnet.arc.io/tx/0x778f4c330166b2efaaa8d40565fc420e602fb6ae58a9be5add377c42925c7981 |
| Finalize | https://explorer.testnet.arc.io/tx/0x0acf3216b34457b30bcb4fd8c1ddcaf67fd8354a50283f077f4c89bd05cd14e6 |
| Payout | https://explorer.testnet.arc.io/tx/0x3bb10d1ba4fd9d3a7c9005dbddb1ecda89155ec96617fb52627d00c8343b75e5 |

Arc's real USDC, the agent's sends, the page's fee and the explorer links all worked.

**Two bugs that anvil hid, both from RPC delay.** A chain read takes about 0.4 s on the public RPC, and one balance read takes about 5 s on the server.

- The page's timers stacked up requests, and Fund from my wallet hung for over 90 s with no message. Timers now wait for their last read. The fork with delay showed the hang before the fix and none after. The real chain has not rerun this fix, because the company has too little USDC.
- The countdown showed 68 s on a 60 s window, because it trusted the age of the agent's file. It now compares the two clocks at one moment. Same evidence.

**RPC facts:**

- Gas is 18 decimals natively, and the USDC contract is 6. They are one balance, so the company's USDC falls by gas too. The page shows the 6-decimal value.
- The fee: the base was 20 Gwei and `eth_gasPrice` 25 to 32 Gwei. The page offers the larger of 40 Gwei and twice the gas price, with a 1 Gwei tip. It landed.
- Receipts: within about 1.2 s. Nonce `pending` and `latest` agree when idle.
- `eth_getLogs` refuses a range of 10,000 blocks, and accepts 1,000. The flow never calls it. It reads events from receipts.

## What the owner must still check with Rabby

The injected wallet cannot prove these:

- **The popups.** Connect, approve, create and sign, and how each reads on film.
- **Add and switch network.** Rabby's real answer to `wallet_addEthereumChain` and its error code for an unknown chain. The page expects 4902.
- **The fee.** Rabby may replace the page's fee. Under 20 Gwei, Arc drops the transaction with no error. If a step waits with no receipt, look at the fee in the popup first.
- **Account 2.** Whether the wallet shares account 2 with this page without asking. Step 4 says what to do if not.
- **A stuck agent's fallback.** Claim from my wallet needs gas, and an engineer at 0 USDC has none. The real run did not use it. The contract's claim has not run on Arc.
- **Rejection.** Reject as the company has not run on real Arc. It would lock 1 USDC until the refund opens, 7 days and 1 hour after funding.
- **Faucet limits.** Not tested.
