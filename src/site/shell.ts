// The site's frame: sidebar, page head and status line. Any page imports this and fills `main`.
//   const { main } = mountShell({ page: 'bounties', title: 'Bounties', status: 'Local ledger. Not on chain.' });
// The page needs one <div id="site"></div>. A visitor with no session goes to login.html.
import './shell.css';
import { icon, type IconName } from './icons.ts';
import { ENGINEER_HOME, loginHref, onAuthChange, savePayout } from './auth.ts';
import { signOut, whoIs, type Who } from './session.ts';

export type PageName = 'home' | 'simulation' | 'failures' | 'bounties' | 'data' | 'settings' | 'providers';
const MARK = '<svg viewBox="0 0 28 28" width="22" height="22" aria-hidden="true"><g fill="currentColor"><path d="M3 20.2A11 11 0 0 1 18.6 4.6z"/><path d="M25 7.8A11 11 0 0 1 9.4 23.4z"/></g></svg>';
export const SIM_NOTE = 'Simulated. Hand-built physics, not checked against real hardware.';

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
  light?: boolean;
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
    const value = window.prompt('Your public payout address, 0x and 40 hex characters. Never enter a private key. Test units only: nothing is paid to it yet.', '');
    if (!value) return;
    const r = await savePayout(value);
    if (!r.ok) { window.alert(r.words); return; }
    location.reload();
  });
  return b;
}

function whoRow(box: HTMLElement, who: Who) {
  const name = make('div', 'sh-who-name');
  box.dataset.who = who.kind;
  box.dataset.level = who.verification;
  const words = who.kind === 'guest' ? who.verificationLabel : who.label;
  name.append(make('span', '', words));
  if (who.kind !== 'guest') name.append(make('small', '', who.verificationLabel));
  if (who.kind === 'engineer') name.append(make('small', '', who.screened ? 'Screened. A quiz, not proof of skill.' : 'Not screened yet'), payoutButton(who));
  box.replaceChildren(name);
  const out = make('button', 'sh-out');
  out.setAttribute('aria-label', 'Sign out');
  out.title = 'Sign out';
  out.append(icon('logout', 16));
  out.addEventListener('click', async () => { await signOut(); location.href = 'login.html'; });
  box.append(out);
}

export function mountShell(opts: ShellOptions): Shell {
  const root = document.getElementById('site') ?? document.body.appendChild(make('div', ''));
  root.classList.add('sh-app');
  root.classList.toggle('sh-light', opts.light === true);
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
    if (item.page === opts.page) a.setAttribute('aria-current', 'page');
    nav.append(a);
  }
  const whoBox = make('div', 'sh-who');
  nav.append(whoBox);

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
  };
  setStatus(opts.status ?? SIM_NOTE, opts.statusRight);
  root.replaceChildren(nav, column, status);

  const here = `${location.pathname.replace(/^\//, '')}${location.search}`; // Read now: a page may tidy its address while this waits.
  const who = whoIs();
  void who.then(w => {
    if (w.kind === 'none') { location.replace(loginHref(here)); return; }
    if (w.kind === 'engineer' && opts.page !== 'bounties') { location.replace(ENGINEER_HOME); return; }
    whoRow(whoBox, w);
    for (const a of nav.querySelectorAll<HTMLElement>('a.sh-item')) a.hidden = w.kind === 'engineer' && a.dataset.page !== 'bounties';
    if (w.kind === 'engineer' && new URLSearchParams(location.search).get('notice') === 'engineer') head.append(make('p', 'sh-sub', 'That page is for companies. Engineers work from Bounties.'));
  });
  // A sign-in or sign-out in another tab: read the server again.
  onAuthChange(() => { void whoIs().then(w => { if (w.kind === 'none') location.replace(loginHref(here)); else location.reload(); }); });
  return { root, main, actions, setStatus, who };
}
