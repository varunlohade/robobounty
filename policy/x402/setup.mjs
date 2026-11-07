// One-time testnet setup. Safe to run again: it skips what exists. Never prints a private key.
// 1. Agent key and account. 2. Merchant account that receives payments. 3. HCS audit topic.
import { existsSync, mkdirSync, chmodSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { AccountCreateTransaction, Client, Hbar, PrivateKey, TopicCreateTransaction } from "@hiero-ledger/sdk";
import { KEY_DIR, MIRROR, loadKey, loadState, saveState } from "./lib.mjs";

function ensureKey(name) {
  mkdirSync(KEY_DIR, { recursive: true, mode: 0o700 });
  const file = join(KEY_DIR, `${name}.key`);
  if (!existsSync(file)) writeFileSync(file, PrivateKey.generateECDSA().toStringRaw() + "\n", { mode: 0o600 });
  chmodSync(file, 0o600);
  return loadKey(name);
}

const agentKey = ensureKey("testnet-agent");
const evm = "0x" + agentKey.publicKey.toEvmAddress();
const account = await (await fetch(`${MIRROR}/api/v1/accounts/${evm}`)).json();
if (!account.account) {
  console.log(`Fund this address at https://portal.hedera.com/faucet then run again: ${evm}`);
  process.exit(2);
}

const state = loadState();
state.agent = account.account;
state.agent_evm = evm;
const client = Client.forTestnet().setOperator(state.agent, agentKey);

// The agent pays for this first transaction with its own key, which also completes the
// hollow account the faucet made. After this the facilitator pays payment fees.
if (!state.merchant) {
  const merchantKey = ensureKey("testnet-merchant");
  const tx = await new AccountCreateTransaction().setECDSAKeyWithAlias(merchantKey).setInitialBalance(new Hbar(0)).execute(client);
  state.merchant = (await tx.getReceipt(client)).accountId.toString();
}
if (!state.topic) {
  const tx = await new TopicCreateTransaction().setTopicMemo("CrashLab agent spend audit (testnet)").setSubmitKey(agentKey.publicKey).execute(client);
  state.topic = (await tx.getReceipt(client)).topicId.toString();
}
saveState(state);
client.close();
console.log(`agent ${state.agent} (${evm})  merchant ${state.merchant}  audit topic ${state.topic}`);
