// Pay-per-run crash test API. Order: quote, verify payment, simulate, settle, return.
// A failed simulation never settles, so nobody pays for a run that produced nothing.
import { createHash } from "node:crypto";
import { execFile } from "node:child_process";
import { createServer } from "node:http";
import { join } from "node:path";
import { x402ResourceServer, HTTPFacilitatorClient } from "@x402/core/server";
import { decodePaymentSignatureHeader, encodePaymentRequiredHeader, encodePaymentResponseHeader } from "@x402/core/http";
import { ExactHederaScheme } from "@x402/hedera/exact/server";
import { FACILITATOR, HBAR_ASSET, NETWORK, POLICY, PORT, loadState } from "./lib.mjs";

const { merchant } = loadState();
if (!merchant) throw new Error("run setup.mjs first");

// Fixed list: the query string only ever selects a key here, never a path.
const SCENARIOS = {
  nominal: { title: "Clean facade, calm air", world: "highrise/worlds/nominal.json", stress: 1, price: "1000000" },
  signage: { title: "Facade with signage", world: "highrise/worlds/samples/03_signage.json", stress: 2, price: "2000000" },
  vent_row: { title: "Row of vents", world: "highrise/worlds/samples/02_vent_row.json", stress: 3, price: "2000000" },
  dense_grid: { title: "Dense window grid", world: "highrise/worlds/samples/01_dense_grid.json", stress: 3, price: "3000000" },
  wet_dirty: { title: "Wet, dirty glass", world: "highrise/worlds/samples/07_wet_dirty.json", stress: 4, price: "3000000" },
};
const SEED = 7;
const NOTICE = "Simulated result from a hand-built MuJoCo model of the window robot. Not a real robot failure.";

const resourceServer = new x402ResourceServer(new HTTPFacilitatorClient({ url: FACILITATOR }));
resourceServer.register("hedera:*", new ExactHederaScheme());
await resourceServer.initialize();

const seen = new Set(); // replay guard on top of the facilitator's own check
let busy = false; // one simulation at a time

function simulate(scenario) {
  const env = { ...process.env, OMP_NUM_THREADS: "1", PYTHONDONTWRITEBYTECODE: "1" };
  const args = ["-n", "19", join(POLICY, ".venv/bin/python"), join(POLICY, "highrise5/run_trial5.py"), join(POLICY, scenario.world), "--seed", String(SEED)];
  return new Promise((resolve, reject) => {
    execFile("nice", args, { env, timeout: 60_000, maxBuffer: 1 << 22 }, (err, stdout) => {
      if (err) return reject(new Error("simulation failed"));
      const r = JSON.parse(stdout);
      resolve({
        source: "live simulation, run for this request", simulated: true, notice: NOTICE, seed: SEED,
        outcome: r.outcome, failure: r.failure, fired: r.fired, coverage: r.coverage, sim_time_s: r.time_s,
        steps: r.steps, wall_s: r.wall_s, sim_label: r.label, world_sha256: r.world_sha256, action_chain_head: r.action_chain_head,
      });
    });
  });
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, { "content-type": "application/json", ...headers });
  res.end(JSON.stringify(body));
}

async function crashTest(req, res, url, id) {
  const scenario = Object.hasOwn(SCENARIOS, id) ? SCENARIOS[id] : null;
  if (!scenario) return send(res, 404, { error: "unknown scenario" });

  const resource = { url: url.href, description: `CrashLab simulated crash test: ${id}`, mimeType: "application/json" };
  const [wanted] = await resourceServer.buildPaymentRequirements({
    scheme: "exact", payTo: merchant, network: NETWORK, maxTimeoutSeconds: 120,
    price: { asset: HBAR_ASSET, amount: scenario.price },
  });
  const quote = async (error) => {
    const required = await resourceServer.createPaymentRequiredResponse([wanted], resource, error);
    send(res, 402, required, { "PAYMENT-REQUIRED": encodePaymentRequiredHeader(required) });
  };

  const header = req.headers["payment-signature"];
  if (!header) return quote();

  let payment;
  try {
    payment = decodePaymentSignatureHeader(header);
  } catch {
    return quote("bad payment header");
  }
  const a = payment.accepted || {};
  if (a.amount !== wanted.amount || a.asset !== wanted.asset || a.payTo !== wanted.payTo || a.network !== wanted.network || a.scheme !== wanted.scheme) {
    return quote("payment does not match this quote");
  }
  const fingerprint = createHash("sha256").update(JSON.stringify(payment.payload)).digest("hex");
  if (seen.has(fingerprint)) return quote("payment already used");
  if (busy) return send(res, 503, { error: "a simulation is running; nothing charged" }, { "retry-after": "10" });

  busy = true;
  seen.add(fingerprint);
  try {
    const verified = await resourceServer.verifyPayment(payment, wanted);
    if (!verified.isValid) {
      seen.delete(fingerprint);
      return quote(`verify failed: ${verified.invalidReason}`);
    }
    let result;
    try {
      result = await simulate(scenario);
    } catch (e) {
      seen.delete(fingerprint);
      return send(res, 503, { error: e.message, charged: false });
    }
    const settled = await resourceServer.settlePayment(payment, wanted);
    if (!settled.success) return quote(`settle failed: ${settled.errorReason}`);
    return send(res, 200, { scenario: id, title: scenario.title, result, settlement: settled }, { "PAYMENT-RESPONSE": encodePaymentResponseHeader(settled) });
  } finally {
    busy = false;
  }
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
    if (req.method === "GET" && url.pathname === "/.well-known/x402") {
      return send(res, 200, {
        name: "CrashLab pay-per-run crash test", notice: NOTICE, network: NETWORK, asset: HBAR_ASSET, payTo: merchant, facilitator: FACILITATOR,
        endpoint: "/x402/crash-test?scenario={id}",
        scenarios: Object.entries(SCENARIOS).map(([id, s]) => ({ id, title: s.title, stress: s.stress, price_tinybars: s.price })),
      });
    }
    if (req.method === "GET" && url.pathname === "/x402/crash-test") return await crashTest(req, res, url, url.searchParams.get("scenario"));
    return send(res, 404, { error: "not found" });
  } catch (e) {
    console.error("server error:", e.message);
    if (!res.headersSent) send(res, 500, { error: "server error" });
  }
}).listen(PORT, "127.0.0.1", () => console.error(`listening on 127.0.0.1:${PORT}`));
