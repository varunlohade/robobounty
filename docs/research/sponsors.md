# Sponsor research: Arc or Hedera, 0G, World ID

Research date: 2026-11-06. We read official docs and the prize page. We also made one read-only call to the Hedera mirror node. We created no account, key or wallet, and we deployed nothing.

Each claim has a source URL or says **unknown**. Submissions close Sat 7 Nov 09:00, and each team can pick at most 3 partners (`~/ethglobal-mumbai-research/03-ethglobal-mumbai.md`).

## Decision needed from the owner

**Use Arc, if Arc confirms that a contract written outside Studio qualifies.** Ask at the Arc booth first (step 1 below). If Arc says no, there are two choices: rebuild the contract in Arc Studio, or deploy to Arc for the demo and give up the Arc prize. Do not move to Hedera for the prize, because no open Hedera track fits this contract.

## Arc versus Hedera

| Question | Arc testnet | Hedera testnet |
|---|---|---|
| EVM | Osaka baseline. Most contracts deploy unchanged. [evm-differences](https://docs.arc.io/arc/references/evm-differences) | Pectra with changes. [deploying](https://docs.hedera.com/evm/development/deploying) |
| USDC | ERC-20 interface at `0x3600000000000000000000000000000000000000`, 6 decimals. [contract-addresses](https://docs.arc.io/arc/references/contract-addresses.md) | Token `0.0.429274`, a Hedera token. [Circle](https://www.circle.com/multi-chain-usdc/hedera). 6 decimals, and it has a freeze key. [mirror node](https://testnet.mirrornode.hedera.com/api/v1/tokens/0.0.429274) |
| Gas | Paid in USDC. Native view is 18 decimals on the same balance. Minimum base fee is 20 Gwei. [gas-and-fees](https://docs.arc.io/arc/references/gas-and-fees.md) | Paid in HBAR. `msg.value` is in tinybars. [deploying](https://docs.hedera.com/evm/development/deploying) |
| Extra setup | None in the docs we read | The contract and each winner must associate with the token, or transfers fail. EVM tools cannot set auto-association at deploy. [Hedera llms-full](https://docs.hedera.com/llms-full.txt). FailureBounty has no associate call, so **it needs a code change for Hedera**. |
| Faucet | [faucet.circle.com](https://faucet.circle.com/). Arc Studio also has a built-in faucet. [arc-studio](https://docs.arc.io/ai/arc-studio.md). Limits: unknown. | HBAR: [portal.hedera.com/faucet](https://portal.hedera.com/faucet). USDC: Circle links a testnet faucet. Hedera in its list: unknown. |
| Explorer, RPC | [explorer.testnet.arc.io](https://explorer.testnet.arc.io), `https://rpc.testnet.arc.io`, chain 5042002. [connect-to-arc](https://docs.arc.io/arc/references/connect-to-arc.md). Other sites list older hosts. Use the Arc docs. | [hashscan.io/testnet](https://hashscan.io/testnet), `https://testnet.hashio.io/api`, chain 296. [Hedera llms-full](https://docs.hedera.com/llms-full.txt) |
| Blockhash | EIP-2935 history "behaves as on Ethereum". `PREVRANDAO` is always 0. Direct `BLOCKHASH` opcode text: not stated. [evm-differences](https://docs.arc.io/arc/references/evm-differences) | `BLOCKHASH` behaviour: unknown in the pages we read. `block.number` is a record file index. Randomness comes from system contract `0x169`. [deploying](https://docs.hedera.com/evm/development/deploying) |
| Validator bias on blockhash (threat-model risk 4) | Unknown | Unknown |
| Prize fit | $3,000 "Best Smart Contracts with Advanced Stablecoin Logic". It names "conditional escrow with onchain dispute and automatic release". [prizes](https://ethglobal.com/events/mumbai/prizes) | Tracks are x402 payments, tokenization, and "No Solidity". None fits. A $1,500 Continuity track exists. [prizes](https://ethglobal.com/events/mumbai/prizes) |
| World ID on-chain | Satellite listed for Arc production only. [on-chain](https://docs.world.org/world-id/idkit/onchain-verification) | Not listed |

**Why Arc:**
1. The prize text describes this contract.
2. Winners need only USDC, not a second gas token.
3. The contract needs no association code. Hedera would need a code change plus an extra step for each winner.
4. On Arc, the blocklist reverts a transfer at runtime, which our pull claim already handles. [evm-differences](https://docs.arc.io/arc/references/evm-differences)

**The main risk with Arc:** "Every Arc prize requires using Arc Studio as the starting point." The track says "write, test, and deploy smart contracts in Arc Studio", and needs a shareable Studio project URL. It also needs Studio in the demo, a working frontend and backend, an architecture diagram and a video. [prizes](https://ethglobal.com/events/mumbai/prizes)

We wrote this contract in Foundry, not Studio. Studio can build a frontend on a deployed contract, and its home page shows a "From GitHub" start. [arc-studio](https://docs.arc.io/ai/arc-studio.md), [studio.arc.io](https://studio.arc.io). Whether this qualifies is **unknown**.

### Arc steps for the owner

1. Ask the Arc booth: "We wrote and tested a contract in Foundry. Does it qualify if we import it into Arc Studio and build the app there?" Also ask whether this project counts as Continuity. That eligibility is unknown.
2. Sign up at [studio.arc.io](https://studio.arc.io). Usage limits apply. [troubleshooting](https://docs.arc.io/ai/arc-studio-troubleshooting.md)
3. Install Arc Foundry from its [releases page](https://docs.arc.io/arc/tutorials/install-arc-foundry.md). Then run `arc-forge test --network arc` in `contracts/`. Steve can run this step without any key.
4. Create four separate testnet wallets, each with no real funds: company, resolver, arbiter, tester. Keep the resolver key out of web and LLM processes.
5. Fund the wallets from the faucet, then approve the deploy. Use the Arc USDC address above as the constructor argument.
6. Do not use the Foundry default test accounts on Arc testnet. Arc seeds `0x70997970C51812dc3A010C7d01b50e0d17dc79C8` as blocklisted. That address is useful for one demo of the blocklist path. [contract-addresses](https://docs.arc.io/arc/references/contract-addresses.md)

## 0G Private Computer

**How a call works.** Send an OpenAI-style request to `https://router-api.0g.ai/v1/chat/completions` with a `sk-` bearer key. Add `"verify_tee": true` to the body. [quickstart](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/quickstart.md), [verifiable-execution](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/features/verifiable-execution)

**Set the trust mode.** A request with no trust mode can go to any provider, including `standard` ones. Set the key to Private in the dashboard, or send the header `X-0G-Provider-Trust-Mode: private`. [privacy](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/privacy.md)

**What comes back.** Every response has `x_0g_trace` with `request_id`, `provider` and `billing`. With `verify_tee`, it also has `tee_verified`. [llms-full](https://docs.0g.ai/llms-full.txt)

**What proof it gives.**
- `tee_verified` only says that the Router reports a good check. The Router does not return the raw signature.
- For our own check, call `broker.inference.processResponse(provider, chatID)` from `@0gfoundation/0g-compute-ts-sdk`. The chat ID comes from the `ZG-Res-Key` header, or else the body `id`. It returns true, false, or null (no verifiable TEE service).
- The check is an EIP-191 signature from the provider's TEE signer over the response text. [verifiable-execution](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/features/verifiable-execution)
- This fits threat-model risk 16: call `processResponse` ourselves, and treat null or false as not verified.

**What it does not prove.** Whether the signature covers the prompt: unknown. It does not show that our app used the answer. It also does not show that a TEE is free of flaws. Looking up a past call by `request_id`: unknown.

**What the owner must do.**
1. Ask the 0G booth how to claim team credits. The prize page says each team gets them. The claim method is unknown. [prizes](https://ethglobal.com/events/mumbai/prizes)
2. Sign in at [pc.0g.ai](https://pc.0g.ai) with a wallet, or with a social login that makes an embedded wallet. [quickstart](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/quickstart.md)
3. Add funds only if the credits do not cover the demo. Sources conflict on a deposit: the quickstart says deposit, and a [blog post](https://0g.ai/blog/0g-private-computer) says no minimum. This costs money, so the owner decides.
4. Create a `sk-` key, set it to Private, and put it in `.env`. The dashboard shows it once.
5. Give steve the go-ahead for `llm.py` backend B (`docs/PLAN.md`). `processResponse` also needs a wallet object, and the docs say any wallet works because it only reads. [verifiable-execution](https://docs.0g.ai/developer-hub/building-on-0g/compute-network/router/features/verifiable-execution)

**Prize fit.** "Build with 0G PC" needs inference in the main flow with request IDs, and rejects AI calls that nobody would miss. "Physical AI" needs a 0G call in the decision loop, a log on 0G Storage with a request ID per decision, and a real safe-stop. A fallback that fakes the decision disqualifies the entry. Both need a demo video under 3 minutes. [prizes](https://ethglobal.com/events/mumbai/prizes)

## World ID

**Recommendation: verify on the server, not on-chain.** The docs list an on-chain 4.0 verifier on World Chain (production and staging) and on Arc (production only). They list no Arc testnet address and no Hedera address. [on-chain](https://docs.world.org/world-id/idkit/onchain-verification). The prize accepts "on the server or onchain as appropriate". [prizes](https://ethglobal.com/events/mumbai/prizes). FailureBounty stays free of World ID code.

**Flow.**
1. The backend signs each request with the RP signing key, and returns `sig`, `nonce`, `created_at` and `expires_at`. Never sign on the client. [integrate](https://docs.world.org/world-id/idkit/integrate)
2. The client opens the IDKit widget with `app_id`, `action`, `rp_context` and a preset that holds the signal.
3. The backend forwards the result unchanged to `POST https://developer.world.org/api/v4/verify/{rp_id}`. It checks for `success === true` and the expected environment.
4. The backend stores the nullifier as `NUMERIC(78,0)` with `UNIQUE(nullifier, action)`.
5. The resolver proposes only for a wallet that has a stored verification. This is the link to the contract.

**Two design points.**
- A 4.0 uniqueness proof is one-time per action for each user. [llms-full](https://docs.world.org/llms-full.txt). So verify once when a tester registers, not once per failure. Otherwise a tester could submit only one failure.
- Use the payout wallet as the signal (threat-model risk 12). The docs say the backend "should enforce the same value". The exact way to compare a signal after a v4 verify: unknown. Read the [verify reference](https://docs.world.org/world-id/idkit/integrate) before building.

**What the owner must create.**
1. A [Developer Portal](https://developer.world.org) team and app. Then save `app_id`, `rp_id` and `signing_key`. The key appears once. [llms-full](https://docs.world.org/llms-full.txt)
2. One action, for example `crashlab-tester-register`, in `staging` for the [simulator](https://simulator.worldcoin.org/). Add `production` if a real phone will scan.
3. For production, wait until the RP registration shows `registered`. Until then, verify returns `not_registered`. [llms-full](https://docs.world.org/llms-full.txt)
4. Choose the credential. The docs make `proofOfHuman` the default for sybil resistance. A staging action works only with the simulator. Having an Orb-verified phone on the team for a live demo: unknown.

**Prize needs.** "Best Use of IDKit" needs a success path, one other path (such as cancel or reject), a reason for the credential choice, and a short integration debrief. [prizes](https://ethglobal.com/events/mumbai/prizes)

## Partner picks

0G, World and Arc use all 3 picks. The Finalist track does not use a pick. [research file](../../../ethglobal-mumbai-research/03-ethglobal-mumbai.md)
