// Offline checks of the spending rules. Run: node check_spend_policy.mjs
import assert from "node:assert/strict";
import { rank, refuse } from "./spend_policy.mjs";

const limits = { network: "hedera:testnet", asset: "0.0.0", payTo: ["0.0.9"], perCall: 5n, budget: 7n };
const quote = { scheme: "exact", network: "hedera:testnet", asset: "0.0.0", payTo: "0.0.9", amount: "3" };
const ask = (over = {}, spent = 0n, listed = "3") => refuse({ quote: { ...quote, ...over }, listed, limits, spent });

assert.equal(ask(), null);
assert.equal(ask({}, 4n), null, "exactly reaches the budget");
assert.equal(ask({}, 5n), "over budget");
assert.equal(ask({ payTo: "0.0.666" }), "merchant not on allowlist");
assert.equal(ask({ asset: "0.0.429274" }), "asset not allowed");
assert.equal(ask({ network: "hedera:mainnet" }), "wrong scheme or network");
assert.equal(ask({ amount: "4" }), "quote differs from listed price");
assert.equal(ask({ amount: "6" }, 0n, "6"), "over per-call limit");
assert.equal(ask({ amount: "0" }, 0n, "0"), "bad amount");
assert.equal(refuse({ quote: null, listed: "3", limits, spent: 0n }), "no quote");
assert.deepEqual(rank([
  { id: "b", stress: 1, price_tinybars: "1" },
  { id: "a", stress: 1, price_tinybars: "1" },
  { id: "c", stress: 4, price_tinybars: "2" },
]).map((s) => s.id), ["c", "a", "b"]);
console.log("spend policy checks pass");
