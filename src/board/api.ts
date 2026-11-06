// The board server. Every bounty, fix and number on the page comes from here. Nothing is sample data.
const BASE = `http://127.0.0.1:${import.meta.env.VITE_BOARD_PORT ?? 5298}`;

export class ApiError extends Error {
  constructor(readonly code: string, reason: string) { super(reason); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const reply = await fetch(BASE + path, { method, headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await reply.json();
  if (!reply.ok) throw new ApiError(data.error ?? 'error', data.reason ?? 'The board refused this.');
  return data as T;
}

export interface World { index: number; name: string; scenario: string; verdict: string; reason: string; changes: string[]; seed: number; replay: boolean; numbers: Record<string, number>; events?: { name: string; t: number; value: number }[] }
export interface Balance { available: number; pending: number; finalized: number; claimed: number; claimed_by_tester: Record<string, number> }
export interface Bounty {
  id: number; kind: 'fix_failure' | 'find_failure'; title: string; company: string; status: string; spec_hash: string; available: number; dispute_window_s: number; balance: Balance; now: number; posted_by?: string; checking?: number; chain_mirror?: { label: string; chain_id: number; txs: Record<string, string> } | null;
  pay?: number; cap: number; per_failure: number; group?: string; robot: string; pack?: string; public_worlds?: World[]; hidden_counts?: Record<string, number>; frozen?: Record<string, string>; scope?: string; replay_rejudge?: boolean; controller?: { file: string; sha256: string };
  limits?: Record<string, [number, number]>; narrowed?: string[]; scenarios?: string[]; schema_limits?: Record<string, [number, number]>; scenarios_label?: string; sim_label: string;
}
export interface SetCount { n: number; better: number; worse: number; same: number; passed_before: number; passed_after: number; limits_hit: number; replay_mismatch: number }
export interface FixResult {
  accepted: boolean; code: string; words: string; stage: string; flags: { line: number; text: string; words: string }[]; sets: Record<string, SetCount> | null;
  target: { index: number; name: string; old: string; new: string; passed: boolean; safe_hold: boolean }[]; held_back_with_this_failure?: number; held_back_fixed?: number; proof_wall_s?: number; patched_sha256?: string;
}
export interface Payout { status: string; amount?: number; dispute_ends_at?: number; fingerprint?: string; error?: string }
export interface Fix { n: number; tester: string; source_sha256: string; state: string; result: FixResult | null; payout: Payout | null; wall_s?: number; used_before: number }
export interface Sub { n: number; tester: string; seed: number; state: string; used_before: number; result: { accepted: boolean; code: string; reason: string; fingerprint?: string; repeat?: unknown; runs: number } | null; payout: Payout | null; wall_s?: number }
export interface Fixable { session: string; cid: string; group: string; robot: string; failed: number; worlds: number; posted: boolean; ref: string }
export interface Budget { funded: boolean; cap?: number; held?: number; spent?: number; left?: number; stopped?: boolean; per_bounty_max?: number }

// A claim needs the secret that submit returned once. It stays in this tab, so a reload keeps it. The server keeps only its hash.
const secretKey = (kind: 'fix' | 'world', id: number, n: number) => `crashlab-claim-${kind}-${id}-${n}`;
function keepSecret(kind: 'fix' | 'world', id: number, reply: { n: number; claim_secret: string }) {
  try { sessionStorage.setItem(secretKey(kind, id, reply.n), reply.claim_secret); } catch { /* no storage: the page says the secret is lost when a claim comes */ }
  return reply;
}
export function fixSecret(id: number, n: number): string | null {
  try { return sessionStorage.getItem(secretKey('fix', id, n)); } catch { return null; }
}

export const api = {
  bounties: () => call<{ bounties: Bounty[] }>('GET', '/api/bounties'),
  fixes: (id: number) => call<{ fixes: Fix[] }>('GET', `/api/bounties/${id}/fixes`),
  subs: (id: number) => call<{ submissions: Sub[] }>('GET', `/api/bounties/${id}/submissions`),
  source: (id: number) => call<{ source: string; file: string; scope: string }>('GET', `/api/bounties/${id}/source`),
  fixable: () => call<{ fixable: Fixable[] }>('GET', '/api/fixable'),
  budget: () => call<Budget>('GET', '/api/budget'),
  stop: () => call<Budget>('POST', '/api/budget/stop', {}),
  post: (body: unknown) => call<Bounty>('POST', '/api/bounties/fix', body),
  submitFix: (id: number, tester: string, source: string) => call<{ n: number; claim_secret: string }>('POST', `/api/bounties/${id}/fix`, { tester, source }).then(r => keepSecret('fix', id, r)),
  submitWorld: (id: number, tester: string, world: string, seed: number) => call<{ n: number; claim_secret: string }>('POST', `/api/bounties/${id}/submit`, { tester, world, seed }).then(r => keepSecret('world', id, r)),
  step: (id: number, n: number, step: string) => call<unknown>('POST', `/api/bounties/${id}/fixes/${n}/${step}`, {}),
  claim: (id: number, n: number, tester: string, secret: string) => call<unknown>('POST', `/api/bounties/${id}/fixes/${n}/claim`, { tester, secret }),
  findStep: (id: number, fingerprint: string, step: string, tester?: string) => call<unknown>('POST', `/api/bounties/${id}/failures/${fingerprint}/${step}`, tester ? { tester } : {}),
};
