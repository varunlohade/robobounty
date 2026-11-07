import QR from 'qrcode-generator';
import './login.css';
import { authOptions, demoSignIn, enterAsGuest, landing, me, signInCompany, signUpCompany, worldContext, worldVerify } from './auth.ts';
import { whoIs } from './session.ts';
import { getJson, h, START_SERVER } from './ui.ts';

interface Status { on: boolean; missing: string[]; credential?: string | null }
const root = document.getElementById('site')!;
const MARK = '<svg viewBox="0 0 28 28" aria-hidden="true"><g fill="currentColor"><path d="M3 20.2A11 11 0 0 1 18.6 4.6z"/><path d="M25 7.8A11 11 0 0 1 9.4 23.4z"/></g></svg>';

// The background is one recorded film with its labels baked in. The page plays it and does nothing else. With reduced motion it stays on the poster.
const film = Object.assign(document.createElement('video'), { className: 'lg-film', muted: true, loop: true, playsInline: true, preload: 'none', poster: '/login/film-poster.jpg', disablePictureInPicture: true });
film.setAttribute('muted', '');
film.setAttribute('playsinline', '');
film.setAttribute('aria-hidden', 'true');
const still = matchMedia('(prefers-reduced-motion: reduce)');
function setPlaying(on: boolean) {
  if (on) {
    if (!film.getAttribute('src')) { film.preload = 'auto'; film.autoplay = true; film.src = '/login/film-1080.mp4'; }
    void film.play().catch(() => {});
  } else film.pause();
}
still.addEventListener('change', () => setPlaying(!still.matches));
if (!still.matches) setPlaying(true);

const brand = h('div', 'lg-brand');
brand.innerHTML = `${MARK}CrashLab`;
const sheet = h('section', 'lg-sheet');
sheet.setAttribute('aria-label', 'Sign in to CrashLab');
root.append(h('div', 'lg', film, brand, sheet));

// The sheet's top edge follows the height of its step. Past the screen height the sheet scrolls.
const fit = new ResizeObserver(() => place());
function place() {
  const step = sheet.firstElementChild as HTMLElement | null;
  if (!step) return;
  sheet.style.transform = `translateY(${Math.max(16, innerHeight - step.offsetHeight)}px)`;
  step.style.marginBottom = step.offsetHeight > innerHeight - 16 ? '16px' : '';
}
addEventListener('resize', place);
function show(step: HTMLElement) {
  fit.disconnect();
  sheet.replaceChildren(step);
  sheet.scrollTop = 0;
  fit.observe(step);
  place();
}

const goIn = () => { void me().then(m => { location.href = landing(m); }); };

function pill(cls: string, label: string, on: () => void) {
  const b = h('button', `lg-pill ${cls}`, label);
  b.type = 'button';
  b.addEventListener('click', on);
  return b;
}
function textButton(label: string, on: () => void) {
  const b = h('button', 'lg-text', label);
  b.type = 'button';
  b.addEventListener('click', on);
  return b;
}
const guestButton = () => textButton('Enter as local guest', () => { stopRequest(); void enterAsGuest().then(r => { if (r.ok) goIn(); else failStep(r.words); }); });
const backButton = () => textButton('Back', () => { stopRequest(); startStep(); });

function startStep() {
  const option = (who: string, label: string, on: () => void) => h('div', 'lg-opt', h('span', '', who), pill('', label, on));
  const demo = (role: 'company' | 'engineer', label: string) => option('Demo, seeded and not real', label, () => { void demoSignIn(role).then(r => { if (r.ok) goIn(); else failStep(r.words); }); });
  const opts = h('div', 'lg-opts',
    option('For robotics teams', 'Continue with work email', companyStep),
    option('For engineers', 'Continue with World ID', () => { void engineerStep(); }));
  show(h('div', 'lg-step', h('h1', '', 'Robots fall', h('br'), 'here first.'), opts));
  // Seeded sign-in is for automated checks only. It stays off the real page.
  if (new URLSearchParams(location.search).get('seed') === '1') void status.then(st => { if (st?.demo) { opts.append(demo('company', 'Demo company'), demo('engineer', 'Demo engineer')); place(); } });
}

type CompanyMode = 'signin' | 'create';

function companyStep() {
  let mode: CompanyMode = 'signin';
  const title = h('h1', '');
  const email = h('input', 'lg-input');
  Object.assign(email, { type: 'email', required: true, placeholder: 'you@company.com', autocomplete: 'email', name: 'email' });
  email.setAttribute('aria-label', 'Work email');
  const password = h('input', 'lg-input');
  Object.assign(password, { type: 'password', required: true, placeholder: 'Password', name: 'password' });
  password.setAttribute('aria-label', 'Password');
  const company = h('input', 'lg-input');
  Object.assign(company, { placeholder: 'Company name', autocomplete: 'organization', name: 'company' });
  company.setAttribute('aria-label', 'Company name');
  const enter = h('button', 'lg-pill');
  enter.type = 'submit';
  const error = h('p', 'lg-small bad');
  error.setAttribute('role', 'alert');
  error.hidden = true;
  const tab = (label: string, to: CompanyMode) => {
    const b = h('button', 'lg-tab', label);
    b.type = 'button';
    b.dataset.mode = to;
    b.addEventListener('click', () => setMode(to));
    return b;
  };
  const tabs = h('div', 'lg-tabs', h('i', 'lg-knob'), tab('Sign in', 'signin'), tab('Create account', 'create'));
  tabs.setAttribute('role', 'group');
  tabs.setAttribute('aria-label', 'Sign in or create an account');
  function setMode(to: CompanyMode) {
    mode = to;
    tabs.dataset.mode = to;
    for (const b of tabs.querySelectorAll<HTMLButtonElement>('button')) b.setAttribute('aria-pressed', String(b.dataset.mode === to));
    title.replaceChildren(...(to === 'signin' ? ['Company', h('br'), 'sign in.'] : ['New company', h('br'), 'account.']));
    enter.textContent = to === 'signin' ? 'Sign in' : 'Create account';
    password.autocomplete = to === 'signin' ? 'current-password' : 'new-password';
    company.hidden = to === 'signin';
    company.required = to === 'create';
    error.hidden = true;
  }
  setMode('signin');
  const form = h('form', 'lg-form', tabs, email, password, company, h('div', 'lg-submit', enter), error);
  form.addEventListener('submit', e => {
    e.preventDefault();
    error.hidden = true;
    const asked = mode === 'signin' ? signInCompany({ email: email.value, password: password.value }) : signUpCompany({ email: email.value, password: password.value, company: company.value });
    void asked.then(r => {
      if (r.ok) goIn();
      else { error.textContent = r.words; error.hidden = false; }
    });
  });
  show(h('div', 'lg-step', h('div', 'lg-left', title, h('div', 'lg-links', backButton())), form));
  email.focus({ preventScroll: true });
}

const status = authOptions().catch(() => null);
let environment = '';
// The server names its World ID environment on the providers list. Display only.
getJson<{ entries?: { id: string; version: string }[] }>('/site-api/providers').then(d => {
  environment = d.entries?.find(e => e.id === 'world')?.version ?? '';
}).catch(() => {});
const stagingLine = () => environment === 'staging' ? h('p', 'lg-small amber', 'This server uses World ID staging, which accepts test proofs.') : null;

function worldTitle(first: string, second: string) { return h('h1', '', first, h('br'), second); }
function worldStep(title: HTMLElement, body: (Node | null)[], links: Node[], qr?: HTMLElement) {
  show(h('div', 'lg-step', h('div', 'lg-left', h('div', '', title, ...body), h('div', 'lg-links', ...links)), qr ?? null));
}

function offStep(s: Status | null) {
  worldStep(worldTitle('World ID', 'is off.'), [
    h('p', 'lg-say lg-status', s ? 'World ID is not set up on this server yet.' : 'The site server does not answer, so World ID is off.'),
    h('p', 'lg-small', 'A guest can look and run the saved demo. A guest cannot post, submit or claim.'),
    s?.missing.length ? h('p', 'lg-small', import.meta.env.VITE_HOSTED === '1' ? 'World ID sign-in is off.' : `Missing in .env: ${s.missing.join(', ')}`) : null,
    s || import.meta.env.VITE_HOSTED === '1' ? null : h('p', 'lg-small', h('code', '', START_SERVER)),
  ], [backButton(), guestButton()]);
}

function failStep(words: string) {
  worldStep(worldTitle('World ID', 'did not finish.'), [
    h('p', 'lg-say bad', words),
    h('div', 'lg-row', pill('', 'Try again', () => { void engineerStep(); })),
  ], [backButton(), guestButton()]);
}

function qrBox(text: string): HTMLElement {
  const qr = QR(0, 'M');
  qr.addData(text);
  qr.make();
  const box = h('div', 'lg-qr');
  box.innerHTML = qr.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
  const svg = box.querySelector('svg')!;
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'QR code for this World ID request');
  return box;
}

let cancel: AbortController | null = null;
function stopRequest() { cancel?.abort(); cancel = null; }

async function engineerStep() {
  stopRequest();
  const run = new AbortController();
  cancel = run;
  const title = () => worldTitle('Scan with', 'World App.');
  const empty = h('div', 'lg-qr empty');
  empty.setAttribute('aria-hidden', 'true');
  const asking = h('p', 'lg-say lg-status', 'Asking the server to sign this request.');
  asking.setAttribute('aria-live', 'polite');
  worldStep(title(), [asking], [backButton(), guestButton()], empty);
  const s = await status;
  if (run.signal.aborted) return;
  if (!s?.on) { cancel = null; offStep(s); return; }
  const device = s.credential !== 'human';
  try {
    const ctx = await worldContext();
    if (!ctx.ok) throw new Error(ctx.body.words ?? 'The server would not sign this request.');
    if (run.signal.aborted) return;
    const c = ctx.body;
    if (c.environment) environment = c.environment;
    const { IDKit, CredentialRequest, deviceLegacy } = await import('@worldcoin/idkit-core');
    const config = { app_id: c.app_id, rp_context: c.rp_context, environment: c.environment };
    const credential = CredentialRequest('proof_of_human');
    // Device mode only. The signal carries the nonce, because a World ID 3.0 proof has no nonce of its own.
    const request = c.credential === 'device'
      ? await IDKit.request({ ...config, action: c.action, allow_legacy_proofs: true }).preset(deviceLegacy({ signal: c.signal }))
      : c.mode === 'prove'
      ? await IDKit.proveSession(c.session_id, config).constraints(credential)
      : await IDKit.request({ ...config, action: c.action, session_id: 'create', allow_legacy_proofs: false }).constraints(credential);
    if (run.signal.aborted) return;
    const uri = request.connectorURI;
    const open = h('a', '', 'open this request on your phone');
    open.href = uri;
    open.target = '_blank';
    open.rel = 'noopener';
    worldStep(title(), [
      h('p', 'lg-say', device ? 'Confirm with World ID.' : 'World ID proves you are one unique human. It shares no name, email or face.'),
      h('p', 'lg-small', 'Waiting for World App. Or ', open, '. The request ends in 5 minutes.'),
      stagingLine(),
    ], [backButton(), guestButton()], qrBox(uri));
    const done = await request.pollUntilCompletion({ signal: run.signal, timeout: 300_000 });
    if (run.signal.aborted) return;
    if (!done.success) throw new Error('You are not signed in. You can try again.');
    worldStep(worldTitle('Checking', 'your proof.'), [h('p', 'lg-say lg-status', 'World App answered. The server is checking the proof.')], []);
    const reply = await worldVerify(done.result);
    if (run.signal.aborted) return;
    if (!reply.ok || reply.body.verified !== true) throw new Error(reply.body.words ?? 'The server refused this proof. You are not signed in.');
    cancel = null;
    worldStep(worldTitle('Opening', 'CrashLab.'), [h('p', 'lg-say lg-status', reply.body.credential === 'human' ? 'The server verified your proof.' : 'Verified device.')], []);
    goIn();
  } catch (err) {
    if (run.signal.aborted) return;
    cancel = null;
    failStep((err instanceof Error && err.message) || 'You are not signed in. You can try again.');
  }
}

startStep();
// ?switch=1: a guest who wants a real account stays here. A sign-in replaces the guest session.
whoIs().then(who => { if (who.kind !== 'none' && !new URLSearchParams(location.search).has('switch')) location.replace(landing(who)); });
