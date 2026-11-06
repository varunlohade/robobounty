// Small helpers every page shares. All text goes in through textContent.
import './site.css';
import { icon, type IconName } from './icons.ts';

export type Kid = Node | string | null | undefined | false;
export function h<K extends keyof HTMLElementTagNameMap>(tag: K, cls = '', ...kids: Kid[]): HTMLElementTagNameMap[K] {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) n.append(kid);
  return n;
}

export function link(cls: string, href: string, ...kids: Kid[]): HTMLAnchorElement {
  const a = h('a', cls, ...kids);
  a.href = href;
  return a;
}

export function button(cls: string, label: Kid, on: () => void, ic?: IconName): HTMLButtonElement {
  const b = h('button', `btn ${cls}`, ic ? icon(ic) : null, label);
  b.type = 'button';
  b.addEventListener('click', on);
  return b;
}

export const START_SERVER = 'policy/.venv/bin/python policy/server/site_data.py';

export function serverDown(what: string): HTMLElement {
  return h('div', 'empty',
    h('p', '', `${what} comes from the site server, and it does not answer.`),
    h('p', 'quiet', 'Start it with: ', h('code', '', START_SERVER)));
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { signal: AbortSignal.timeout(15_000) });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

export interface Tally { total: number; passed: number; failed: number; holds: number }

// One bar with room for its own numbers: the data row's large labelled bars.
export function outcomeBar(t: Tally, large = false): HTMLElement {
  const bar = h('div', large ? 'obar large' : 'obar');
  bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', `${t.passed} passed, ${t.failed} failed, ${t.holds} safe holds, of ${t.total}`);
  for (const [cls, n, word] of [['pass', t.passed, 'passed'], ['fail', t.failed, 'failed'], ['hold', t.holds, 'safe holds']] as const) {
    if (!n) continue;
    const part = h('span', `o-${cls}`, large && n / t.total > 0.1 ? String(n) : '');
    part.style.flexGrow = String(n);
    part.title = `${n} ${word}`;
    bar.append(part);
  }
  return bar;
}

export function resultWords(t: Tally): string {
  const parts = [`${t.passed} passed`, `${t.failed} failed`];
  if (t.holds) parts.push(`${t.holds} safe ${t.holds === 1 ? 'hold' : 'holds'}`);
  return parts.join(', ');
}

// A run's film is a sheet of frames. Moving across it plays the recorded run by hand.
export function filmStrip(url: string, label: string, cols = 6, rows = 4): HTMLElement {
  const box = h('div', 'film');
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', label);
  box.style.backgroundImage = `url(${url})`;
  box.style.backgroundSize = `${cols * 100}% ${rows * 100}%`;
  const show = (i: number) => {
    const n = Math.max(0, Math.min(cols * rows - 1, i));
    box.style.backgroundPosition = `${(n % cols) * 100 / (cols - 1)}% ${Math.floor(n / cols) * 100 / (rows - 1)}%`;
  };
  const rest = Math.floor((cols * rows) / 2);
  show(rest);
  box.addEventListener('pointermove', e => {
    const r = box.getBoundingClientRect();
    show(Math.floor(((e.clientX - r.left) / r.width) * cols * rows));
  });
  box.addEventListener('pointerleave', () => show(rest));
  return box;
}
