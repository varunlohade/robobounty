// The site's frame: sidebar, page head and status line. Any page imports this and fills `main`.
//   const { main } = mountShell({ page: 'bounties', title: 'Bounties' });
// The page needs one <div id="site"></div>. A visitor with no session goes to login.html.
import './shell.css';
import { icon, type IconName } from './icons.ts';
import { ENGINEER_HOME, loginHref, onAuthChange, savePayout } from './auth.ts';
import { signOut, whoIs, type Who } from './session.ts';

export type PageName = 'home' | 'simulation' | 'failures' | 'bounties' | 'data' | 'settings' | 'providers';
const MARK = '<svg viewBox="0 0 28 28" width="22" height="22" aria-hidden="true"><g fill="currentColor"><path d="M3 20.2A11 11 0 0 1 18.6 4.6z"/><path d="M25 7.8A11 11 0 0 1 9.4 23.4z"/></g></svg>';
const RAIL_KEY = 'crashlab-rail';

const NAV: { page: PageName; label: string; href: string; icon: IconName }[] = [
  { page: 'home', label: 'Overview', href: 'home.html', icon: 'overview' },
  { page: 'simulation', label: 'Simulation', href: 'simulation.html', icon: 'play' },
  { page: 'failures', label: 'Failures', href: 'failures.html', icon: 'alert' },
  { page: 'bounties', label: 'Bounties', href: 'bounties.html', icon: 'coins' },
  { page: 'data', label: 'Data', href: 'data.html', icon: 'database' },
  { page: 'settings', label: 'Settings', href: 'settings.html', icon: 'settings' },
];

export interface ShellOptions {
  page: PageName;
  title: string;
  subtitle?: string;
  status?: string;
  statusRight?: string[];
  quietWho?: boolean; // The side bar names the account and no more.
}

export interface Shell {
  root: HTMLElement;
  main: HTMLElement;
  actions: HTMLElement;
  setStatus(left: string, right?: string[]): void;
  who: Promise<Who>;
}

function make(tag: string, cls: string, text?: string): HTMLElement {
  const n = document.createElement(tag);
  n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

function payoutButton(who: Who) {
  if (who.payout.signed) return make('small', 'sh-mono', `Wallet ${who.payout.masked}, signature checked`);
  const b = make('button', 'sh-mono', who.payout.masked ? `Payout ${who.payout.masked}` : 'Add payout address');
  b.addEventListener('click', async () => {
    const value = window.prompt('Your public payout address, 0x and 40 hex characters. Never enter a private key. Credits only: nothing is paid to it yet.', '');
    if (!value) return;
    const r = await savePayout(value);
    if (!r.ok) { window.alert(r.words); return; }
    location.reload();
  });
  return b;
}

function whoRow(box: HTMLElement, who: Who, quiet = false) {
  const name = make('div', 'sh-who-name');
  const label = who.kind === 'guest' ? who.verificationLabel : who.label;
  const badge = make('span', 'sh-badge', label.trim().charAt(0).toUpperCase());
  badge.title = who.kind === 'guest' ? label : `${label}, ${who.verificationLabel}`;
  box.dataset.who = who.kind;
  box.dataset.level = who.verification;
  const words = who.kind === 'guest' ? who.verificationLabel : who.label;
  name.append(make('span', '', words));
  if (who.kind !== 'guest' && (!quiet || who.verification === 'world_human')) name.append(make('small', '', who.verificationLabel));
  if (who.kind === 'engineer' && !quiet) name.append(make('small', '', who.screened ? 'Screened. A quiz, not proof of skill.' : 'Not screened yet'), payoutButton(who));
  else if (who.kind === 'engineer' && !who.payout.signed) name.append(payoutButton(who));
  box.replaceChildren(badge, name);
  const out = make('button', 'sh-out');
  out.setAttribute('aria-label', 'Sign out');
  out.title = 'Sign out';
  out.append(icon('logout', 16));
  out.addEventListener('click', async () => { await signOut(); location.href = 'login.html'; });
  box.append(out);
}

function sidebar(page: PageName) {
  const nav = make('nav', 'sh-nav');
  nav.setAttribute('aria-label', 'Main');
  const brand = make('a', 'sh-brand', 'CrashLab') as HTMLAnchorElement;
  brand.href = 'home.html';
  brand.insertAdjacentHTML('afterbegin', MARK);
  nav.append(brand);
  for (const item of NAV) {
    const a = make('a', 'sh-item') as HTMLAnchorElement;
    a.href = item.href;
    a.append(icon(item.icon, 16), make('span', '', item.label));
    a.hidden = item.page !== 'bounties'; // Shown once the server names the role, so an engineer never sees them flash.
    a.dataset.page = item.page;
    if (item.page === page) a.setAttribute('aria-current', 'page');
    nav.append(a);
  }
  const whoBox = make('div', 'sh-who');
  nav.append(whoBox);
  return { nav, brand, whoBox };
}

// The simulator's copy of the sidebar. It folds to icons so the simulation keeps its room, and remembers. The lab does its own redirects.
export function mountRail(root: HTMLElement): HTMLElement {
  root.classList.add('sh-app', 'sh-light');
  const { nav, brand, whoBox } = sidebar('simulation');
  nav.classList.add('sh-rail');
  for (const a of nav.querySelectorAll<HTMLAnchorElement>('a.sh-item')) a.title = a.textContent ?? '';
  const fold = make('button', 'sh-fold') as HTMLButtonElement;
  fold.type = 'button';
  fold.append(icon('panel', 16));
  const paint = (closed: boolean) => {
    nav.classList.toggle('closed', closed);
    fold.setAttribute('aria-label', closed ? 'Open the sidebar' : 'Fold the sidebar to icons');
    fold.title = fold.getAttribute('aria-label') ?? '';
    fold.setAttribute('aria-expanded', String(!closed));
  };
  let closed = true;
  try { closed = localStorage.getItem(RAIL_KEY) !== 'open'; } catch { /* no storage: folded */ }
  paint(closed);
  fold.addEventListener('click', () => {
    closed = !closed;
    paint(closed);
    try { localStorage.setItem(RAIL_KEY, closed ? 'closed' : 'open'); } catch { /* no storage: this page only */ }
  });
  brand.after(fold);
  void whoIs().then(w => {
    if (w.kind === 'none') { for (const a of nav.querySelectorAll<HTMLElement>('a.sh-item')) a.hidden = false; return; }
    whoRow(whoBox, w);
    for (const a of nav.querySelectorAll<HTMLElement>('a.sh-item')) a.hidden = w.kind === 'engineer' && a.dataset.page !== 'bounties';
  });
  return nav;
}

export function mountShell(opts: ShellOptions): Shell {
  const root = document.getElementById('site') ?? document.body.appendChild(make('div', ''));
  root.classList.add('sh-app', 'sh-light');
  const { nav, whoBox } = sidebar(opts.page);

  const column = make('div', 'sh-column');
  const head = make('header', 'sh-head');
  head.append(make('h1', 'sh-title', opts.title));
  if (opts.subtitle) head.append(make('p', 'sh-sub', opts.subtitle));
  const actions = make('div', 'sh-actions');
  head.append(actions);
  const main = make('main', 'sh-main');
  column.append(head, main);

  const status = make('footer', 'sh-status');
  const setStatus = (left: string, right: string[] = []) => {
    const r = make('div', 'sh-status-r');
    r.append(...right.map(text => make('span', '', text)));
    status.replaceChildren(make('span', 'sh-status-l', left), r);
    status.hidden = !left && !right.length;
  };
  setStatus(opts.status ?? '', opts.statusRight);
  root.replaceChildren(nav, column, status);

  const here = `${location.pathname.replace(/^\//, '')}${location.search}`; // Read now: a page may tidy its address while this waits.
  const who = whoIs();
  void who.then(w => {
    if (w.kind === 'none') { location.replace(loginHref(here)); return; }
    if (w.kind === 'engineer' && opts.page !== 'bounties') { location.replace(ENGINEER_HOME); return; }
    whoRow(whoBox, w, opts.quietWho);
    for (const a of nav.querySelectorAll<HTMLElement>('a.sh-item')) a.hidden = w.kind === 'engineer' && a.dataset.page !== 'bounties';
    if (w.kind === 'engineer' && new URLSearchParams(location.search).get('notice') === 'engineer') head.append(make('p', 'sh-sub', 'That page is for companies. Engineers work from Bounties.'));
  });
  // A sign-in or sign-out in another tab: read the server again.
  onAuthChange(() => { void whoIs().then(w => { if (w.kind === 'none') location.replace(loginHref(here)); else location.reload(); }); });
  return { root, main, actions, setStatus, who };
}
