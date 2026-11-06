import QR from 'qrcode-generator';
import './shell.css';
import { icon, type IconName } from './icons.ts';
import { enterAsGuest, whoIs } from './session.ts';
import { button, getJson, h, START_SERVER } from './ui.ts';

interface Status { on: boolean; missing: string[] }
const root = document.getElementById('site')!;
const go = h('div', 'go');
const note = h('div', '');
const live = h('div', '');
const error = h('p', 'error');
error.hidden = true;
error.setAttribute('role', 'alert');
let cancel: AbortController | null = null;

const side = h('div', 'side', h('div', 'mark', 'CrashLab'),
  h('div', 'body', h('h1', '', 'Sign in to CrashLab'), h('p', 'proof', 'World ID proves you are one unique human. It shares no name, email or face.'), go, error, live, note),
  h('p', 'foot', 'Simulated. Hand-built physics, not checked against real hardware.'));
const picture = h('div', 'picture frame', Object.assign(h('img'), { src: '/site/frames/login-snow.jpg', alt: 'The window robot on a tower in snow' }), h('div', 'frame-note', 'Simulated. Still from a recorded run.'));
root.append(h('div', 'login', side, picture));

function guest() {
  enterAsGuest();
  location.href = 'home.html';
}

function fail(words: string) {
  error.textContent = words;
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
  go.replaceChildren(button('sec', 'Enter as local guest', guest));
  note.replaceChildren(h('div', 'note',
    h('b', '', status ? 'World ID is not set up on this server yet' : 'The site server does not answer, so World ID is off'),
    h('p', '', 'A guest can use everything here, and is shown as not verified.'),
    status?.missing.length ? h('p', 'quiet', `Missing in .env: ${status.missing.join(', ')}`) : null,
    status ? null : h('code', '', START_SERVER)));
}

function onState() {
  go.replaceChildren(button('pri', 'Sign in with World ID', () => { void start(); }), button('bare', 'Enter as local guest', guest));
  note.replaceChildren();
  live.replaceChildren();
}

async function post(path: string, body?: unknown) {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(45_000) });
  return { ok: res.ok, body: await res.json().catch(() => ({})) };
}

async function start() {
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
    const { IDKit, CredentialRequest } = await import('@worldcoin/idkit-core');
    const config = { app_id: c.app_id, rp_context: c.rp_context, environment: c.environment };
    const credential = CredentialRequest('proof_of_human');
    const request = c.mode === 'prove'
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
    live.replaceChildren(h('div', 'verify', qrSvg(uri), steps));
    const done = await request.pollUntilCompletion({ signal: cancel.signal, timeout: 300_000 });
    if (!done.success) throw new Error(cancel.signal.aborted ? 'cancelled' : 'World ID did not finish. You are not signed in. You can try again.');
    steps.replaceChildren(step('done', 'check', 'Request created'), step('done', 'check', 'World App answered'), step('now', 'loader', 'Checking the proof on the server'));
    const reply = await post('/site-api/auth/world/verify', done.result);
    if (!reply.ok || reply.body.verified !== true) throw new Error(reply.body.words ?? 'The server refused this proof. You are not signed in.');
    location.href = 'home.html';
  } catch (err) {
    onState();
    const words = err instanceof Error ? err.message : '';
    if (words !== 'cancelled' && !cancel?.signal.aborted) fail(words || 'World ID did not finish. You are not signed in.');
  }
}

whoIs().then(who => { if (who.kind !== 'none') location.replace('home.html'); });
getJson<Status>('/site-api/auth/world').then(s => (s.on ? onState() : offState(s))).catch(() => offState(null));
