// The board server. Every bounty, fix and number on the page comes from here. Nothing is sample data.
import { boardAuth, loginHref } from '../site/auth.ts';

const BASE = `http://127.0.0.1:${import.meta.env.VITE_BOARD_PORT ?? 5298}`;

export class ApiError extends Error {
  constructor(readonly code: string, reason: string) { super(reason); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const send = (token: string | null) => fetch(BASE + path, { method, headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: body === undefined ? undefined : JSON.stringify(body) });
  let reply = await send(await boardAuth());
  if (reply.status === 401) {
    const token = await boardAuth(true); // The short token ran out. A new one comes only if the session lives.
    if (!token) { location.replace(loginHref()); throw new ApiError('sign_in_needed', 'Your session ended. Sign in again.'); }
    reply = await send(token);
  }
  const data = await reply.json();
  if (!reply.ok) throw new ApiError(data.error ?? 'error', data.reason ?? 'The board refused this.');
  return data as T;
}

export interface ArcConfig { on: boolean; asked?: boolean; reason?: string; label: string; real: boolean; chain_id: number; chain_hex: string; rpc_url: string; explorer: string | null; explorer_home: string | null; usdc: string; contract: string; resolver: string; arbiter: string; agent_name: string; cap_usdc: number; demo: boolean; demo_session?: string; recorded_label: string; deploy_tx?: string }
export interface ArcBalance { address: string; usdc_base_units: string; gas_wei: string; allowance_base_units: string }
export interface FundPlan { contract: string; usdc: string; resolver: string; arbiter: string; spec_hash: string; cap: string; approve?: string; per_failure: string; top_prize: string; deadline: string; grace: string; dispute_window: string; fee_wei: string; chain_hex: string }
export interface ArcSteps { state: string | null; txs: Record<string, string>; tx_links: Record<string, string>; submitter?: string; fingerprint?: string; chain_bounty?: number; amount_base_units?: number; dispute_ends_at?: number | null; chain_now?: number; chain_read_at?: number; recorded?: boolean; message?: string | null; paid?: boolean; paid_by?: string; balance_before?: number; balance_after?: number }
export interface ArcFunding { label: string; chain_bounty: number; company: string; contract: string; cap_base_units: number; txs: Record<string, string>; tx_links: Record<string, string>; fixes: Record<string, ArcSteps> }
export interface World { index: number; name: string; scenario: string; verdict: string; reason: string; changes: string[]; seed: number; replay: boolean; numbers: Record<string, number>; events?: { name: string; t: number; value: number }[] }
export interface Balance { available: number; pending: number; finalized: number; claimed: number; claimed_by_tester: Record<string, number> }
export interface Bounty {
  mine?: boolean; id: number; kind: 'fix_failure' | 'find_failure'; title: string; company: string; status: string; spec_hash: string; available: number; dispute_window_s: number; balance: Balance; now: number; posted_by?: string; checking?: number; chain_mirror?: { label: string; chain_id: number | null; txs: Record<string, string>; tx_links?: Record<string, string>; state?: string | null; paid?: boolean; message?: string | null; pay_base_units?: number } | null; evidence?: { label: string; root_hash: string; rechecked: boolean } | null; arc?: ArcFunding | null;
  pay?: number; cap: number; per_failure: number; group?: string; robot: string; pack?: string; public_worlds?: World[]; hidden_counts?: Record<string, number>; frozen?: Record<string, string>; scope?: string; replay_rejudge?: boolean; controller?: { file: string; sha256: string };
  limits?: Record<string, [number, number]>; narrowed?: string[]; scenarios?: string[]; schema_limits?: Record<string, [number, number]>; scenarios_label?: string; sim_label: string;
}
export interface SetCount { n: number; better: number; worse: number; same: number; passed_before: number; passed_after: number; limits_hit: number; replay_mismatch: number }
export interface FixResult {
  accepted: boolean; code: string; words: string; stage: string; flags: { line: number; text: string; words: string }[]; sets: Record<string, SetCount> | null;
  target: { index: number; name: string; old: string; new: string; passed: boolean; safe_hold: boolean }[]; held_back_with_this_failure?: number; held_back_fixed?: number; proof_wall_s?: number; patched_sha256?: string; recorded?: boolean;
}
export interface Payout { status: string; amount?: number; dispute_ends_at?: number; fingerprint?: string; error?: string }
export interface Fix { n: number; tester: string; source_sha256: string; state: string; result: FixResult | null; payout: Payout | null; wall_s?: number; used_before: number; wallet?: string | null }
export interface Sub { n: number; tester: string; seed: number; state: string; used_before: number; result: { accepted: boolean; code: string; reason: string; fingerprint?: string; repeat?: unknown; runs: number } | null; payout: Payout | null; wall_s?: number }
export interface Fixable { session: string; cid: string; group: string; robot: string; failed: number; worlds: number; posted: boolean; ref: string }
export interface PostCheck { state: string; phase: string; done: number; total: number }
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
  startCheck: (session: string, campaign: string, group: string) => call<PostCheck>('POST', '/api/fixable/check', { session, campaign, group }),
  postCheck: (session: string, campaign: string) => call<PostCheck>('GET', `/api/fixable/check/${session}/${campaign}`),
  budget: () => call<Budget>('GET', '/api/budget'),
  stop: () => call<Budget>('POST', '/api/budget/stop', {}),
  post: (body: unknown) => call<Bounty>('POST', '/api/bounties/fix', body),
  submitFix: (id: number, source: string) => call<{ n: number; claim_secret: string }>('POST', `/api/bounties/${id}/fix`, { source }).then(r => keepSecret('fix', id, r)),
  submitWorld: (id: number, world: string, seed: number) => call<{ n: number; claim_secret: string }>('POST', `/api/bounties/${id}/submit`, { world, seed }).then(r => keepSecret('world', id, r)),
  step: (id: number, n: number, step: string) => call<unknown>('POST', `/api/bounties/${id}/fixes/${n}/${step}`, {}),
  claim: (id: number, n: number, secret: string) => call<unknown>('POST', `/api/bounties/${id}/fixes/${n}/claim`, { secret }),
  arc: () => call<ArcConfig>('GET', '/api/arc'),
  arcBalance: (address: string) => call<ArcBalance>('GET', `/api/arc/balance/${address}`),
  arcDemoFix: () => call<{ source: string; group: string }>('GET', '/api/arc/demo-fix'),
  arcChallenge: (body: unknown) => call<{ nonce: string; message: string }>('POST', '/api/arc/challenge', body),
  arcWallet: (nonce: string, signature: string) => call<{ wallet: string }>('POST', '/api/arc/wallet', { nonce, signature }),
  arcPlan: (id: number) => call<FundPlan>('POST', `/api/arc/bounties/${id}/plan`, {}),
  arcFunded: (id: number, create_tx: string, approve_tx: string | null) => call<{ waiting?: boolean }>('POST', `/api/arc/bounties/${id}/funded`, approve_tx ? { create_tx, approve_tx } : { create_tx }),
  arcReject: (id: number, n: number, nonce: string, signature: string) => call<unknown>('POST', `/api/arc/bounties/${id}/fixes/${n}/reject`, { nonce, signature }),
  arcClaimed: (id: number, n: number, tx: string) => call<{ waiting?: boolean }>('POST', `/api/arc/bounties/${id}/fixes/${n}/claimed`, { tx }),
  findStep: (id: number, fingerprint: string, step: string) => call<unknown>('POST', `/api/bounties/${id}/failures/${fingerprint}/${step}`, {}),
};
