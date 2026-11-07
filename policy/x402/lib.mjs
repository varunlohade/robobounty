// Shared paths, testnet constants and read-only chain lookups. Testnet only, by construction.
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PrivateKey } from "@x402/hedera";

export const NETWORK = "hedera:testnet";
export const HBAR_ASSET = "0.0.0";
export const FACILITATOR = process.env.X402_FACILITATOR || "https://api.testnet.blocky402.com";
export const MIRROR = "https://testnet.mirrornode.hedera.com";
export const PORT = Number(process.env.X402_PORT || 7402);
export const HERE = dirname(fileURLToPath(import.meta.url));
export const POLICY = resolve(HERE, "..");
export const KEY_DIR = join(homedir(), ".crashlab-hedera");
const STATE_FILE = join(KEY_DIR, "state.json");

export const loadKey = (name) => PrivateKey.fromStringECDSA(readFileSync(join(KEY_DIR, `${name}.key`), "utf8").trim());

// Public ids only: agent account, merchant account, audit topic.
export const loadState = () => (existsSync(STATE_FILE) ? JSON.parse(readFileSync(STATE_FILE, "utf8")) : {});
export const saveState = (s) => writeFileSync(STATE_FILE, JSON.stringify(s, null, 1) + "\n", { mode: 0o600 });

// Two decimals at least, and never hides a smaller amount: 500000 -> "0.005", 2000000 -> "0.02".
export const hbar = (tinybars) => (Number(tinybars) / 1e8).toFixed(8).replace(/(\.\d\d\d*?)0+$/, "$1");

// "0.0.5@1700000000.000000042" -> "0.0.5-1700000000-000000042", the form the mirror node takes.
export const mirrorTxId = (id) => id.replace("@", "-").replace(/\.(\d+)$/, "-$1");

export const hashscanTx = (consensusTimestamp, id) =>
  `https://hashscan.io/testnet/transaction/${consensusTimestamp}?tid=${mirrorTxId(id)}`;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Waits for the mirror node to show the transaction. Returns null when it never appears.
export async function mirrorTx(id, tries = 25) {
  for (let i = 0; i < tries; i++) {
    const r = await fetch(`${MIRROR}/api/v1/transactions/${mirrorTxId(id)}`);
    if (r.ok) {
      const j = await r.json();
      const tx = (j.transactions || []).find((t) => !t.parent_consensus_timestamp) || j.transactions?.[0];
      if (tx) return tx;
    }
    await sleep(1500);
  }
  return null;
}
