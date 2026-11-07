// Live checks of the API's refusals. Spends one 0.01 HBAR testnet payment to prove replay is refused.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { join } from "node:path";
import { x402Client, x402HTTPClient } from "@x402/core/client";
import { createClientHederaSigner } from "@x402/hedera";
import { ExactHederaScheme } from "@x402/hedera/exact/client";
import { HBAR_ASSET, HERE, NETWORK, PORT, loadKey, loadState } from "./lib.mjs";

const server = spawn(process.execPath, [join(HERE, "server.mjs")], { stdio: ["ignore", "ignore", "ignore"] });
const base = `http://127.0.0.1:${PORT}`;
const test = (scenario) => `${base}/x402/crash-test?scenario=${encodeURIComponent(scenario)}`;
try {
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await fetch(`${base}/.well-known/x402`).then((r) => r.ok, () => false)) break;
  }
  const state = loadState();
  const http = new x402HTTPClient(x402Client.fromConfig({
    schemes: [{ network: NETWORK, client: new ExactHederaScheme(createClientHederaSigner(state.agent, loadKey("testnet-agent"), { network: NETWORK })) }],
    spendControls: { allowedAssets: [{ network: NETWORK, asset: HBAR_ASSET }] },
  }));

  assert.equal((await fetch(test("../../etc/passwd"))).status, 404);
  assert.equal((await fetch(test("__proto__"))).status, 404);
  const quote = await fetch(test("nominal"));
  assert.equal(quote.status, 402);
  const required = http.getPaymentRequiredResponse((h) => quote.headers.get(h), await quote.json());
  assert.equal(required.accepts[0].amount, "1000000");
  console.log("402 quote ok; unknown scenarios 404");

  const junk = await fetch(test("nominal"), { headers: { "PAYMENT-SIGNATURE": "not-a-payment" } });
  assert.equal(junk.status, 402);
  assert.equal((await junk.json()).error, "bad payment header");
  console.log("junk payment refused");

  const headers = http.encodePaymentSignatureHeader(await http.createPaymentPayload(required));
  const cheap = await fetch(test("wet_dirty"), { headers });
  assert.equal(cheap.status, 402);
  assert.equal((await cheap.json()).error, "payment does not match this quote");
  console.log("0.01 HBAR payment refused on a 0.03 HBAR scenario");

  const paid = await fetch(test("nominal"), { headers });
  const body = await paid.json();
  assert.equal(paid.status, 200, JSON.stringify(body));
  assert.equal(body.result.simulated, true);
  console.log(`settled ${body.settlement.transaction}`);

  const replay = await fetch(test("nominal"), { headers });
  assert.equal(replay.status, 402);
  assert.equal((await replay.json()).error, "payment already used");
  console.log("replay refused");
} finally {
  server.kill();
}
