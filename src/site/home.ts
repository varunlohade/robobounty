import { mountShell } from './shell.ts';
import { icon } from './icons.ts';
import { h, link, resultWords, serverDown, type Tally } from './ui.ts';
import { ago, askAi, board, byNewest, campaigns, failKinds, OPEN_SCOPE, openRuns, pickRobot, postBounty, postRef, robotLink, rowGo, type Board, type Campaign } from './overview_data.ts';

const { main, actions, who } = mountShell({ page: 'home', title: 'Overview', subtitle: 'Simulated' });
const page = h('div', 'scroll ov');
main.append(page);

const newSim = (off: boolean) => {
  if (!off) return link('ov-pill', 'simulation.html', icon('plus', 15), 'New simulation');
  const b = h('button', 'ov-pill', icon('plus', 15), 'New simulation');
  b.disabled = true;
  b.title = 'Add a robot first.';
  return b;
};

function stat(label: string, value: string, note: string, href: string | null) {
  const kids = [h('span', '', label), h('b', /^[0-9,]+$/.test(value) ? '' : 'word', value), h('i', '', note)];
  return href ? link('ov-st', href, ...kids) : h('div', 'ov-st', ...kids);
}
const share = (n: number, all: number) => all ? `${Math.round(n * 100 / all)}% of worlds` : '';
const sum = (list: Campaign[], key: keyof Tally) => list.reduce((n, c) => n + c[key], 0);

function bountyCounts(b: Board) {
  const list = b.bounties ?? [];
  const paid = list.filter(x => x.status === 'claimed');
  const checking = list.filter(x => x.status !== 'claimed' && (x.status !== 'open' || (x.checking ?? 0) > 0));
  return { open: list.length - paid.length - checking.length, checking: checking.length, paid: paid.length, units: list.reduce((n, x) => n + (x.balance?.claimed ?? 0), 0) };
}

function budgetStat(b: Board) {
  if (!b.budget) return stat('Budget', 'No reply', 'Board is off', 'bounties.html');
  if (!b.budget.funded) return stat('Budget', 'Not set', 'Local test units', 'bounties.html');
  return stat('Budget', (b.budget.left ?? 0).toLocaleString('en'), 'Local test units left', 'bounties.html');
}

function bar(r: Tally, widest: number) {
  const box = h('div', 'ov-bar');
  box.style.width = `${(r.total / widest) * 100}%`;
  box.setAttribute('role', 'img');
  box.setAttribute('aria-label', resultWords(r));
  for (const [cls, n] of [['pass', r.passed], ['fail', r.failed], ['hold', r.holds]] as const) {
    if (!n) continue;
    const part = h('u', cls);
    part.style.flexGrow = String(n);
    box.append(part);
  }
  return box;
}

function runsTable(list: Campaign[]) {
  const runs = byNewest(list).slice(0, 5);
  const widest = Math.max(...runs.map(r => r.total), 1);
  const body = h('tbody', '', ...runs.map(r => rowGo(h('tr', '',
    h('td', 'nw', h('b', '', r.label)), h('td', 'hs nw', r.robot), h('td', 'n hs', String(r.total)),
    h('td', 'ov-out', bar(r, widest), h('div', 'ov-lg', resultWords(r))), h('td', 'n hs nw', ago(r.at))),
    () => { pickRobot(r.pack); location.href = 'simulation.html'; }, `Open ${r.label} in Simulation`)));
  return h('section', '', h('div', 'ov-h', h('h2', '', 'Recent simulations'), link('', 'data.html', 'View all')),
    h('table', '', h('thead', '', h('tr', '', h('th', '', 'Name'), h('th', 'hs', 'Robot'), h('th', 'n hs', 'Worlds'), h('th', '', 'Outcome'), h('th', 'n hs', 'When'))), body));
}

function robotsTable(list: Campaign[]) {
  const packs = new Map<string, Campaign>();
  for (const c of byNewest(list)) if (!packs.has(c.pack)) packs.set(c.pack, c);
  const body = h('tbody', '', ...[...packs.values()].map(r => rowGo(h('tr', '',
    h('td', '', h('b', '', r.robot)), h('td', 'hs', r.label), h('td', 'n', r.total ? `${Math.round(r.passed * 100 / r.total)}%` : '0%'),
    h('td', 'n', r.failed ? `${r.failed} failed` : 'None failed')),
    () => { pickRobot(r.pack); location.href = 'simulation.html'; }, `Open ${r.robot} in Simulation`)));
  return h('section', '', h('div', 'ov-h', h('h2', '', 'Robots'), link('', 'simulation.html', 'View all')),
    h('table', '', h('thead', '', h('tr', '', h('th', '', 'Name'), h('th', 'hs', 'Last run'), h('th', 'n', 'Pass share'), h('th', 'n', 'Status'))), body));
}

function failuresList(list: Campaign[], b: Board) {
  const kinds = failKinds(list).slice(0, 3);
  const box = h('section', '', h('div', 'ov-h', h('h2', '', 'Failures needing attention'), link('', 'failures.html', 'View all')));
  if (!kinds.length) { box.append(h('div', 'ov-none', 'No open failures.')); return box; }
  for (const k of kinds) {
    const ref = postRef(b.fixable, k.run.pack, k.kind);
    box.append(rowGo(h('div', 'ov-f', h('em', '', String(k.count)), h('div', '', h('b', '', k.name), h('small', '', k.run.robot)), ref ? postBounty(ref) : askAi(k.run.pack)),
      () => { location.href = `data.html?c=${encodeURIComponent(k.run.id)}&q=${encodeURIComponent(k.name)}`; }, `Open ${k.name} in ${k.run.label}`));
  }
  return box;
}

function bountiesBox(b: Board) {
  const box = h('section', '', h('div', 'ov-h', h('h2', '', 'Bounties'), link('', 'bounties.html', 'View all')));
  if (!b.bounties) { box.append(h('div', 'ov-none', 'The board server does not answer.')); return box; }
  const c = bountyCounts(b);
  const n = (word: string, v: number) => h('div', '', h('span', '', word), h('b', '', String(v)));
  box.append(h('div', 'ov-b3', n('Open', c.open), n('In checking', c.checking), n('Paid', c.paid)),
    h('p', 'ov-note', `${c.units.toLocaleString('en')} local test units paid. Local ledger. Not on chain.`));
  return box;
}

function filled(list: Campaign[], b: Board) {
  const open = openRuns(list).reduce((n, c) => n + c.failed, 0);
  const total = sum(list, 'total');
  const kinds = new Set(failKinds(list).map(k => k.name)).size;
  const openNote = open ? `${kinds} ${kinds === 1 ? 'kind' : 'kinds'}` : '';
  const stats = h('div', 'ov-stats',
    stat('Worlds run', total.toLocaleString('en'), `${list.length} ${list.length === 1 ? 'simulation' : 'simulations'}`, 'data.html'),
    stat('Passed', sum(list, 'passed').toLocaleString('en'), share(sum(list, 'passed'), total), 'data.html'),
    stat('Failed', sum(list, 'failed').toLocaleString('en'), share(sum(list, 'failed'), total), 'failures.html'),
    stat('Safe holds', sum(list, 'holds').toLocaleString('en'), share(sum(list, 'holds'), total), 'data.html'),
    stat('Open failures', open.toLocaleString('en'), openNote, 'failures.html'),
    b.bounties ? stat('Open bounties', String(bountyCounts(b).open), 'Local ledger', 'bounties.html') : stat('Open bounties', 'No reply', 'Board is off', 'bounties.html'),
    budgetStat(b));
  stats.title = `Open failures: ${OPEN_SCOPE}`;
  page.replaceChildren(stats, h('div', 'ov-cols', h('div', '', runsTable(list), robotsTable(list)), h('div', '', failuresList(list, b), bountiesBox(b))));
}

const SAMPLES = [
  { pack: 'window', name: 'Window cleaning robot', line: 'Sample. Suction climber on tower glass.', img: '/site/frames/tower-wind.jpg' },
  { pack: 'inspection', name: 'Inspection robot', line: 'Sample. ANYmal C on a plant route.', img: '/site/frames/plant-walk.jpg' },
];

function first(b: Board) {
  actions.replaceChildren(newSim(true));
  const zero = (word: string, note = '') => stat(word, '0', note, null);
  const units = b.budget?.funded ? (b.budget.left ?? 0).toLocaleString('en') : '0';
  page.replaceChildren(
    h('div', 'ov-first',
      h('div', '', h('h2', '', 'Add your first robot'), h('p', '', 'Pick your robot once. AI builds the worlds, and simulated runs show you where it fails.'), link('ov-pill big', 'simulation.html', icon('plus', 16), 'Add your first robot')),
      h('div', 'ov-smp', h('p', '', 'Or look around with a sample robot'), ...SAMPLES.map(s => h('div', 'ov-sr', Object.assign(h('img'), { src: s.img, alt: '' }), h('div', '', h('b', '', s.name), h('span', '', s.line)), robotLink('ov-btn', s.pack, 'lab.html', 'Use sample'))))),
    h('div', 'ov-zero', h('div', 'ov-stats', zero('Worlds run', 'No runs yet'), zero('Passed'), zero('Failed'), zero('Safe holds'), zero('Open failures'), zero('Open bounties'), stat('Budget', units, 'Local test units', null))));
}

void who.then(async w => {
  if (w.kind === 'none' || w.kind === 'engineer') return; // The shell is on its way elsewhere.
  actions.replaceChildren(newSim(false));
  const [list, b] = await Promise.all([campaigns().catch(() => null), board()]);
  if (!list) { page.replaceChildren(serverDown('The run list')); return; }
  if (list.length) filled(list, b); else first(b);
});
