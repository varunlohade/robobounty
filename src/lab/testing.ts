// Operating limits, the boundary search and the regression suite on the grid. The server's numbers, as they are. Results are simulated. Tested never means safe.
import { el } from '../app/dom.ts';
import type { ServerEvent } from '../app/chat/live.ts';
import './testing.css';

interface Band { runs: number; failed: number; moved: boolean }
interface Factor { key: string; label: string; unit: string; low: number; high: number; base: number | null; tested_low: number | null; tested_high: number | null; bands_touched: number; bands: number; band_rows: Band[]; worlds_moved: number; words: string }
interface Run { value: number; seed: number; role: string; status: string; verdict: string | null; reason?: string | null }
interface OneSearch { factor: string; label: string; unit: string; words: string | null; clean: boolean | null; status: string; runs: Run[]; pass_value: number | null; fail_value: number | null; fail_seeds?: [number, number]; pass_seeds?: [number, number] }
interface Group { verdict: string; verdict_name: string; count: number; world: string | null; seed: number | null; searches: OneSearch[]; words: string | null }
interface SuiteRow { id: string; name: string; seed: number; status: string; verdict: string | null; was: { status: string; verdict: string | null; code_sha: string }; change: string | null; words?: string; reason?: string }
export interface TestingDeps {
  base: string;
  verdictWord: (verdict: string | null, status: string) => string;
  showPanel: (mode: string, title: string, body: HTMLElement[]) => void;
  panelMode: () => string | undefined;
}

const COVERAGE_MS = 2000;
const num = (v: number) => String(Number(v.toFixed(4)));
const withUnit = (v: number, unit: string) => (unit ? `${num(v)} ${unit}` : num(v));
const short = (sha: string | undefined) => (sha ?? '').slice(0, 8);

function bandCells(f: Factor) {
  const box = el('span', 't-bands');
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', `${f.bands_touched} of ${f.bands} bands tested`);
  for (const b of f.band_rows) {
    const cell = el('i');
    cell.dataset.band = !b.runs ? 'none' : !b.moved ? 'start' : !b.failed ? 'passed' : b.failed === b.runs ? 'failed' : 'mixed';
    box.append(cell);
  }
  return box;
}

function section(title: string, body: (HTMLElement | null)[]) {
  const box = el('section', 'grid-section');
  box.append(el('h4', '', title), ...body.filter((b): b is HTMLElement => b !== null));
  return box;
}

export class Testing {
  readonly strip = el('div', 't-strip');
  readonly limitsBtn = el('button', 'grid-btn', 'Limits');
  readonly rerunBtn = el('button', 'grid-btn', 'Re-run failures');
  private coverage: ServerEvent | null = null;
  private fetchedAt = 0; private endedSeen = -1; private fetching = false;
  private boundary: ServerEvent | null = null;
  private suite: ServerEvent | null = null;
  private refusal = '';

  constructor(private deps: TestingDeps) {
    this.strip.hidden = true;
    this.limitsBtn.type = 'button';
    this.rerunBtn.type = 'button';
    this.rerunBtn.title = "Runs this robot's saved failed worlds on your current code, each on its own seed.";
    this.limitsBtn.addEventListener('click', () => this.toggle('limits', () => this.paintLimits()));
    this.rerunBtn.addEventListener('click', () => void this.rerun());
  }

  private toggle(mode: string, paint: () => void) {
    if (this.deps.panelMode() === mode) return this.deps.showPanel('', '', []);
    paint();
  }

  /** Each grid event: new finished runs change the coverage, and a search or suite run brings its live state. */
  onGrid(e: ServerEvent) {
    const ended = Number(e.counts?.passed ?? 0) + Number(e.counts?.failed ?? 0) + Number(e.counts?.stuck ?? 0) + Number(e.counts?.safe_hold ?? 0);
    if (ended !== this.endedSeen && performance.now() - this.fetchedAt > COVERAGE_MS) void this.loadCoverage(ended);
    const state = e.testing as ServerEvent | undefined;
    if (!state) return;
    if (state.kind === 'boundary') { this.boundary = state; if (this.deps.panelMode() === 'boundary') this.paintBoundary(); }
    if (state.kind === 'regressions') { this.suite = state; if (this.deps.panelMode() === 'regressions') this.paintSuite(); }
  }

  private async loadCoverage(ended: number) {
    if (this.fetching) return;
    this.fetching = true;
    this.fetchedAt = performance.now();
    try {
      const res = await fetch(`${this.deps.base}/limits`, { signal: AbortSignal.timeout(15_000) });
      if (res.ok) {
        const body = await res.json();
        if (body.factors?.length) { this.coverage = body; this.endedSeen = ended; this.paintStrip(); if (this.deps.panelMode() === 'limits') this.paintLimits(); }
      }
    } catch { /* The strip keeps its last numbers, and the next grid event asks again. */ }
    this.fetching = false;
  }

  private paintStrip() {
    const c = this.coverage;
    if (!c) return;
    const cells = (c.factors as Factor[]).map(f => {
      const cell = el('button', 't-factor');
      cell.type = 'button';
      cell.title = f.words;
      cell.dataset.key = f.key;
      const head = el('span', 't-factor-head');
      head.append(el('span', '', f.label), el('b', '', `${f.bands_touched} of ${f.bands}`));
      const span = (a: number, b: number) => (a < 0 || b < 0 ? `${num(a)} to ${num(b)}` : `${num(a)}\u2013${num(b)}`);
      const range = f.tested_low === null ? `limit ${span(f.low, f.high)} ${f.unit}` : f.tested_low === f.tested_high ? `only ${withUnit(f.tested_low, f.unit)} of ${span(f.low, f.high)}` : `${span(f.tested_low, f.tested_high!)} ${f.unit} of ${span(f.low, f.high)}`;
      cell.append(head, bandCells(f), el('span', 't-factor-range', range));
      cell.addEventListener('click', () => this.paintLimits());
      return cell;
    });
    const label = el('div', 't-strip-label');
    label.append(el('b', '', 'Tested'), el('span', '', `${c.bands_touched} of ${c.bands_total} bands`), el('span', 't-strip-not', 'Not a safety claim'));
    this.strip.replaceChildren(label, ...cells);
    this.strip.hidden = false;
    this.strip.dataset.factors = String(cells.length);
    this.limitsBtn.textContent = `Limits ${c.bands_touched}/${c.bands_total}`;
  }

  private legend() {
    const box = el('div', 't-legend');
    for (const [band, word] of [['none', 'Not tested'], ['start', 'Start value only'], ['passed', 'Moved, none failed'], ['mixed', 'Moved, some failed'], ['failed', 'Moved, all failed']]) {
      const row = el('span');
      const i = el('i');
      i.dataset.band = band;
      row.append(i, el('span', '', word));
      box.append(row);
    }
    return box;
  }

  private paintLimits() {
    const c = this.coverage;
    if (!c) { this.deps.showPanel('limits', 'Operating limits', [el('div', 'grid-rail-note', 'Loading the limits.')]); return; }
    const rows = (c.factors as Factor[]).map(f => {
      const row = el('div', 't-limit');
      const top = el('div', 't-limit-top');
      top.append(el('span', '', f.label), el('b', '', `${f.bands_touched} of ${f.bands} bands`));
      row.append(top, bandCells(f), el('div', 't-limit-words', f.words));
      row.append(el('div', 't-limit-words quiet', `${f.worlds_moved} ${f.worlds_moved === 1 ? 'world' : 'worlds'} moved it from the start value${f.base === null ? '' : `, ${withUnit(f.base, f.unit)}`}.`));
      return row;
    });
    const body: HTMLElement[] = [el('div', 'grid-rail-note', String(c.limits_words)), ...rows, this.legend()];
    const dropped = (c.dropped ?? []) as { name: string; reason: string }[];
    if (dropped.length) body.push(section(`Dropped, outside the limits: ${dropped.length}`, dropped.map(d => { const r = el('div', 't-dropped'); r.append(el('b', '', d.name.replaceAll('_', ' ')), el('span', '', d.reason)); return r; })));
    const find = el('button', 'grid-btn', 'Find the limit, 3 largest failure groups') as HTMLButtonElement;
    find.type = 'button';
    find.addEventListener('click', () => void this.findLimit());
    body.push(find, el('div', 'grid-rail-note', 'To change a limit, say it in the chat, for example: wind limit 0 to 12. A new limit applies to the next list.'), el('div', 'grid-rail-note', String(c.note)));
    this.deps.showPanel('limits', 'Operating limits', body);
  }

  private async post(body: Record<string, unknown>) {
    const url = this.deps.base.replace(/\/campaigns\/[^/]+$/, '/testing');
    const campaign = this.deps.base.match(/\/campaigns\/([^/]+)$/)?.[1];
    this.refusal = '';
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...body, campaign }), signal: AbortSignal.timeout(15_000) });
      if (!res.ok) this.refusal = (await res.json().catch(() => ({}))).words ?? `HTTP ${res.status}`;
    } catch (err) { this.refusal = String(err); }
  }

  /** The button in a failed world's panel, and the one for the largest groups. */
  async findLimit(group?: string, index?: number) {
    this.boundary = { type: 'testing', kind: 'boundary', groups: [], running: true };
    this.paintBoundary();
    await this.post({ what: 'boundary', group, index });
    if (this.refusal) await this.reloadBoundary();
    this.paintBoundary();
  }

  private async reloadBoundary() {
    const res = await fetch(`${this.deps.base}/boundary`, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
    if (res?.ok) this.boundary = await res.json();
  }

  private tile(r: { status: string; verdict: string | null }, top: string, title: string) {
    const tile = el('div', 't-tile');
    tile.dataset.status = r.status;
    tile.title = title;
    tile.append(el('b', '', top), el('span', '', this.deps.verdictWord(r.verdict, r.status)));
    return tile;
  }

  // A number line from the passing end to the failing end. One tick per same-seed run, and dots for the extra seeds.
  private line(s: OneSearch) {
    const values = s.runs.map(r => r.value);
    const lo = Math.min(...values), hi = Math.max(...values);
    if (!Number.isFinite(lo) || lo === hi) return null;
    const NS = 'http://www.w3.org/2000/svg', W = 296, PAD = 8, H = 46, AXIS = 28;
    const x = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - PAD * 2);
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 't-line');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${s.label} from ${num(lo)} to ${withUnit(hi, s.unit)}, each run marked by its result.`);
    const add = (tag: string, attrs: Record<string, string | number>, text?: string) => { const n = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (text) n.textContent = text; svg.append(n); };
    const ink: Record<string, string> = { passed: '#5CC186', held: '#E3B04F', failed: '#F27B73', stuck: '#F27B73', running: '#ECEEF1', queued: '#4B515B' };
    add('line', { x1: PAD, y1: AXIS, x2: W - PAD, y2: AXIS, stroke: 'rgba(255,255,255,.18)', 'stroke-width': 1 });
    if (s.pass_value !== null && s.fail_value !== null) {
      const a = x(s.pass_value), b = x(s.fail_value);
      add('rect', { x: Math.min(a, b) - 1, y: AXIS - 13, width: Math.max(2, Math.abs(b - a) + 2), height: 15, fill: 'rgba(62,123,250,.28)' });
    }
    const stack = new Map<number, number>();
    for (const r of s.runs) {
      const px = x(r.value);
      if (r.role.startsWith('seed')) {
        const n = stack.get(r.value) ?? 0;
        stack.set(r.value, n + 1);
        add('circle', { cx: px, cy: AXIS - 17 - n * 5, r: 2, fill: ink[r.status] ?? ink.queued });
      } else add('line', { x1: px, y1: AXIS - 8, x2: px, y2: AXIS + 3, stroke: ink[r.status] ?? ink.queued, 'stroke-width': 2 });
    }
    add('text', { x: PAD, y: H - 3, fill: '#A3A9B3', 'font-size': 11 }, withUnit(lo, s.unit));
    add('text', { x: W - PAD, y: H - 3, fill: '#A3A9B3', 'font-size': 11, 'text-anchor': 'end' }, withUnit(hi, s.unit));
    return svg as unknown as HTMLElement;
  }

  private searchBox(s: OneSearch) {
    const box = el('div', 't-search');
    box.dataset.clean = String(s.clean);
    const said = s.words ?? `Searching ${s.label.toLowerCase()}: ${s.runs.length} of at most 12 runs so far.`;
    box.append(el('div', 't-said', said));
    const line = this.line(s);
    if (line) box.append(line);
    const rows: [string, Run[]][] = [['Same seed, bisection', s.runs.filter(r => !r.role.startsWith('seed'))], ['More seeds, failing side', s.runs.filter(r => r.role === 'seed, failing side')], ['More seeds, passing side', s.runs.filter(r => r.role === 'seed, passing side')]];
    for (const [word, runs] of rows) {
      if (!runs.length) continue;
      const tiles = el('div', 't-tiles');
      for (const r of runs) tiles.append(this.tile(r, withUnit(r.value, s.unit), `${s.label} ${withUnit(r.value, s.unit)}, seed ${r.seed}, ${r.role}`));
      box.append(el('div', 't-row-word', word), tiles);
    }
    return box;
  }

  private paintBoundary() {
    const b = this.boundary;
    const body: HTMLElement[] = [];
    if (this.refusal) body.push(el('div', 'grid-rail-note bad', this.refusal));
    if (!b || (!b.groups?.length && !b.words)) body.push(el('div', 'grid-rail-note', b?.empty ? 'No search has run for this campaign yet.' : 'Starting the search.'));
    if (b?.recorded) body.push(el('div', 'grid-rail-note', 'Recorded result of an earlier real search. No sim runs here.'));
    if (b?.words) body.push(el('div', 'grid-text', String(b.words)));
    for (const g of (b?.groups ?? []) as Group[]) {
      const parts: (HTMLElement | null)[] = [g.world ? el('div', 'grid-rail-note', `From ${g.world.replaceAll('_', ' ')}, seed ${g.seed}. ${g.count} ${g.count === 1 ? 'world' : 'worlds'} in this group.`) : null, g.words ? el('div', 't-said', g.words) : null];
      for (const s of g.searches) parts.push(this.searchBox(s));
      body.push(section(`Failure group: ${g.verdict_name}`, parts));
    }
    if (b?.note) body.push(el('div', 'grid-rail-note', String(b.note)));
    this.deps.showPanel('boundary', b?.running ? 'Finding the limit' : 'The limit', body);
  }

  private async rerun() {
    if (this.deps.panelMode() === 'regressions') return this.deps.showPanel('', '', []);
    const res = await fetch(`${this.deps.base}/regressions`, { signal: AbortSignal.timeout(15_000) }).catch(() => null);
    const state = res?.ok ? await res.json() : null;
    this.suite = { type: 'testing', kind: 'regressions', size: state?.size ?? 0, last: state?.last ?? null, idle: true };
    this.paintSuite();
  }

  private paintSuite() {
    const s = this.suite;
    const body: HTMLElement[] = [];
    if (this.refusal) body.push(el('div', 'grid-rail-note bad', this.refusal));
    if (s?.recorded) body.push(el('div', 'grid-rail-note', 'Recorded result of an earlier real suite run. No sim runs here.'));
    if (s?.idle) {
      const last = s.last as { run?: number; code_sha?: string; counts?: Record<string, number> } | null;
      body.push(el('div', 'grid-text', `${s.size} failed ${s.size === 1 ? 'world' : 'worlds'} saved for this robot. Each runs on its own seed, on your current code.`));
      if (last?.counts) body.push(this.counts(last.counts), el('div', 'grid-rail-note', `Last result: run ${last.run}, code ${short(last.code_sha)}.`));
      const go = el('button', 'grid-btn t-go', `Run ${s.size} ${s.size === 1 ? 'world' : 'worlds'} now`) as HTMLButtonElement;
      go.type = 'button';
      go.disabled = !s.size;
      go.addEventListener('click', () => void this.startSuite());
      body.push(go);
    } else if (s) {
      if (s.counts) body.push(this.counts(s.counts as Record<string, number>));
      body.push(el('div', 'grid-rail-note', `Code ${short(s.code_sha as string)}${s.edited ? ', your edit' : ', the original'}.${s.words ? ` ${s.words}` : ''}`));
      const order = ['new_failure', 'fixed', 'still_failing', 'passes_same_code', 'world_changed', 'could_not_run', 'still_passing', null];
      const rows = [...((s.rows ?? []) as SuiteRow[])].sort((a, b) => order.indexOf(a.change) - order.indexOf(b.change));
      for (const r of rows) {
        const row = el('div', 't-suite');
        row.dataset.change = r.change ?? 'running';
        row.dataset.status = r.status;
        const top = el('div', 't-suite-top');
        top.append(el('b', '', r.name.replaceAll('_', ' ')), el('span', 't-change', r.words ?? this.deps.verdictWord(r.verdict, r.status)));
        row.append(top, el('div', 't-suite-was', `Seed ${r.seed}. Was ${this.deps.verdictWord(r.was.verdict, r.was.status)} on ${short(r.was.code_sha)}. Now ${this.deps.verdictWord(r.verdict, r.status)}.`));
        body.push(row);
      }
    }
    body.push(el('div', 'grid-rail-note', 'Same world, same seed, each time. Only a code change that stops the failure counts as fixed. Simulated.'));
    this.deps.showPanel('regressions', 'Re-run failures', body);
  }

  private counts(c: Record<string, number>) {
    const box = el('div', 't-counts');
    for (const [key, word] of [['fixed', 'Fixed'], ['still_failing', 'Still failing'], ['new_failure', 'New failures']]) {
      const n = el('div', 't-count');
      n.dataset.key = key;
      n.dataset.some = String((c[key] ?? 0) > 0);
      n.append(el('b', '', String(c[key] ?? 0)), el('span', '', word));
      box.append(n);
    }
    return box;
  }

  private async startSuite() {
    this.suite = { type: 'testing', kind: 'regressions', rows: [], code_sha: '', running: true, counts: null };
    await this.post({ what: 'regressions' });
    this.paintSuite();
  }
}
