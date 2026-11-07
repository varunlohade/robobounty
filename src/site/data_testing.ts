// The Data page's limits coverage and regression suite tables. Numbers come from stored run files. All simulated. Tested never means safe.
import { plainNote } from './plain_note.ts';
import { h } from './ui.ts';

interface Band { runs: number; failed: number; moved: boolean }
interface CoverageFactor { key: string; label: string; unit: string; low: number; high: number; tested_low: number | null; tested_high: number | null; bands_touched: number; bands: number; band_rows: Band[]; worlds_moved: number; runs: number; outside: number }
export interface Coverage { factors: CoverageFactor[]; runs: number; bands_touched: number; bands_total: number; note: string; limits_words: string; dropped: { name: string; reason: string }[] }
interface Result { status: string; verdict: string | null; code_sha: string; change?: string; run?: number | null }
interface Entry { id: string; name: string; group: string; seed: number; first: Result; last: Result; history: Result[] }
interface SuiteRun { run: number; at: number; code_sha: string; edited: boolean; counts: Record<string, number>; worlds: number }
interface Suite { robot: string; entries: Entry[]; runs: SuiteRun[]; note: string; recorded?: boolean }
export type Suites = Record<string, Suite>;

const num = (v: number) => String(Number(v.toFixed(4)));
const withUnit = (v: number, unit: string) => (unit ? `${num(v)} ${unit}` : num(v));
const words = (s: string | null) => (s ?? 'unknown').replaceAll('_', ' ');
const short = (sha: string) => sha.slice(0, 8);
const failing = (r: { status: string }) => r.status === 'failed' || r.status === 'stuck';

function bands(f: CoverageFactor) {
  const box = h('span', 'bands');
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', `${f.bands_touched} of ${f.bands} bands`);
  for (const b of f.band_rows) box.append(h('i', !b.runs ? 'b-none' : !b.moved ? 'b-start' : !b.failed ? 'b-pass' : b.failed === b.runs ? 'b-fail' : 'b-mix'));
  return box;
}

export function coverageTable(c: Coverage): HTMLElement {
  const body = h('tbody');
  for (const f of c.factors) {
    const tested = f.tested_low === null ? 'No finished run' : f.tested_low === f.tested_high ? `Only ${withUnit(f.tested_low, f.unit)}` : `${num(f.tested_low)} to ${withUnit(f.tested_high!, f.unit)}`;
    body.append(h('tr', '', h('td', 'main', f.label), h('td', '', `${num(f.low)} to ${withUnit(f.high, f.unit)}`), h('td', '', tested), h('td', '', bands(f)), h('td', 'num', `${f.bands_touched} of ${f.bands}`), h('td', 'num', String(f.worlds_moved)), h('td', 'num hide-s', String(f.outside))));
  }
  const head = h('tr', '', h('th', '', 'Factor'), h('th', '', 'Operating limit'), h('th', '', 'Tested'), h('th', '', 'Bands'), h('th', 'num', 'Bands tested'), h('th', 'num', 'Worlds moved it'), h('th', 'num hide-s', 'Runs outside'));
  const out = h('div', '', h('div', 'chart-h', h('h2', '', 'Operating limits: what this campaign tested'), h('span', '', `${c.bands_touched} of ${c.bands_total} bands, ${c.runs} runs`)), h('table', '', h('thead', '', head), body),
    h('p', 'quiet', `${c.limits_words} ${plainNote(c.note)}`), h('p', 'legendline quiet', h('i', 'b-none'), 'Not tested', h('i', 'b-start'), 'Start value only', h('i', 'b-pass'), 'Moved, none failed', h('i', 'b-mix'), 'Moved, some failed', h('i', 'b-fail'), 'Moved, all failed'));
  if (c.dropped?.length) out.append(h('p', 'quiet', `Dropped for being outside the limits: ${c.dropped.length}. ${c.dropped.slice(0, 3).map(d => `${words(d.name)}: ${d.reason}`).join(' ')}`));
  return out;
}

function historyCells(e: Entry) {
  const box = h('span', 'hist');
  const cell = (r: Result, title: string) => { const i = h('i', failing(r) ? 'b-fail' : r.status === 'held' ? 'b-hold' : 'b-pass'); i.title = title; box.append(i); };
  cell(e.first, `First: ${words(e.first.verdict)} on ${short(e.first.code_sha)}`);
  for (const r of e.history) cell(r, `Run ${r.run}: ${words(r.verdict)} on ${short(r.code_sha)}`);
  return box;
}

export function suiteTables(s: Suite): HTMLElement[] {
  const title = h('div', 'chart-h', h('h2', '', `Regression suite: ${s.robot}`), h('span', '', `${s.entries.length} saved failed worlds, ${s.runs.length} suite runs`));
  if (!s.entries.length) return [title, h('p', 'quiet', 'The suite is empty. Failed worlds join it when a campaign ends on the lab server.')];
  const rows = h('tbody');
  for (const e of [...s.entries].sort((a, b) => Number(failing(b.last)) - Number(failing(a.last)))) {
    rows.append(h('tr', '', h('td', 'main clip', words(e.name)), h('td', 'num', String(e.seed)), h('td', '', `${words(e.first.verdict)}`), h('td', 'mono', short(e.first.code_sha)), h('td', failing(e.last) ? 'tone-bad' : 'tone-ok', failing(e.last) ? `Failing: ${words(e.last.verdict)}` : `Not failing: ${words(e.last.verdict)}`), h('td', 'mono', short(e.last.code_sha)), h('td', '', historyCells(e))));
  }
  const head = h('tr', '', h('th', '', 'World'), h('th', 'num', 'Seed'), h('th', '', 'First failed with'), h('th', '', 'On code'), h('th', '', 'Last result'), h('th', '', 'On code'), h('th', '', 'History, oldest first'));
  const runs = h('tbody');
  for (const r of [...s.runs].reverse()) {
    runs.append(h('tr', '', h('td', 'num', String(r.run)), h('td', '', new Date(r.at * 1000).toLocaleString()), h('td', 'mono', short(r.code_sha)), h('td', '', r.edited ? 'Edited copy' : 'Original'), h('td', 'num', String(r.worlds)), h('td', `num ${r.counts.fixed ? 'tone-ok' : ''}`, String(r.counts.fixed ?? 0)), h('td', `num ${r.counts.still_failing ? 'tone-bad' : ''}`, String(r.counts.still_failing ?? 0)), h('td', `num ${r.counts.new_failure ? 'tone-bad' : ''}`, String(r.counts.new_failure ?? 0))));
  }
  const runHead = h('tr', '', h('th', 'num', 'Run'), h('th', '', 'When'), h('th', '', 'Code'), h('th', '', 'Controller'), h('th', 'num', 'Worlds'), h('th', 'num', 'Fixed'), h('th', 'num', 'Still failing'), h('th', 'num', 'New failures'));
  return [title, h('table', 'suite-worlds', h('thead', '', head), rows), s.runs.length ? h('table', 'suite-runs', h('thead', '', runHead), runs) : h('p', 'quiet', 'No suite run yet. Press Re-run failures on the grid.'), h('p', 'quiet', `${s.recorded ? 'Recorded from an earlier real run. ' : ''}${s.note}`)];
}
