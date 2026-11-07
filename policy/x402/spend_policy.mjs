// The agent's spending rules, as plain code with no chain access. No AI decides a payment.

// Most stress per tinybar first; id breaks ties so the order is stable.
export function rank(scenarios) {
  const value = (s) => s.stress / Number(s.price_tinybars);
  return [...scenarios].sort((a, b) => value(b) - value(a) || a.id.localeCompare(b.id));
}

// Returns null when the agent may sign this quote, else the reason to refuse.
export function refuse({ quote, listed, limits, spent }) {
  if (!quote) return "no quote";
  if (quote.scheme !== "exact" || quote.network !== limits.network) return "wrong scheme or network";
  if (quote.asset !== limits.asset) return "asset not allowed";
  if (!limits.payTo.includes(quote.payTo)) return "merchant not on allowlist";
  const amount = BigInt(quote.amount);
  if (amount <= 0n) return "bad amount";
  if (amount !== BigInt(listed)) return "quote differs from listed price";
  if (amount > limits.perCall) return "over per-call limit";
  if (spent + amount > limits.budget) return "over budget";
  return null;
}
