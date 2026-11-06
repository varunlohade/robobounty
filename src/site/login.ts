import QR from 'qrcode-generator';
import './shell.css';
import './login.css';
import { icon, type IconName } from './icons.ts';
import { enterAsGuest, whoIs } from './session.ts';
import { button, getJson, h, START_SERVER } from './ui.ts';

interface Status { on: boolean; missing: string[]; credential?: string | null }
type Face = 'ready' | 'off' | 'asking' | 'waiting' | 'verifying' | 'verified' | 'failed';
const root = document.getElementById('site')!;
const go = h('div', 'go');
const note = h('div', '');
const live = h('div', '');
const error = h('div', 'lg-error');
error.hidden = true;
error.setAttribute('role', 'alert');
const proves = h('p', 'lg-proves');
proves.hidden = true;
const staging = h('p', 'lg-staging', 'This server uses World ID staging, which accepts test proofs.');
staging.hidden = true;
const head = h('p', 'lg-head', 'Scan with World App');
head.setAttribute('aria-live', 'polite');
const proof = h('div', 'lg-proof');
proof.hidden = true;
let cancel: AbortController | null = null;
let deviceMode = true;

const panel = h('section', 'lg-panel', h('div', 'lg-mark', 'CrashLab'),
  h('h1', '', 'Crash tests for robots'),
  h('p', 'lg-lede', 'Describe the job. AI builds the world and runs your robot through it. Every failure comes with its reason.'),
  head, go, error, live, proves, staging, note, proof,
  h('p', 'lg-foot', 'Simulated. Hand-built physics and an upstream walking policy, not checked against real hardware.'));
panel.setAttribute('aria-label', 'Sign in to CrashLab');
const face = (f: Face) => { panel.dataset.state = f; };

// The background is one recorded film with its labels baked in. The page plays it and does nothing else: no canvas, no per-tile elements, no timers.
const film = Object.assign(document.createElement('video'), { className: 'lg-film', muted: true, loop: true, playsInline: true, autoplay: false, preload: 'none', poster: '/login/film-poster.jpg', disablePictureInPicture: true });
film.setAttribute('muted', '');
film.setAttribute('playsinline', '');
film.setAttribute('aria-hidden', 'true');
const still = matchMedia('(prefers-reduced-motion: reduce)');
const caption = h('div', 'lg-cap', h('p', '', 'Simulated'));
root.append(h('div', 'lg', h('div', 'lg-back', film), caption, panel));
function setPlaying(on: boolean) {
  if (on) {
    if (!film.getAttribute('src')) { film.preload = 'auto'; film.src = '/login/film-1080.mp4'; }
    void film.play().catch(() => {});
  } else film.pause();
}
still.addEventListener('change', () => { if (still.matches) setPlaying(false); });
if (!still.matches) setPlaying(true);

// Small proof, read from the site's own data, never written here.
interface Batch { id: string; total: number; passed: number; failed: number; holds: number }
getJson<{ campaigns: Batch[] }>('/site-api/data').then(d => {
  const batches = d.campaigns.filter(c => c.id === 'demo-window' || c.id === 'demo-inspection');
  if (!batches.length) return;
  const sum = (k: 'total' | 'passed' | 'failed' | 'holds') => batches.reduce((n, b) => n + b[k], 0);
  const cell = (n: number, word: string, cls = '') => h('div', cls, h('dd', '', String(n)), h('dt', '', word));
  proof.replaceChildren(h('dl', '', cell(sum('total'), 'runs'), cell(sum('passed'), 'passed'), cell(sum('failed'), 'failed', 'bad'), cell(sum('holds'), 'safe holds')),
    h('p', 'lg-from', 'Latest recorded batches, window robot and walking robot.'));
  proof.hidden = false;
}).catch(() => {});
// The server names its World ID environment on the providers list. Display only.
getJson<{ entries?: { id: string; version: string }[] }>('/site-api/providers').then(d => {
  if (d.entries?.find(e => e.id === 'world')?.version === 'staging') staging.hidden = false;
}).catch(() => {});

// Where a visitor was going before login. Only a page of this site, so a link cannot send them elsewhere.
function nextPage(): string {
  const asked = new URLSearchParams(location.search).get('next') ?? '';
  return /^[a-z]+\.html(\?[\w\-./=&%]*)?$/.test(asked) ? asked : 'home.html';
}

function guest() {
  enterAsGuest();
  location.href = nextPage();
}

function fail(words: string) {
  face('failed');
  error.replaceChildren(icon('x', 16), h('div', '', words));
  error.hidden = false;
}

function step(cls: string, ic: IconName, text: string, ...small: (Node | string)[]) {
  const mark = icon(ic, 16);
  if (ic === 'loader') mark.classList.add('spin');
  return h('li', cls, mark, h('div', '', text, small.length ? h('small', '', ...small) : null));
}

function qrSvg(text: string): HTMLElement {
  const qr = QR(0, 'M');
  qr.addData(text);
  qr.make();
  const box = h('div', 'qr');
  box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
  return box;
}

function offState(status: Status | null) {
  face('off');
  proves.hidden = true;
  go.replaceChildren(button('sec', 'Enter as local guest', guest));
  note.replaceChildren(h('div', 'lg-note',
    h('b', '', status ? 'World ID is not set up on this server yet' : 'The site server does not answer, so World ID is off'),
    h('p', '', 'A guest can use everything here, and is shown as not verified.'),
    status?.missing.length ? h('p', 'quiet', `Missing in .env: ${status.missing.join(', ')}`) : null,
    status ? null : h('code', '', START_SERVER)));
}

function onState(credential: string | null | undefined) {
  face('ready');
  deviceMode = credential !== 'human';
  proves.textContent = deviceMode ? 'World ID checks this device only. Not proof of a unique human. It shares no name, email or face.' : 'World ID proves you are one unique human. It shares no name, email or face.';
  proves.hidden = false;
  go.replaceChildren(button('pri', 'Sign in with World ID', () => { void start(); }), button('bare', 'Enter as local guest', guest));
  note.replaceChildren();
  live.replaceChildren();
}

async function post(path: string, body?: unknown) {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(45_000) });
  return { ok: res.ok, body: await res.json().catch(() => ({})) };
}

async function start() {
  face('asking');
  error.hidden = true;
  cancel = new AbortController();
  const waiting = h('button', 'btn pri wait', icon('loader'), 'Waiting for World App');
  waiting.setAttribute('aria-disabled', 'true');
  waiting.tabIndex = -1;
  waiting.firstElementChild!.classList.add('spin');
  const stop = button('bare', 'Cancel', () => cancel?.abort());
  go.replaceChildren(waiting, stop);
  live.replaceChildren(h('ul', 'steps verify-only', step('now', 'loader', 'Asking the server to sign this request')));
  try {
    const ctx = await post('/site-api/auth/world/context');
    if (!ctx.ok) throw new Error(ctx.body.words ?? 'The server would not sign this request.');
    const c = ctx.body;
    if (c.environment === 'staging') staging.hidden = false;
    const { IDKit, CredentialRequest, deviceLegacy } = await import('@worldcoin/idkit-core');
    const config = { app_id: c.app_id, rp_context: c.rp_context, environment: c.environment };
    const credential = CredentialRequest('proof_of_human');
    // Device mode only. The signal carries the nonce, because a World ID 3.0 proof has no nonce of its own.
    const request = c.credential === 'device'
      ? await IDKit.request({ ...config, action: c.action, allow_legacy_proofs: true }).preset(deviceLegacy({ signal: c.signal }))
      : c.mode === 'prove'
      ? await IDKit.proveSession(c.session_id, config).constraints(credential)
      : await IDKit.request({ ...config, action: c.action, session_id: 'create', allow_legacy_proofs: false }).constraints(credential);
    const uri = request.connectorURI;
    const openLink = h('a', '', 'open this request on your phone');
    openLink.href = uri;
    openLink.target = '_blank';
    openLink.rel = 'noopener';
    const steps = h('ul', 'steps',
      step('done', 'check', 'Request created'),
      step('now', 'loader', 'Scan the code with World App', 'Or ', openLink, '. The request ends in 5 minutes.'),
      step('', 'circle', 'Check the proof on the server'));
    head.textContent = 'Scan with World App';
    go.replaceChildren(stop);
    live.replaceChildren(h('div', 'lg-verify', qrSvg(uri), steps));
    face('waiting');
    const done = await request.pollUntilCompletion({ signal: cancel.signal, timeout: 300_000 });
    if (!done.success) throw new Error(cancel.signal.aborted ? 'cancelled' : 'World ID did not finish. You are not signed in. You can try again.');
    head.textContent = 'Checking your proof';
    go.replaceChildren();
    proves.hidden = true;
    face('verifying');
    steps.replaceChildren(step('done', 'check', 'Request created'), step('done', 'check', 'World App answered'), step('now', 'loader', 'Checking the proof on the server'));
    const reply = await post('/site-api/auth/world/verify', done.result);
    if (!reply.ok || reply.body.verified !== true) throw new Error(reply.body.words ?? 'The server refused this proof. You are not signed in.');
    face('verified');
    live.replaceChildren(h('div', 'lg-done', icon('ok', 16), reply.body.credential === 'human' ? 'The server verified your proof. Opening CrashLab.' : 'Verified device. Not proof of a unique human. Opening CrashLab.'));
    location.href = nextPage();
  } catch (err) {
    onState(deviceMode ? 'device' : 'human');
    const words = err instanceof Error ? err.message : '';
    if (words !== 'cancelled' && !cancel?.signal.aborted) fail(words || 'World ID did not finish. You are not signed in.');
  }
}

whoIs().then(who => { if (who.kind !== 'none') location.replace(nextPage()); });
getJson<Status>('/site-api/auth/world').then(s => (s.on ? onState(s.credential) : offState(s))).catch(() => offState(null));
