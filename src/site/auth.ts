// The one door to sign-in. The server decides who you are: /site-api/auth/me is the only source. No token or password reaches browser storage.
export type Role = 'company' | 'engineer' | 'guest';
export interface Me {
  signedIn: boolean; role: Role | null; label: string; verification: string; verificationLabel: string; email: string | null; demo: boolean; tester: string | null; screened: boolean;
  payout: { set: boolean; masked: string | null; signed?: boolean }; expired: boolean; offline: boolean; csrf: string; humanId: string | null; credential: string | null;
}
export type AuthResult = { ok: true } | { ok: false; code: string; words: string };

const NOBODY: Me = { signedIn: false, role: null, label: '', verification: 'none', verificationLabel: '', email: null, demo: false, tester: null, screened: false, payout: { set: false, masked: null }, expired: false, offline: false, csrf: '', humanId: null, credential: null };
const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('crashlab-auth');
let csrf = '';
let boardToken: { value: string; until: number } | null = null;

function read(m: Record<string, any>): Me {
  csrf = typeof m.csrf === 'string' ? m.csrf : '';
  if (m.signed_in !== true) return { ...NOBODY, expired: m.expired === true };
  return { signedIn: true, role: m.role, label: String(m.label ?? ''), verification: String(m.verification ?? 'none'), verificationLabel: String(m.verification_label ?? ''), email: m.email ?? null, demo: m.demo === true, tester: m.tester ?? null, screened: m.screened === true,
    payout: m.payout ?? NOBODY.payout, expired: false, offline: false, csrf, humanId: m.human_id ?? null, credential: m.credential ?? null };
}

export async function me(): Promise<Me> {
  try {
    const res = await fetch('/site-api/auth/me', { signal: AbortSignal.timeout(4_000) });
    if (res.ok) return read(await res.json());
  } catch { /* no server: nobody is signed in */ }
  boardToken = null;
  return { ...NOBODY, offline: true };
}

async function post(path: string, body?: unknown, timeout = 20_000): Promise<{ ok: boolean; status: number; body: Record<string, any> }> {
  const send = () => fetch(path, { method: 'POST', headers: { 'X-CrashLab-Request': '1', ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(timeout) });
  let res = await send();
  if (res.status === 403) {
    const first = await res.clone().json().catch(() => ({}));
    if (first.error === 'csrf_refused') { await me(); res = await send(); } // Another tab changed the session.
  }
  return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) };
}

async function entered(path: string, body?: unknown): Promise<AuthResult> {
  try {
    const r = await post(path, body);
    if (!r.ok) return { ok: false, code: String(r.body.error ?? 'refused'), words: String(r.body.words ?? 'The server refused this. You are not signed in.') };
    read(r.body);
    boardToken = null;
    channel?.postMessage('changed');
    return { ok: true };
  } catch {
    return { ok: false, code: 'no_server', words: 'The site server does not answer. You are not signed in.' };
  }
}

export const signUpCompany = (v: { email: string; password: string; company: string }) => entered('/site-api/auth/signup', v);
export const signInCompany = (v: { email: string; password: string }) => entered('/site-api/auth/signin', v);
export const enterAsGuest = () => entered('/site-api/auth/guest');
export const demoSignIn = (role: 'company' | 'engineer') => entered('/site-api/auth/demo', { role });

export interface WorldStatus { on: boolean; missing: string[]; credential?: string | null; demo?: boolean; password_min?: number }
export const authOptions = () => fetch('/site-api/auth/world').then(r => r.json() as Promise<WorldStatus>);

// The World ID steps. The page runs IDKit between these two.
export const worldContext = () => post('/site-api/auth/world/context', undefined, 45_000);
export async function worldVerify(result: unknown) {
  const r = await post('/site-api/auth/world/verify', result, 45_000);
  if (r.ok) { read(r.body); boardToken = null; channel?.postMessage('changed'); }
  return r;
}

export async function signOut() {
  await me();
  try { await post('/site-api/auth/logout'); } catch { /* no server: no server session either */ }
  csrf = '';
  boardToken = null;
  channel?.postMessage('changed');
}

export async function savePayout(address: string | null): Promise<AuthResult> {
  await me();
  const r = await post('/site-api/auth/wallet', { address });
  if (!r.ok) return { ok: false, code: String(r.body.error ?? 'refused'), words: String(r.body.words ?? 'The server refused this address.') };
  channel?.postMessage('changed');
  return { ok: true };
}

// A short token for the board on its own port. It stays in this page's memory.
export async function boardAuth(fresh = false): Promise<string | null> {
  if (!fresh && boardToken && boardToken.until > Date.now()) return boardToken.value;
  if (!csrf) await me();
  if (!csrf) return null; // Signed out: ask for nothing.
  try {
    const r = await post('/site-api/auth/board-token');
    if (!r.ok) { boardToken = null; return null; }
    boardToken = { value: r.body.token, until: Date.now() + (r.body.expires_in - 30) * 1000 };
    return boardToken.value;
  } catch { return null; }
}

// Where a visitor was going. Only a page of this site, so a link cannot send them elsewhere. policy/server/site_auth.py safe_next holds the same rule.
export function nextPage(search = location.search): string {
  const asked = new URLSearchParams(search).get('next') ?? '';
  return /^[a-z]+\.html(\?[\w\-./=&%]*)?$/.test(asked) && !asked.startsWith('login.html') ? asked : 'home.html';
}
// Where this person goes after signing in. An engineer works from Bounties, after the short quiz.
export function landing(m: Me, search = location.search): string {
  const asked = nextPage(search);
  if (m.role !== 'engineer') return asked;
  if (asked.startsWith('bounties.html')) return asked;
  return m.screened ? 'bounties.html' : 'screener.html';
}
export const ENGINEER_HOME = 'bounties.html?notice=engineer';
export const runHeaders = async (): Promise<Record<string, string>> => { const t = await boardAuth(); return t ? { Authorization: `Bearer ${t}` } : {}; };
export const screenerStart = async () => { await me(); return post('/site-api/auth/screener/start'); };
export const screenerGrade = (answers: Record<string, number>) => post('/site-api/auth/screener/grade', { answers });
export function loginHref(page = `${location.pathname.replace(/^\//, '')}${location.search}`): string {
  return `login.html?next=${encodeURIComponent(page)}`;
}
export const onAuthChange = (run: () => void) => { channel?.addEventListener('message', run); };
