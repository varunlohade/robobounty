// The site's frame: sidebar, page head and status line. Any page imports this and fills `main`.
//   const { main } = mountShell({ page: 'bounties', title: 'Bounties', status: 'Local ledger. Not on chain.' });
// The page needs one <div id="site"></div>. A visitor with no session goes to login.html.
import './shell.css';
import { icon, type IconName } from './icons.ts';
import { signOut, whoIs, type Who } from './session.ts';

export type PageName = 'home' | 'crashlab' | 'bounties' | 'data' | 'providers';
export const SIM_NOTE = 'Simulated. Hand-built physics, not checked against real hardware.';

const NAV: { page: PageName; label: string; href: string; icon: IconName }[] = [
  { page: 'home', label: 'Home', href: 'home.html', icon: 'home' },
  { page: 'crashlab', label: 'CrashLab', href: 'crashlab.html', icon: 'box' },
  { page: 'bounties', label: 'Bounties', href: 'bounties.html', icon: 'target' },
  { page: 'data', label: 'Data', href: 'data.html', icon: 'chart' },
  { page: 'providers', label: 'Providers', href: 'providers.html', icon: 'layers' },
];

export interface ShellOptions {
  page: PageName;
  title: string;
  subtitle?: string;
  status?: string;
  statusRight?: string[];
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

function whoRow(box: HTMLElement, who: Who) {
  const name = make('div', 'sh-who-name');
  if (who.kind === 'verified') {
    box.dataset.who = 'verified';
    const ok = icon('check', 16);
    ok.classList.add('sh-ok');
    name.append(make('span', '', who.credential === 'human' ? 'Verified human' : 'Verified device. Not proof of a unique human.'), make('small', 'sh-mono', `${who.humanId.slice(0, 6)}…${who.humanId.slice(-4)}`));
    box.replaceChildren(ok, name);
  } else {
    box.dataset.who = 'guest';
    name.append(make('span', '', 'Local guest, not verified'));
    box.replaceChildren(name);
  }
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
  const nav = make('nav', 'sh-nav');
  nav.setAttribute('aria-label', 'Main');
  const brand = make('a', 'sh-brand', 'CrashLab') as HTMLAnchorElement;
  brand.href = 'home.html';
  nav.append(brand);
  for (const item of NAV) {
    const a = make('a', 'sh-item') as HTMLAnchorElement;
    a.href = item.href;
    a.append(icon(item.icon, 16), make('span', '', item.label));
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
    if (w.kind === 'none') location.replace(`login.html?next=${encodeURIComponent(here)}`);
    else whoRow(whoBox, w);
  });
  return { root, main, actions, setStatus, who };
}
