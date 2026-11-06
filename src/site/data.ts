import { mountShell } from './shell.ts';
import { icon } from './icons.ts';
import { filmStrip, getJson, h, link, outcomeBar, resultWords, serverDown, type Tally } from './ui.ts';

interface World {
  id: string; group: string; name: string; kind: string; kind_name: string; outcome: 'pass' | 'fail' | 'hold'; at: number | null; reading: string; line: string; repeat: string; flaky: boolean;
  reason: string; changes: string[]; seed: number | null; film: string | null; replay: string | null; bounds?: Record<string, number | null>;
}
interface Campaign extends Tally { id: string; label: string; robot: string; pack: string; sim: string | null; source: string; kind: 'rows' | 'totals'; note: string; held_back: number; worlds: World[] }
type SortKey = 'id' | 'group' | 'kind_name' | 'at' | 'reading' | 'repeat' | 'line';

const { main, setStatus } = mountShell({ page: 'data', title: 'Data', subtitle: 'Campaign results. All simulated.' });
const wrap = h('div', 'datawrap');
const page = h('div', 'scroll');
const drawer = h('aside', 'drawer');
drawer.setAttribute('aria-label', 'Run detail');
wrap.append(page, drawer);
main.append(wrap);

const params = new URLSearchParams(location.search);
let campaigns: Campaign[] = [];
let current: Campaign;
let query = params.get('q') ?? '';
let outcome: 'all' | 'pass' | 'fail' | 'hold' = 'all';
let type: string | null = null;
let sortKey: SortKey = 'at';
let sortUp = true;
let openId: string | null = null;

const campaignBox = h('div', 'campaigns');
const summary = h('div', 'summary');
const charts = h('div', 'charts');
const libHead = h('div', 'libhead');
const libBody = h('div', 'lib');
const input = Object.assign(h('input'), { type: 'search', placeholder: 'Search worlds', id: 'lib-search' });
input.setAttribute('aria-label', 'Search the failure library');
input.value = query;
const count = h('span', 'count');
const key = h('kbd', '', '/');
const field = h('label', 'field', icon('search'), input, count, key);
const chips = h('div', 'chips');
libHead.append(h('h2', '', 'Failure library'), chips, field);
page.append(campaignBox, summary, charts, libHead, libBody);

const swatch = (w: World) => (w.outcome === 'pass' ? 'c-pass' : w.outcome === 'hold' ? 'c-hold' : `c-${w.kind} c-fail`);

function filtered(): World[] {
  const q = query.trim().toLowerCase();
  const rows = current.worlds.filter(w => (outcome === 'all' || w.outcome === outcome) && (!type || w.kind === type)
    && (!q || [w.id, w.name, w.group, w.kind_name, w.reading, w.line, w.reason, ...w.changes].join(' ').toLowerCase().includes(q)));
  const dir = sortUp ? 1 : -1;
  return rows.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * dir;
    return String(x).localeCompare(String(y), undefined, { numeric: true }) * dir;
  });
}

function paintCampaigns() {
  const body = h('tbody');
  for (const c of campaigns) {
    const tr = h('tr', 'row', h('td', 'main', c.label), h('td', 'hide-n', c.robot), h('td', 'num', String(c.total)), h('td', 'num', String(c.passed)), h('td', 'num', String(c.failed)), h('td', 'num', String(c.holds)),
      h('td', 'hide-s', outcomeBar(c)), h('td', 'mono', c.sim ?? 'unknown'), h('td', 'hide-s', c.kind === 'rows' ? 'Each world' : 'Totals only'));
    tr.tabIndex = 0;
    tr.dataset.id = c.id;
    tr.setAttribute('aria-selected', String(c.id === current.id));
    const go = () => pick(c);
    tr.addEventListener('click', go);
    tr.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
    body.append(tr);
  }
  const head = h('tr', '', h('th', '', 'Campaign'), h('th', 'hide-n', 'Robot'), h('th', 'num', 'Worlds'), h('th', 'num', 'Passed'), h('th', 'num', 'Failed'), h('th', 'num', 'Safe holds'), h('th', 'hide-s', 'Outcome'), h('th', '', 'Sim version'), h('th', 'hide-s', 'Stored'));
  campaignBox.replaceChildren(h('table', '', h('thead', '', head), body));
}

function paintSummary() {
  const n = (value: number, word: string, cls = '') => h('div', `n ${cls}`, h('b', '', String(value)), h('span', '', word));
  const held = current.held_back ? `, ${current.held_back} held back and not run` : '';
  summary.replaceChildren(n(current.total, 'Worlds run'), n(current.passed, 'Passed'), n(current.failed, 'Failed', 'f'), n(current.holds, 'Safe holds'),
    h('div', 'barbox', h('div', 'legend', h('span', '', `${current.label}${held}`), h('span', 'mono', current.source)), outcomeBar(current, true)));
}

function paintMap(): HTMLElement {
  const box = h('div', 'wide');
  box.append(h('div', 'chart-h', h('h2', '', 'Every world'), h('span', '', 'One square, one world')));
  const readout = h('div', 'readout', 'Point at a square to read its world. Click it to open the run.');
  const map = h('div', 'map');
  const groups = [...new Set(current.worlds.map(w => w.group))];
  for (const g of groups) {
    const row = h('div', 'cellrow');
    for (const w of current.worlds.filter(x => x.group === g)) {
      const cell = h('button', swatch(w));
      cell.type = 'button';
      cell.setAttribute('aria-label', `${w.id}, ${w.kind_name}`);
      cell.classList.toggle('on', w.id === openId);
      const say = () => readout.replaceChildren(h('b', '', `${w.name} ${w.kind_name}`), w.at !== null ? ` at ${w.at} s` : '', h('br'), w.reading || w.group);
      cell.addEventListener('pointerenter', say);
      cell.addEventListener('focus', say);
      cell.addEventListener('click', () => openRun(w.id));
      row.append(cell);
    }
    const label = h('div', 'g', g);
    label.title = g;
    map.append(h('div', 'mapgroup', label, row));
  }
  box.append(map, readout);
  return box;
}

function paintTypes(): HTMLElement {
  const counts = new Map<string, { name: string; kind: string; n: number; flaky: number; sample: World }>();
  for (const w of current.worlds) {
    if (w.outcome === 'pass') continue;
    const t = counts.get(w.kind) ?? { name: w.kind_name, kind: w.kind, n: 0, flaky: 0, sample: w };
    t.n += 1;
    if (w.flaky) t.flaky += 1;
    counts.set(w.kind, t);
  }
  const rows = [...counts.values()].sort((a, b) => b.n - a.n);
  const top = rows[0]?.n ?? 1;
  const list = h('div', 'typebars');
  for (const t of rows) {
    const bar = h('i', swatch(t.sample));
    bar.style.width = `${(t.n / top) * 100}%`;
    const b = h('button', '', h('span', '', t.name), h('span', '', String(t.n), t.flaky ? h('span', 'flaky', ` ${t.flaky} flaky`) : null), bar);
    b.type = 'button';
    b.setAttribute('aria-pressed', String(type === t.kind));
    b.addEventListener('click', () => { type = type === t.kind ? null : t.kind; paintTables(); });
    list.append(b);
  }
  return h('div', '', h('div', 'chart-h', h('h2', '', 'Failure types'), h('span', '', `${rows.reduce((s, t) => s + t.n, 0)} worlds`)), rows.length ? list : h('p', 'quiet', 'No failures in this campaign.'));
}

function axis(word: string, bound: string, lo: number, hi: number): HTMLElement | null {
  const rows = current.worlds.filter(w => w.bounds && typeof w.bounds[bound] === 'number');
  if (rows.length < 4) return null;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 300 22');
  svg.setAttribute('height', '22');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${word}: tall tick failed, short tick passed or held`);
  const line = (x1: number, y1: number, x2: number, y2: number, stroke: string, width = 1.5) => {
    const l = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    for (const [k, v] of Object.entries({ x1, y1, x2, y2, stroke, 'stroke-width': width })) l.setAttribute(k, String(v));
    svg.append(l);
  };
  line(0, 20, 300, 20, 'rgba(255,255,255,.14)', 1);
  for (const w of rows) {
    const x = ((w.bounds![bound]! - lo) / (hi - lo)) * 300;
    if (w.outcome === 'fail') line(x, 4, x, 20, '#E5534B');
    else line(x, 12, x, 20, w.outcome === 'pass' ? '#C9CED6' : '#979EA9');
  }
  return h('div', '', h('div', 'top', h('span', '', word), h('span', '', `${lo} to ${hi}`)), svg);
}

function paintBounds(): HTMLElement {
  const axes = [axis('Gust speed, m/s', 'gust', 0, 50), axis('Wetness, 0 to 1', 'wet', 0, 1), axis('Steady wind, m/s', 'wind', 0, 25), axis('Edge margin, m', 'edge', 0, 1.2)].filter(Boolean) as HTMLElement[];
  return h('div', '', h('div', 'chart-h', h('h2', '', 'Boundary values'), h('span', '', 'Tall tick failed')), h('div', 'ticks', ...axes));
}

function paintCharts() {
  charts.hidden = current.kind === 'totals';
  if (charts.hidden) return;
  const bounds = current.worlds.some(w => w.bounds);
  charts.classList.toggle('two', !bounds);
  charts.replaceChildren(paintMap(), paintTypes(), ...(bounds ? [paintBounds()] : []));
}

function highlighted(text: string): (Node | string)[] {
  const q = query.trim();
  const at = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (at < 0) return [text];
  return [text.slice(0, at), h('mark', '', text.slice(at, at + q.length)), text.slice(at + q.length)];
}

const COLUMNS: [SortKey, string, string][] = [['id', 'World', ''], ['group', 'Group', 'clip'], ['kind_name', 'Outcome', ''], ['at', 'Fails at, s', 'num'], ['reading', 'Reading', ''], ['repeat', 'Re-runs', 'hide-n'], ['line', 'Code line', 'hide-s']];

function paintLibrary() {
  if (current.kind === 'totals') {
    libHead.hidden = true;
    libBody.replaceChildren(h('div', 'empty', h('p', '', 'This campaign kept totals only. No world rows are on disk.'), h('p', 'quiet', `Source: ${current.source}`)));
    return;
  }
  libHead.hidden = false;
  const rows = filtered();
  count.textContent = `${rows.length} of ${current.worlds.length}`;
  const tally = { all: current.worlds.length, pass: current.passed, fail: current.failed, hold: current.holds };
  chips.replaceChildren(...(['all', 'fail', 'hold', 'pass'] as const).map(o => {
    const b = h('button', '', { all: 'All', fail: 'Failed', hold: 'Safe holds', pass: 'Passed' }[o], h('i', '', String(tally[o])));
    b.type = 'button';
    b.setAttribute('aria-pressed', String(outcome === o));
    b.addEventListener('click', () => { outcome = o; type = null; paintTables(); });
    return b;
  }));
  const head = h('tr');
  for (const [k, word, cls] of COLUMNS) {
    const th = h('th', `sort ${cls}`, word);
    th.dataset.sort = k;
    if (sortKey === k) {
      th.setAttribute('aria-sort', sortUp ? 'ascending' : 'descending');
      const ar = icon(sortUp ? 'up' : 'down', 12);
      ar.classList.add('ar');
      th.append(ar);
    }
    th.tabIndex = 0;
    const go = () => { if (sortKey === k) sortUp = !sortUp; else { sortKey = k; sortUp = true; } paintLibrary(); };
    th.addEventListener('click', go);
    th.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
    head.append(th);
  }
  const body = h('tbody');
  for (const w of rows) {
    const tr = h('tr', 'row', h('td', 'main mono', ...highlighted(w.id)), h('td', 'clip', ...highlighted(w.group)),
      h('td', '', h('span', `sw ${swatch(w)}`), ...highlighted(w.kind_name)), h('td', 'num', w.at === null ? '' : w.at.toFixed(2)), h('td', '', ...highlighted(w.reading)),
      h('td', w.flaky ? 'flaky hide-n' : 'hide-n', w.flaky ? `Flaky, ${w.repeat}` : w.repeat), h('td', 'mono hide-s', ...highlighted(w.line)));
    tr.tabIndex = 0;
    tr.dataset.id = w.id;
    tr.setAttribute('aria-selected', String(w.id === openId));
    tr.addEventListener('click', () => openRun(w.id));
    tr.addEventListener('keydown', e => {
      if (e.key === 'Enter') openRun(w.id);
      const next = e.key === 'ArrowDown' ? tr.nextElementSibling : e.key === 'ArrowUp' ? tr.previousElementSibling : null;
      if (next) { e.preventDefault(); (next as HTMLElement).focus(); }
    });
    body.append(tr);
  }
  libBody.replaceChildren(rows.length
    ? h('table', '', h('thead', '', head), body)
    : h('div', 'empty', h('p', '', 'No world matches.'), h('p', 'quiet', 'Clear the search or pick another outcome.')));
}

function paintTables() {
  paintLibrary();
  charts.querySelectorAll('.typebars button').forEach((b, i) => {
    const pressed = [...charts.querySelectorAll('.typebars button')][i];
    pressed.setAttribute('aria-pressed', String(!!type && pressed.firstElementChild?.textContent === current.worlds.find(w => w.kind === type)?.kind_name));
  });
}

function closeRun() {
  openId = null;
  drawer.classList.remove('on');
  libBody.querySelectorAll('tr[aria-selected=true]').forEach(r => r.setAttribute('aria-selected', 'false'));
}

function openRun(id: string) {
  const w = current.worlds.find(x => x.id === id);
  if (!w) return;
  openId = id;
  libBody.querySelectorAll<HTMLElement>('tr.row').forEach(r => r.setAttribute('aria-selected', String(r.dataset.id === id)));
  const close = h('button', 'x', icon('x', 16));
  close.type = 'button';
  close.setAttribute('aria-label', 'Close');
  close.addEventListener('click', closeRun);
  const dl = h('dl');
  const add = (k: string, v: string | null | undefined, mono = false) => { if (v) dl.append(h('dt', '', k), h('dd', mono ? 'mono' : '', v)); };
  add('Campaign', current.label);
  add('Group', w.group);
  add('Reading', w.reading);
  add('Fails at', w.at === null ? null : `${w.at} s`);
  add('Change', w.changes.join(', '), true);
  add('Seed', w.seed === null ? null : String(w.seed));
  add('Re-runs', w.flaky ? `Flaky, ${w.repeat}` : w.repeat);
  add('Code line', w.line, true);
  add('Sim', current.sim, true);
  drawer.replaceChildren(
    w.film ? filmStrip(w.film, `Frames from ${w.name}. Move across to step through them.`) : h('div', ''),
    h('div', 'in',
      h('div', 'top', h('h2', '', `${w.name}: ${w.kind_name}`), close),
      w.reason ? h('p', '', w.reason) : null,
      dl,
      w.replay ? link('btn pri wide', w.replay, icon('play'), 'Replay the recorded run') : h('p', 'quiet', 'This run kept its numbers only. It has no stored replay.'),
      h('p', 'quiet', current.note)));
  drawer.classList.add('on');
}

function pick(c: Campaign) {
  current = c;
  outcome = 'all';
  type = null;
  closeRun();
  const url = new URL(location.href);
  url.searchParams.set('c', c.id);
  history.replaceState(null, '', url);
  sortKey = 'at';
  sortUp = true;
  paintCampaigns();
  campaignBox.querySelector('tr[aria-selected=true]')?.scrollIntoView({ block: 'nearest' });
  paintSummary();
  paintCharts();
  paintLibrary();
  setStatus(c.note, c.sim ? [`sim ${c.sim}`, resultWords(c)] : [resultWords(c)]);
}

input.addEventListener('input', () => { query = input.value; paintLibrary(); });
input.addEventListener('keydown', e => {
  if (e.key === 'Escape') { input.value = ''; query = ''; paintLibrary(); input.blur(); }
  if (e.key === 'ArrowDown') { e.preventDefault(); libBody.querySelector<HTMLElement>('tr.row')?.focus(); }
});
document.addEventListener('keydown', e => {
  const typing = document.activeElement === input;
  if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); input.focus(); input.select(); }
  if (e.key === 'Escape' && openId) closeRun();
});

getJson<{ campaigns: Campaign[] }>('/site-api/data').then(d => {
  campaigns = d.campaigns;
  if (!campaigns.length) { page.replaceChildren(h('div', 'empty', h('p', '', 'No campaigns on disk yet.'), h('p', 'quiet', 'Open CrashLab and run a batch.'))); return; }
  pick(campaigns.find(c => c.id === params.get('c')) ?? campaigns[0]);
}).catch(() => { page.replaceChildren(serverDown('This page')); });
