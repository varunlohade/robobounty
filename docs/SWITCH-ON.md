# Switching on 0G, World ID and Arc

All three stay off until you set their env vars. With no keys, the app runs as before and its labels say "World ID not connected" and "Local ledger. Not on chain."

**Tested only on local mocks and anvil.** No real sponsor service has received a call from this code. See "What is only mocked".

Load a file into a shell with `set -a; . ./.env; set +a`. The names are in `.env.example`.

## Local check, no keys

    policy/.venv/bin/python policy/sponsors/check_sponsors.py
    node src/app/tools/check_live.mjs /tmp/out --sponsors-mock

The second needs vite running. Neither calls a sponsor.

## 0G

Owner steps, from `docs/research/sponsors.md`:

1. Ask the 0G booth how to claim team credits. The claim method is unknown.
2. Sign in at https://pc.0g.ai.
3. Add funds only if the credits do not cover the demo. This costs money, so you decide.
4. Create an `sk-` key and set it to Private. The dashboard shows it once.

Then:

1. Run `npm --prefix policy/sponsors/zg ci`. Without this SDK, each receipt says "no check".
2. Pick a model from `GET https://router-api.0g.ai/v1/models` with `"verifiability": "TeeML"` and JSON mode support.
3. In `.env`, set `CRASHLAB_LLM=0g`, `ZG_API_KEY` and `ZG_MODEL`.

Test: `policy/.venv/bin/python policy/sponsors/smoke.py 0g`. This makes one small real call, and it spends credits.

The status line names the backend used. With a key missing, calls use Claude and the line says so. A failed 0G call stops the step, and it does not fall back. `fix.py` still uses Claude, because it needs file tools.

Receipts go to `llm_receipts.jsonl` in the session's run folder. `processResponse` false refuses the answer. Null or a failed check keeps the answer and counts it as not checked.

A checked receipt shows that the provider's TEE signer signed the reply text. It does not show that the signature covers the prompt, that the app used the answer, or that the TEE has no flaws.

## World ID

Owner steps:

1. Create a team and app at https://developer.world.org. Save `app_id`, `rp_id` and `signing_key`. The key shows once.
2. Create the action `crashlab-tester-register`, with this exact name, in `staging` for the simulator. Add `production` if a real phone will scan.
3. For production, wait until the RP registration shows `registered`.

Then set the `WORLD_*` values in `.env`. `WORLD_ENVIRONMENT` is `staging` or `production`.

Test: `policy/.venv/bin/python policy/sponsors/smoke.py world`. This signs one request and sends nothing. Then verify once in the app, with the simulator.

Choices to check:

- The signal is the wallet. The server compares each `signal_hash` with IDKit's `hashSignal(wallet)`. The docs do not spell out this comparison, so we inferred it. Confirm it on the simulator first.
- Legacy proofs are off, because one human could then hold both a v3 and a v4 nullifier. A phone with only a v3 proof will fail. `WORLD_ALLOW_LEGACY=1` allows it and reopens that double registration.
- Whether `proofOfHuman` works with legacy proofs off: unknown. The docs' examples turn them on.

## Arc

Owner steps:

1. Ask the Arc booth: "We wrote and tested a contract in Foundry. Does it qualify if we import it into Arc Studio and build the app there?" Also ask if this project counts as Continuity.
2. Sign up at https://studio.arc.io.
3. Install Arc Foundry, then run `arc-forge test --network arc` in `contracts/`. This step has not run yet.
4. Create four new testnet wallets, each a keystore: company, resolver, arbiter, tester. Do not use Foundry's default accounts. The deploy script and resolver refuse them on Arc testnet.
5. Fund them from https://faucet.circle.com.

Then, with your approval for the deploy:

    policy/.venv/bin/python policy/sponsors/arc_spec.py --out policy/runs/arc_spec    # prints ARC_SPEC_HASH. Build this last: the spec freezes the sim and gate code.

    cd contracts && arc-forge script script/Deploy.s.sol:Deploy --rpc-url https://rpc.testnet.arc.io --broadcast \
      --keystore "$ARC_COMPANY_KEYSTORE" --password-file "$ARC_COMPANY_PASSWORD_FILE" --sender "$ARC_COMPANY_ADDRESS"

Set `ARC_USDC_ADDRESS=0x3600000000000000000000000000000000000000` and the deploy values first. Amounts are in 6-decimal base units. Fresh deploys give bounty id 1. Whether `arc-forge script` needs extra flags on Arc: unknown, because the Arc docs do not cover it.

Put the read values in `.env`, with `ARC_CAST_BIN=arc-cast`. Then start the resolver in its own shell, with only `.env.resolver` loaded plus the read values:

    policy/.venv/bin/python policy/sponsors/resolver.py serve

The web server turns Arc off if a keystore var reaches it.

Test: `policy/.venv/bin/python policy/sponsors/smoke.py arc`. This reads the chain and sends nothing.

**The tester's claim.** The contract pays only if the named submitter calls `claim`, so the resolver cannot claim. The tester runs this with the tester key:

    policy/.venv/bin/python policy/sponsors/resolver.py claim --fingerprint 0x...

**The arbiter's reject** uses the arbiter key, inside the window:

    arc-cast send "$ARC_BOUNTY_ADDRESS" "reject(uint256,bytes32,bytes32)" 1 <fingerprint> <reason hash> --rpc-url "$ARC_RPC_URL" --keystore "$ARC_ARBITER_KEYSTORE" --password-file "$ARC_ARBITER_PASSWORD_FILE"

By default, the resolver proposes only for a wallet with a stored World ID. `ARC_REQUIRE_WORLD_ID=0` turns that off, for testing Arc alone.

The resolver checks each verdict, but anyone who can write to its inbox can build one that passes. The arbiter and the dispute window are the check on that.

## What is only mocked

| Part | In the checks | Real and untested |
|---|---|---|
| 0G Router, `x_0g_trace`, `ZG-Res-Key` | Local mock | The real Router's replies, and JSON mode on the chosen model |
| `processResponse` | Mock SDK | The real SDK call |
| World ID verify and World App | Local mock, which checks no proof | Real proofs, the IDKit widget in the browser, the bridge |
| RP signing and `hashSignal` | Real IDKit code | |
| Chain | Standard anvil | Arc's EVM, gas in USDC, the 20 Gwei floor |
| USDC | `MockUSDC` at the Arc address | Arc's USDC and its blocklist |
| Contract, deploy script, resolver, gate, store | Real | |
