// What Overview and Failures both read: stored results from the site server, and the board. Nothing here is sample data.
import { api, type Bounty, type Budget, type Fixable } from '../board/api.ts';
import { getJson, h, type Kid, type Tally } from './ui.ts';
import './overview.css';

export interface World { id: string; name: string; group: string; kind: string; kind_name: string; outcome: 'pass' | 'fail' | 'hold'; reading: string; replay: string | null }
export interface Campaign extends Tally { id: string; label: string; robot: string; pack: string; kind: 'rows' | 'totals'; at: number | null; worlds: World[] }
export type Postable = Fixable & { pack?: string };

export const PACK_KEY = 'crashlab-pack'; // The same key simulation.ts and lab.html read.
export const campaigns = () => getJson<{ campaigns: Campaign[] }>('/site-api/data').then(d => d.campaigns);

// The board may be off. The page then says so, and shows no number for it.
export interface Board { bounties: Bounty[] | null; budget: Budget | null; fixable: Postable[] }
export async function board(): Promise<Board> {
  const [b, m, f] = await Promise.allSettled([api.bounties(), api.budget(), api.fixable()]);
  return { bounties: b.status === 'fulfilled' ? b.value.bounties : null, budget: m.status === 'fulfilled' ? m.value : null, fixable: f.status === 'fulfilled' ? f.value.fixable : [] };
}

const newestFirst = <T extends { at: number | null }>(list: T[]) => [...list].sort((a, b) => (b.at ?? 0) - (a.at ?? 0));
export const byNewest = (list: Campaign[]) => newestFirst(list);

// Open failures: failed worlds in the newest run of each robot that kept per-world results.
export function openRuns(list: Campaign[]): Campaign[] {
  const seen = new Map<string, Campaign>();
  for (const c of newestFirst(list)) if (c.kind === 'rows' && c.failed > 0 && !seen.has(c.pack)) seen.set(c.pack, c);
  return [...seen.values()];
}
export const OPEN_SCOPE = 'Failed worlds in the newest run of each robot.';

export interface FailKind { kind: string; name: string; count: number; run: Campaign }
export function failKinds(list: Campaign[]): FailKind[] {
  const out: FailKind[] = [];
  for (const run of openRuns(list)) {
    const counts = new Map<string, FailKind>();
    for (const w of run.worlds) {
      if (w.outcome !== 'fail') continue;
      const k = counts.get(w.kind) ?? { kind: w.kind, name: w.kind_name, count: 0, run };
      k.count += 1;
      counts.set(w.kind, k);
    }
    out.push(...counts.values());
  }
  return out.sort((a, b) => b.count - a.count);
}

export function postRef(fixable: Postable[], pack: string, kind: string): string | null {
  return fixable.find(f => !f.posted && f.pack === pack && f.group === kind)?.ref ?? null;
}

// A link that opens a robot in the tool. The pick goes where the tool reads it.
export function robotLink(cls: string, pack: string, href: string, ...kids: Kid[]): HTMLAnchorElement {
  const a = h('a', cls, ...kids);
  a.href = href;
  a.addEventListener('click', e => { e.stopPropagation(); pickRobot(pack); });
  return a;
}
export function pickRobot(pack: string) {
  try { sessionStorage.setItem(PACK_KEY, pack); } catch { /* no storage: the tool keeps its default robot */ }
}

export const askAi = (pack: string) => robotLink('ov-btn', pack, 'lab.html', 'Ask AI to fix');
export function postBounty(ref: string | null): HTMLAnchorElement {
  const a = h('a', 'ov-btn', 'Post a bounty');
  a.href = ref ? `bounties.html?post=${ref}` : 'bounties.html';
  a.addEventListener('click', e => e.stopPropagation());
  return a;
}

export function rowGo<T extends HTMLElement>(row: T, go: () => void, label: string): T {
  row.classList.add('go');
  row.tabIndex = 0;
  row.setAttribute('aria-label', label);
  row.addEventListener('click', go);
  row.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target === row) go(); });
  return row;
}

// "2 hours ago", only from a time the server gave.
export function ago(at: number | null): string {
  if (!at) return 'Unknown';
  const s = Math.max(0, Date.now() / 1000 - at);
  const say = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'} ago`;
  if (s < 60) return 'Just now';
  if (s < 3600) return say(Math.floor(s / 60), 'minute');
  if (s < 86400) return say(Math.floor(s / 3600), 'hour');
  if (s < 172800) return 'Yesterday';
  return say(Math.floor(s / 86400), 'day');
}
