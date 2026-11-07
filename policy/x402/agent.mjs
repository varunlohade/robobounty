// CrashLab test agent: finds the API, picks scenarios, pays per run, stops at its budget,
// logs each payment to an HCS topic and writes a spend report. No human approves anything.
import { createHash } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { Client, TopicMessageSubmitTransaction } from "@hiero-ledger/sdk";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { createClientHederaSigner } from "@x402/hedera";
import { ExactHederaScheme } from "@x402/hedera/exact/client";
import { HBAR_ASSET, HERE, MIRROR, NETWORK, PORT, hashscanTx, hbar, loadKey, loadState, mirrorTx, mirrorTxId } from "./lib.mjs";
import { rank, refuse } from "./spend_policy.mjs";

const flag = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const tinybars = (h) => BigInt(Math.round(Number(h) * 1e8));
const BASE = flag("base", `http://127.0.0.1:${PORT}`);
const state = loadState();
const limits = {
  network: NETWORK, asset: HBAR_ASSET, payTo: [state.merchant],
  budget: tinybars(flag("budget", "0.07")), perCall: tinybars(flag("max-per-call", "0.03")),
};
const key = loadKey("testnet-agent");
const signer = createClientHederaSigner(state.agent, key, { network: NETWORK });
const http = new x402HTTPClient(x402Client.fromConfig({
  schemes: [{ network: NETWORK, client: new ExactHederaScheme(signer) }],
  spendControls: { allowedAssets: [{ network: NETWORK, asset: HBAR_ASSET, maxAmountPerPayment: limits.perCall.toString() }] },
}));
const hcs = Client.forTestnet().setOperator(state.agent, key);

// Each audit message carries the sha256 of the message before it, across runs too.
async function lastAuditHash() {
  const r = await fetch(`${MIRROR}/api/v1/topics/${state.topic}/messages?order=desc&limit=1`);
  const last = (await r.json()).messages?.[0];
  return last ? createHash("sha256").update(Buffer.from(last.message, "base64")).digest("hex") : "0".repeat(64);
}

const say = (tag, text) => console.log(`${tag.padEnd(7)}${text}`);
const started = new Date().toISOString();
let spent = 0n;
let prevHash = await lastAuditHash();
const runs = [];
const skipped = [];

async function audit(entry) {
  const message = JSON.stringify({ ...entry, prev: prevHash });
  const sent = await new TopicMessageSubmitTransaction().setTopicId(state.topic).setMessage(message).execute(hcs);
  const receipt = await sent.getReceipt(hcs);
  prevHash = createHash("sha256").update(message).digest("hex");
  return { sequence: Number(receipt.topicSequenceNumber), tx: sent.transactionId.toString() };
}

async function buy(scenario) {
  const url = `${BASE}/x402/crash-test?scenario=${encodeURIComponent(scenario.id)}`;
  const first = await fetch(url);
  if (first.status !== 402) throw new Error(`expected 402, got ${first.status}`);
  const required = http.getPaymentRequiredResponse((h) => first.headers.get(h), await first.json());
  const quote = required.accepts[0];
  const no = refuse({ quote, listed: scenario.price_tinybars, limits, spent });
  if (no) return { refused: no };
  say("402", `${scenario.id}: ${hbar(quote.amount)} HBAR quoted, in budget, paying`);

  // Count the money once signed, before the request. If the request dies, the payment may still settle,
  // so the budget stays spent and the agent stops.
  const payment = await http.createPaymentPayload({ ...required, accepts: [quote] });
  spent += BigInt(quote.amount);
  const paid = await fetch(url, { headers: http.encodePaymentSignatureHeader(payment) });
  const body = await paid.json();
  if (paid.status !== 200) throw new Error(`payment not accepted (${paid.status}): ${body.error || "no detail"}`);

  // Believe the chain, not the server.
  const id = body.settlement.transaction;
  const tx = await mirrorTx(id);
  const credited = tx?.transfers?.find((t) => t.account === quote.payTo && t.amount === Number(quote.amount));
  const debited = tx?.transfers?.find((t) => t.account === state.agent && t.amount === -Number(quote.amount));
  if (tx?.result !== "SUCCESS" || !credited || !debited) throw new Error(`chain does not confirm ${id}`);

  const run = {
    scenario: scenario.id, amount_tinybars: quote.amount, tx: id, hashscan: hashscanTx(tx.consensus_timestamp, id),
    fee_payer: id.split("@")[0], network_fee_tinybars: tx.charged_tx_fee, result: body.result,
  };
  say("paid", `${hbar(quote.amount)} HBAR settled, ${hbar(limits.budget - spent)} left, tx ${id}`);
  const r = body.result;
  say("sim", `${r.outcome}${r.failure ? " (" + r.failure + ")" : ""}, coverage ${(r.coverage * 100).toFixed(0)}%, simulated`);
  try {
    run.audit = await audit({ agent: state.agent, scenario: scenario.id, amount_tinybars: quote.amount, tx: id, spent_tinybars: spent.toString(), budget_tinybars: limits.budget.toString() });
    say("audit", `HCS ${state.topic} #${run.audit.sequence}`);
  } catch (e) {
    run.audit_error = e.message;
    say("audit", `failed: ${e.message}`);
  }
  return { run };
}

const discovery = `${BASE}/.well-known/x402`;
const catalog = await (await fetch(discovery)).json();
say("agent", `${state.agent}, budget ${hbar(limits.budget)} HBAR, max ${hbar(limits.perCall)} per call`);
say("find", `${catalog.scenarios.length} scenarios at ${discovery}`);

let failed = null;
for (const scenario of rank(catalog.scenarios)) {
  try {
    const { refused, run } = await buy(scenario);
    if (refused) {
      skipped.push({ scenario: scenario.id, price_tinybars: scenario.price_tinybars, reason: refused });
      say("skip", `${scenario.id}: ${hbar(scenario.price_tinybars)} HBAR, ${refused}`);
    } else runs.push(run);
  } catch (e) {
    failed = e.message;
    say("error", failed);
    break;
  }
}
hcs.close();

// Fees the agent itself paid for audit messages; the facilitator paid every payment fee.
let auditFees = 0;
for (const r of runs) {
  if (r.audit) auditFees += (await mirrorTx(r.audit.tx))?.charged_tx_fee || 0;
}
const report = {
  simulated_results_notice: catalog.notice, network: NETWORK, started, finished: new Date().toISOString(),
  agent: state.agent, merchant: state.merchant, audit_topic: state.topic, facilitator: catalog.facilitator,
  budget_tinybars: limits.budget.toString(), max_per_call_tinybars: limits.perCall.toString(), spent_tinybars: spent.toString(),
  settled_runs: runs.length, agent_paid_payment_fees_tinybars: runs.filter((r) => r.fee_payer === state.agent).reduce((n, r) => n + r.network_fee_tinybars, 0), agent_paid_audit_fees_tinybars: auditFees,
  runs, skipped, stopped_on_error: failed,
};
const dir = join(HERE, "reports");
mkdirSync(dir, { recursive: true });
writeFileSync(join(dir, "spend-report.json"), JSON.stringify(report, null, 1) + "\n");

say("spent", `${hbar(spent)} of ${hbar(limits.budget)} HBAR, ${runs.length} settled, ${skipped.length} skipped`);
say("report", "reports/spend-report.json");
if (runs[0]) say("proof", runs[0].hashscan);
process.exit(failed || !runs.length ? 1 : 0);
