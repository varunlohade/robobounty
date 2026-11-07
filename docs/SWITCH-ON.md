# Switching on Arc testnet and 0G

Arc and 0G stay off until you set their values. With nothing set, the app runs as it does now, and the labels stay "Local ledger. Not on chain."

**Arc and 0G Storage are tested only on local mocks and anvil.** The 0G AI is tested on the real 0G Router. See "What is only mocked".

Testnet only, and new wallets only. Never use a wallet that holds real money. Never paste a private key anywhere.

See what is on at any time. This prints no secret and opens no connection:

    python3 scripts/sponsor_status.py

## Arc testnet: payouts in test USDC

To film real wallet popups, use docs/ARC-DEMO.md. It is the newer path, in which the server holds only the resolver and arbiter keys. The steps below are the older path, in which the server holds all four.

**1. Make four new wallets.** One command, once. Each `cast wallet new` asks for a password. Use the same one for all four.

    mkdir -m 700 ~/.crashlab-arc
    for role in company resolver arbiter tester; do cast wallet new ~/.crashlab-arc $role; done
    printf '%s' 'YOUR PASSWORD' > ~/.crashlab-arc/password; chmod 600 ~/.crashlab-arc/password

Put a space before the `printf` line, so your shell history skips it. Read each address with `cast wallet address --keystore ~/.crashlab-arc/company` (and the other three).

**2. Get test USDC** at https://faucet.circle.com. Choose Arc testnet. Do this for company, resolver and tester. On Arc, gas is paid in USDC, so each of them needs some. The arbiter needs some only if you will show a rejection.

**3. Add these to `.env`:**

    ARC_RPC_URL=https://rpc.testnet.arc.io
    ARC_WALLET_DIR=/Users/YOU/.crashlab-arc
    ARC_CAP_USDC=5

`ARC_CAP_USDC` is the most test USDC the board can put on chain across all bounties. Code checks it before any send.

**4. Tell steve to deploy.** He prints the plan first, and you approve it. The plan sends nothing:

    set -a; . ./.env; set +a
    policy/.venv/bin/python policy/bounty/arc_mirror.py deploy
    policy/.venv/bin/python policy/bounty/arc_mirror.py deploy --yes

Deploy costs only gas. It funds no bounty, and it writes `policy/runs/board/arc.json`.

**5. Start the watcher in its own terminal.** It holds the keys, and the web server never does:

    set -a; . ./.env; set +a
    policy/.venv/bin/python policy/bounty/arc_mirror.py serve

What it does with each accepted fix: it funds a chain bounty from company, proposes as resolver, waits for the dispute window, finalizes, and claims as tester. A fix rejected on the local ledger goes to the arbiter's reject. The bounty page shows each transaction with a link, and the label "Arc testnet. Not real money."

To do one pass by hand: `arc_mirror.py sync --bounty 1 --fix 1`.

Limits to know:

- All fixes pay one tester wallet, because a board tester is only a name with no wallet.
- The local ledger keeps its own numbers. A claim on chain does not press claim on the local ledger.
- The shortest dispute window is 60 s, set by the contract.

Ask at the Arc booth: "We wrote and tested the contract in Foundry. Does it qualify if we import it into Arc Studio?" The prize page says every Arc prize starts from Arc Studio. Whether this qualifies is unknown. Studio is at https://studio.arc.io. Arc's own `arc-forge` has not run on this contract.

## 0G Private Computer: the AI

Tested on the real 0G Router on 7 Nov 2026. A small select beside the robot name chooses who answers each chat, and you can change it between messages:

- **0G Private** (`ZG_MODEL`, tested with `glm-5.3`) is the default. It is sealed, and our own check of the TEE signature passes. We send `reasoning_effort: low` (`ZG_REASONING_EFFORT`). One timed call on the inspection prompt took 12 s at low and 67 s at the default.
- **0G Fast** (`ZG_FAST_MODEL`, now `gpt-4.1-nano`) answers in about 3 s a call. It is not private and not verified. It sends no private header, and we check no signature. It often gets things wrong: it refused "add snow" five times out of five.
- **Claude** uses the `claude` CLI, pinned to `claude-opus-5-5`.

A route shows only when its values are set. A recorded run shows no select. The status bar and the Details row name the route that answered.

**1.** Ask the 0G booth how to claim team credits. The method is unknown.

**2.** Sign in at https://pc.0g.ai. Add funds only if the credits do not cover the demo. That costs money, so you decide.

**3.** In Dashboard, API Keys, create an `sk-` key and set it to Private. It shows once.

**4.** Pick a model from the catalog at https://pc.0g.ai that has a TeeML provider and JSON mode.

**5.** Add these to `.env`:

    CRASHLAB_LLM=0g
    ZG_API_KEY=
    ZG_MODEL=
    ZG_FAST_MODEL=

**6.** Install the SDK, so we can check signatures ourselves. Then restart the app with the values loaded:

    npm --prefix policy/sponsors/zg ci --ignore-scripts
    set -a; . ./.env; set +a; npm run demo

The scenario agent and the engine agent now use the chosen route. Fixes and generated models still use Claude, because they need file and image tools.

Each call adds a row to `llm_calls.jsonl` in the run folder, with its request ID and receipt. The chat's Details row shows the same. The line says only what came back:

- "We checked the provider's TEE signature" means our own `processResponse` returned true.
- "The 0G Router reports" means only the Router's word.
- "not verified" means nothing came back. The answer is still used, and it says so.

A false check throws the answer away. Even a good check does not show that the signature covers the prompt.

If 0G fails or is slow, the chat says so and the step fails. To let Claude answer instead, set `ZG_FALLBACK_CLAUDE=1`. The chat then says that Claude answered. Prize rules may count a fallback against you.

**Compare with Claude.** This makes 68 real AI calls, so it spends credits. It stops without `--yes`:

    policy/.venv/bin/python scripts/compare_0g.py --yes

## 0G Storage: evidence

Testnet only (Galileo, chain 16602). Testnet tokens are free.

**1. Make one more new wallet:**

    mkdir -m 700 ~/.crashlab-zg
    cast wallet new ~/.crashlab-zg storage
    printf '%s' 'YOUR PASSWORD' > ~/.crashlab-zg/password; chmod 600 ~/.crashlab-zg/password

**2. Get test tokens** at https://faucet.0g.ai. The limit is 0.1 0G per wallet per day.

**3. Add these to `.env`:**

    ZG_WALLET_KEYSTORE=/Users/YOU/.crashlab-zg/storage
    ZG_WALLET_PASSWORD_FILE=/Users/YOU/.crashlab-zg/password

**4. Upload.** Pick one:

    set -a; . ./.env; set +a
    policy/.venv/bin/python policy/crashlab/zg_storage.py demo --pack window
    policy/.venv/bin/python policy/crashlab/zg_storage.py campaign --session SESSION --campaign c1
    policy/.venv/bin/python policy/crashlab/zg_storage.py bounty --id 1

Each uploads one JSON file, then downloads it again and compares the hash. The Data page shows the root hash. So does the bounty's public view. To check again: `zg_storage.py recheck --id 1`.

Held-back worlds and a bounty's hidden worlds stay out of every bundle. Post a bounty before you upload its campaign, because an uploaded campaign's passed worlds are public. The board refuses the other order.

## Local checks, no keys

    policy/.venv/bin/python policy/bounty/check_arc.py
    policy/.venv/bin/python policy/crashlab/check_zg.py

## What is only mocked

| Part | In the checks | Real and untested |
|---|---|---|
| Chain | Standard anvil with chain id 5042002 | Arc's EVM, gas in USDC, the 20 Gwei floor, the RPC |
| USDC | `MockUSDC` at Arc's address | Arc's USDC and its blocklist |
| Faucet, explorer links | Not called | Faucet limits, the links opening |
| 0G Storage | Mock SDK and a local folder | Upload, fees, indexer delay, the real Merkle root |
| Contract, budget, gate, keystores, ethers opening a cast keystore | Real | |
