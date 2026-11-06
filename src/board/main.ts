// The bounty board in the site's style: side bar, bounty list, one bounty. Real data only. All text goes in through textContent.
import { mountShell, SIM_NOTE } from '../site/shell.ts';
import './board.css';
import { api, ApiError, type Bounty, type Fix, type Sub, type Budget, type Fixable, type FixResult } from './api.ts';
import { icon, type IconName } from './icons.ts';

const LEDGER = 'Local ledger. Not on chain.';
const WORLD_ID = 'World ID is not connected';
const POLL_MS = 1500;

type Kid = Node | string;
function h(tag: string, cls = '', ...kids: Kid[]): HTMLElement {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  n.append(...kids);
  return n;
}
const words = (v: string) => v.replace(/_/g, ' ');
const cap1 = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);
const short = (v: string) => `${v.slice(0, 8)}…${v.slice(-4)}`;
function button(cls: string, text: string, ic: IconName | null, on: () => void) {
  const b = h('button', `btn ${cls}`, ...(ic ? [icon(ic)] : []), text) as HTMLButtonElement;
  b.addEventListener('click', on);
  return b;
}
const tag = (cls: string, ic: IconName, text: string, spin = false) => h('span', `tag ${cls}`, icon(ic, spin ? 'spin' : ''), text);

type Filter = 'all' | 'open' | 'checking' | 'paid';
interface State { bounties: Bounty[]; picked: number | null; fixes: Fix[]; subs: Sub[]; focus: number | null; budget: Budget; error: string | null; offline: boolean; filter: Filter; robot: number; q: string; dir: number }
const S: State = { bounties: [], picked: null, fixes: [], subs: [], focus: null, budget: { funded: false }, error: null, offline: false, filter: 'all', robot: 0, q: '', dir: -1 };
const ROBOTS = ['Any robot', 'Window', 'Inspection'];

const bucket = (b: Bounty): Filter => b.status === 'claimed' ? 'paid' : b.status !== 'open' || (b.checking ?? 0) > 0 ? 'checking' : 'open';
function statusTag(b: Bounty) {
  if (b.status === 'claimed') return tag('ok', 'ok', 'Paid');
  if (b.status === 'pending') return tag('hold', 'clock', 'Dispute window');
  if (b.status === 'finalized') return tag('hold', 'ok', 'Finalized');
  if ((b.checking ?? 0) > 0) return tag('live', 'loader', 'Checking', true);
  if (b.status === 'cap_reached') return tag('quiet', 'slash', 'Cap used');
  return tag('quiet', 'circle', 'Open');
}
const picked = () => S.bounties.find(b => b.id === S.picked) ?? null;
const hiddenTotal = (b: Bounty) => { const c = b.hidden_counts; return c ? c.held_back + c.passed_before + c.other_failed : 0; };

const seg = h('div', 'seg');
seg.setAttribute('role', 'group');
seg.setAttribute('aria-label', 'Status');
const robotBtn = h('button', 'pick');
const search = h('input') as HTMLInputElement;
search.placeholder = 'Search';
search.setAttribute('aria-label', 'Search bounties');
const tbody = h('tbody');
const ledgerBox = h('div', 'ledger');
const detail = h('section', 'detail');
const payArrow = h('span', 'ar');

function shell() {
  const postBtn = button('sec', 'Post a bounty', 'plus', () => openPost(null));
  const table = h('table');
  table.id = 'bt';
  const head = h('tr', '', h('th', '', 'Bounty'), (() => { const t = h('th', '', 'Worlds'); t.style.width = '124px'; return t; })());
  const payHead = h('th', 'sort on num', 'Pay', payArrow);
  payHead.style.width = '76px';
  payHead.addEventListener('click', () => { S.dir = -S.dir; drawList(); });
  const statusHead = h('th', '', 'Status');
  statusHead.style.width = '156px';
  head.append(payHead, statusHead);
  table.append(h('thead', '', head), tbody);
  robotBtn.addEventListener('click', () => { S.robot = (S.robot + 1) % 3; drawList(); });
  search.addEventListener('input', () => { S.q = search.value.toLowerCase(); drawList(); });
  const list = h('section', 'list',
    h('div', 'filters', seg, robotBtn, h('label', 'field', icon('search'), search)),
    h('div', 'tablewrap', table),
    ledgerBox);
  const site = mountShell({ page: 'bounties', title: 'Bounties', status: SIM_NOTE, statusRight: [`${WORLD_ID}, so the cap of 5 counts names, not people.`, LEDGER] });
  // The side bar and this line read the same login state, so they cannot disagree.
  const idLine = h('span', 'warnline', icon('warn', 'i12'), WORLD_ID);
  void site.who.then(who => {
    if (who.kind !== 'verified') return;
    idLine.replaceChildren(icon('warn', 'i12'), 'World ID signs you in. The board does not check it yet');
    site.setStatus(SIM_NOTE, ['The board does not check World ID yet, so the cap of 5 counts names, not people.', LEDGER]);
  });
  site.actions.append(idLine, postBtn);
  site.main.append(h('div', 'bty', list, detail));
  return site;
}

function drawList() {
  const count = (f: Filter) => S.bounties.filter(b => f === 'all' || bucket(b) === f).length;
  seg.replaceChildren(...([['all', 'All'], ['open', 'Open'], ['checking', 'Checking'], ['paid', 'Paid']] as [Filter, string][]).map(([k, label]) => {
    const b = h('button', '', label, h('i', '', String(count(k))));
    b.setAttribute('aria-pressed', String(S.filter === k));
    b.addEventListener('click', () => { S.filter = k; drawList(); });
    return b;
  }));
  robotBtn.replaceChildren(ROBOTS[S.robot], icon('down', 'i12'));
  payArrow.replaceChildren(icon(S.dir < 0 ? 'down' : 'up', 'i12'));
  const rows = S.bounties
    .filter(b => (S.filter === 'all' || bucket(b) === S.filter) && (!S.robot || (b.robot ?? '').startsWith(ROBOTS[S.robot])) && (!S.q || `${b.title} ${b.company} ${b.group ?? ''} ${b.robot}`.toLowerCase().includes(S.q)))
    .sort((a, c) => S.dir * (a.per_failure - c.per_failure) || c.id - a.id);
  tbody.replaceChildren();
  if (!rows.length) {
    const td = h('td', 'wrapn');
    td.setAttribute('colspan', '4');
    const none = !S.bounties.length;
    td.append(h('div', 'empty', h('b', '', S.offline ? 'The board server is not running' : none ? 'No bounties yet' : 'No bounty matches this filter'),
      h('span', '', S.offline ? 'Start policy/bounty/board_server.py on port 5298.' : none ? 'A bounty shows here once a company or its agent posts a real failure.' : 'Clear the search or pick another status.')));
    tbody.append(h('tr', '', td));
    return;
  }
  for (const b of rows) {
    const isFix = b.kind === 'fix_failure';
    const pub = isFix ? b.public_worlds!.length : 0;
    const hid = hiddenTotal(b);
    const mini = h('div', 'cells mini');
    const scale = isFix ? Math.min(16, pub + hid) : 0;
    const redCells = isFix ? Math.max(1, Math.round(scale * pub / (pub + hid))) : 0;
    for (let i = 0; i < scale; i++) mini.append(h('span', i < redCells ? 'c-pub' : 'c-hide'));
    const sub = h('span', 'sub', isFix ? `${pub} public, ${hid} hidden` : 'Find a failure');
    sub.style.marginTop = isFix ? '6px' : '0';
    const row = h('tr', 'row', h('td', '', h('span', 'title', b.title), h('span', 'sub', `${(b.robot ?? '').split(' ')[0]}, ${isFix ? words(b.group ?? '') : 'new failure'}, ${b.company}`)), h('td', '', ...(isFix ? [mini] : []), sub), h('td', 'pay', String(b.per_failure)), h('td', '', statusTag(b)));
    row.tabIndex = 0;
    row.setAttribute('aria-selected', String(b.id === S.picked));
    const go = () => { S.picked = b.id; S.focus = null; S.error = null; refreshPicked().then(render); };
    row.addEventListener('click', go);
    row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    tbody.append(row);
  }
}

function drawLedger() {
  const sum = (f: (b: Bounty) => number) => S.bounties.reduce((a, b) => a + f(b), 0);
  const num = (v: number, label: string) => h('div', '', h('b', '', String(v)), h('span', '', label));
  ledgerBox.replaceChildren(h('div', 'lh', h('h2', '', 'Ledger'), h('span', 'warnline', icon('warn', 'i12'), LEDGER)),
    h('div', 'lnums', num(sum(b => b.cap), 'Posted'), num(sum(b => b.balance.pending + b.balance.finalized), 'Held while checking'), num(sum(b => b.balance.claimed), 'Paid'), num(sum(b => b.balance.available), 'Left')),
    h('p', '', 'Test units, not money. Code alone moves pay, and only after the hidden worlds pass.'));
  const b = S.budget;
  if (b.funded) {
    const stop = button('sec', b.stopped ? 'Agent stopped' : 'Stop the agent', 'stop', async () => { try { S.budget = await api.stop(); S.error = null; } catch (e) { S.error = (e as Error).message; } render(); });
    stop.disabled = !!b.stopped;
    ledgerBox.append(h('div', 'budget', h('span', '', `Agent budget: ${b.left} of ${b.cap} left, ${b.held} held, ${b.spent} spent, ${b.per_bounty_max} most per bounty.`), h('span', 'sp'), stop));
  }
}

const sect = (title: string, right: Kid = '') => h('div', 'dsect', h('h2', '', title), typeof right === 'string' ? h('span', 't3 small', right) : right);
const fact = (k: string, v: Kid) => h('div', '', h('span', '', k), h('b', '', v));
const code = (v: string) => h('code', '', v);

function drawDetail() {
  const b = picked();
  if (!b) {
    detail.replaceChildren(h('div', 'center', h('div', 'empty', h('b', '', 'Pick a bounty'), h('span', '', 'Its failing worlds, its hidden world count and each answer show here. Your source runs only in the sandbox.'))));
    return;
  }
  const inner = h('div', 'in');
  (b.kind === 'fix_failure' ? fixDetail : findDetail)(b, inner);
  const top = detail.scrollTop;
  detail.replaceChildren(inner);
  detail.scrollTop = top;
}

function fixDetail(b: Bounty, inner: HTMLElement) {
  const worlds = b.public_worlds!;
  const c = b.hidden_counts!;
  const total = hiddenTotal(b);
  inner.append(h('div', 'dh', h('div', 'top', h('h1', '', b.title), statusTag(b)), h('p', 'req', `${b.company}. ${cap1(words(b.group!))} on the ${b.robot.toLowerCase()}: ${worlds[0].reason}`)),
    h('div', 'facts', fact('Pay', `${b.pay} test units`), fact('Failure', cap1(words(b.group!))), fact('Base file', code(b.controller!.file)), fact('Dispute window', `${b.dispute_window_s} s`)),
    sect('Public failing worlds', String(worlds.length)));
  const table = h('table');
  table.append(h('thead', '', h('tr', '', h('th', '', 'World'), h('th', 'num', 'Fails at'), h('th', '', 'Judge'), h('th', '', 'Seed'))));
  const body = h('tbody');
  for (const w of worlds) {
    const first = w.events?.find(e => e.name === w.verdict) ?? w.events?.[0];
    const row = h('tr', '', h('td', '', words(w.name)), h('td', 'num', first ? `${first.t.toFixed(1)} s` : ''), h('td', 't2', cap1(words(w.verdict))), h('td', 't2', String(w.seed)));
    row.title = w.reason;
    body.append(row);
  }
  table.append(body);
  inner.append(table);
  const cells = h('div', 'cells');
  const best = latestProof();
  const held = best?.sets?.held_back;
  const fixedShown = best ? (held ? held.better : 0) : 0;
  for (let i = 0; i < c.held_back; i++) cells.append(h('span', i < fixedShown ? 'c-pass' : 'c-hide'));
  const counts = `${c.held_back} held back. ${c.passed_before} passed before and must keep passing. ${c.other_failed} other failures must not get worse.`;
  inner.append(sect('Hidden worlds', h('span', 'tag quiet small', icon('eyeoff', 'i12'), `${total} stay hidden`)), h('div', 'hidden-w', cells, h('p', '', `Nobody sees these worlds. The code runs your fix on them and shows only a count. ${counts}`)));
  if (S.error) inner.append(h('div', 'err', S.error));
  const send = button(S.fixes.length ? 'sec' : 'pri', 'Submit a fix', null, () => openSubmit(b));
  send.disabled = b.status !== 'open';
  const f = S.fixes.find(x => x.n === S.focus) ?? S.fixes[S.fixes.length - 1];
  const head = sect('Submission', h('span', 'row-r', send));
  head.style.height = '40px';
  inner.append(head, flow(b, f));
  if (S.fixes.length) {
    const subs = h('table', 'subs');
    const rows = h('tbody');
    for (const x of S.fixes) {
      const row = h('tr', 'click', h('td', '', x.tester), h('td', '', code(x.source_sha256.slice(0, 10))), h('td', '', fixTag(x)), h('td', 'num t2', x.payout?.amount ? `${x.payout.status}, ${x.payout.amount}` : 'Nothing held'));
      row.setAttribute('aria-selected', String(x.n === f?.n));
      row.addEventListener('click', () => { S.focus = x.n; render(); });
      rows.append(row);
    }
    subs.append(rows);
    inner.append(subs);
  } else inner.append(h('div', 'words small', 'No fix yet. A fix runs on the public worlds, then on the hidden worlds.'));
  if (f) inner.append(...fixResult(b, f));
  inner.append(sect('Frozen judge and sim'));
  for (const [k, v] of Object.entries(b.frozen!).filter(([name]) => /judge|sim/.test(name))) inner.append(h('div', 'kv', h('span', '', code(k.split('/').pop()!)), h('span', '', code(short(v)))));
  inner.append(h('div', 'words small', b.scope!));
  if (b.chain_mirror) {
    inner.append(sect(b.chain_mirror.label, `Chain ${b.chain_mirror.chain_id}`));
    for (const [k, v] of Object.entries(b.chain_mirror.txs).filter(([name]) => ['propose', 'finalize', 'claim'].includes(name))) inner.append(h('div', 'kv', h('span', '', cap1(k)), h('span', '', code(short(v)))));
  }
  inner.append(...notChecked(b));
}

function latestProof(): FixResult | null {
  const done = S.fixes.filter(f => f.result?.sets);
  const f = S.fixes.find(x => x.n === S.focus && x.result?.sets) ?? done[done.length - 1];
  return f?.result ?? null;
}

function flow(b: Bounty, f: Fix | undefined) {
  const r = f?.result;
  const s = r?.sets;
  const reached = !f ? -1 : !r ? 0 : !s ? 0 : r.target.every(t => t.passed || t.safe_hold) ? (Object.values(s).every(v => v.worse === 0) && r.code !== 'overfit' ? (f.payout?.status === 'Claimed' ? 4 : f.payout ? 3 : 2) : 1) : 0;
  const fixed = r ? r.target.filter(t => t.passed || t.safe_hold).length : 0;
  const steps: [string, string][] = [
    ['Patch received', f ? f.source_sha256.slice(0, 12) : 'No patch yet'],
    ['Public worlds', s ? `${fixed} of ${r!.target.length} pass` : f && !r ? 'Running' : 'Waiting'],
    ['Hidden worlds', s ? `${Object.entries(s).filter(([k]) => k !== 'target').reduce((a, [, v]) => a + v.worse, 0)} worse of ${hiddenTotal(b)}` : 'Waiting'],
    ['Ledger pays', f?.payout?.status === 'Claimed' ? `${f.payout.amount} test units paid` : f?.payout?.amount ? `${f.payout.status}, ${f.payout.amount} held` : 'Only on a full pass'],
  ];
  return h('div', 'flowline', ...steps.map(([k, v], i) => h('div', i < reached || reached === 4 ? 'd' : i === reached ? 'n' : '', h('b', '', k), h('small', '', v))));
}

function fixTag(f: Fix) {
  if (!f.result) return f.state === 'interrupted' ? tag('quiet', 'slash', 'Interrupted') : f.state === 'running' ? tag('live', 'loader', 'Checking', true) : tag('quiet', 'clock', 'Waiting');
  const c = f.result.code;
  if (c === 'accepted' || c === 'accepted_by_company') return tag('ok', 'ok', 'Accepted');
  if (c === 'awaiting_company') return tag('hold', 'warn', 'Awaiting company');
  return tag('bad', 'bad', ({ refused_source: 'Refused', judge_changed: 'Judge changed', worse_on_hidden: 'Worse on hidden', overfit: 'Overfit', target_not_fixed: 'Not fixed', limit_hit: 'Limit hit', replay_mismatch: 'Replay differs', declined_by_company: 'Declined' } as Record<string, string>)[c] ?? cap1(words(c)));
}

const HEADLINE: Record<string, string> = { accepted: 'The fix holds on the hidden worlds', accepted_by_company: 'The fix holds, and the company approved it', awaiting_company: 'It passes, and a safety line needs the company', refused_source: 'The code rules refused this source', judge_changed: 'The judge changed, so no run counts', worse_on_hidden: 'It made hidden worlds worse', overfit: 'It does not carry over to hidden worlds', target_not_fixed: 'The failing worlds still fail', limit_hit: 'The sandbox stopped a run', replay_mismatch: 'A run did not replay to its result', declined_by_company: 'The company declined it', no_change: 'The source has no change', gate_crashed: 'The gate stopped with an error' };

function line(state: 'ok' | 'bad' | 'skip' | 'warn', label: string, value: string) {
  const mark = h('span', state, icon(state === 'ok' ? 'check' : state === 'bad' ? 'x' : state === 'warn' ? 'warn' : 'slash'));
  return h('div', 'kv', h('span', '', mark, label), h('span', '', value));
}

const act = (run: () => Promise<unknown>) => async () => {
  S.error = null;
  try { await run(); } catch (e) { S.error = (e as Error).message; }
  await refresh();
};

function fixResult(b: Bounty, f: Fix): HTMLElement[] {
  const out: HTMLElement[] = [];
  const r = f.result;
  if (!r) {
    out.push(sect(f.state === 'running' ? `Fix ${f.n} is running in the sandbox` : f.state === 'interrupted' ? `The board restarted during fix ${f.n}` : `Fix ${f.n} waits for the gate`));
    return out;
  }
  out.push(sect(HEADLINE[r.code] ?? cap1(words(r.code)), f.wall_s !== undefined ? `${f.wall_s} s` : ''), h('div', 'words', r.words));
  const s = r.sets;
  if (s) {
    const fixed = r.target.filter(t => t.passed || t.safe_hold).length;
    const row = (label: string, v: { n: number; better: number; worse: number }) => line(v.worse ? 'bad' : 'ok', label, `${v.better} better, ${v.worse} worse, of ${v.n}`);
    out.push(line(fixed === r.target.length ? 'ok' : 'bad', 'Public failing worlds fixed', `${fixed} of ${r.target.length}`), row('Held back', s.held_back), row('Passed before', s.passed_before), row('Other failures', s.other_failed));
    if (r.held_back_with_this_failure) out.push(line((r.held_back_fixed ?? 0) * 2 >= r.held_back_with_this_failure ? 'ok' : 'bad', 'Held back with this failure', `${r.held_back_fixed} of ${r.held_back_with_this_failure} fixed`));
    const mism = Object.values(s).reduce((a, v) => a + v.replay_mismatch, 0);
    if (b.replay_rejudge) out.push(line(mism ? 'bad' : 'ok', 'Replay re-judge', mism ? `${mism} differ` : 'All match'));
  }
  if (r.flags?.length) {
    out.push(sect('Lines that touch a safety check', String(r.flags.length)));
    for (const fl of r.flags) out.push(h('div', 'flag', h('span', 't3 small', `Line ${fl.line}`), code(fl.text)));
    if (f.state === 'awaiting_company') {
      out.push(h('div', 'acts', button('pri', 'Approve as the company', 'check', act(() => api.step(b.id, f.n, 'approve'))), button('sec', 'Decline', 'x', act(() => api.step(b.id, f.n, 'decline'))), h('span', 'sp'), h('span', 't3 small', 'No account exists yet.')));
      (out[out.length - 1]).style.paddingTop = '8px';
    }
  }
  out.push(...payout(b, f));
  return out;
}

function payout(b: Bounty, f: Fix): HTMLElement[] {
  const p = f.payout;
  if (!p) return [];
  const out = [sect('Payout', h('span', 'warnline', icon('warn', 'i12'), LEDGER))];
  if (p.status === 'LedgerRefused') { out.push(h('div', 'err', `The ledger refused this: ${p.error}.`)); return out; }
  const acts = h('div', 'acts');
  if (p.status === 'Pending') {
    const skew = b.now - Date.now() / 1000;
    const left = Math.max(0, Math.ceil((p.dispute_ends_at ?? 0) - (Date.now() / 1000 + skew)));
    const fin = button('sec', 'Finalize', 'check', act(() => api.step(b.id, f.n, 'finalize')));
    fin.disabled = left > 0;
    const rej = button('sec', 'Reject in the window', 'x', act(() => api.step(b.id, f.n, 'reject')));
    rej.disabled = left <= 0;
    acts.append(fin, rej, h('span', 'sp'), h('span', 't2 small', left ? `${left} s dispute window left` : 'The dispute window closed'));
  } else if (p.status === 'Finalized') {
    const who = h('input') as HTMLInputElement;
    who.placeholder = 'Name to claim with';
    who.setAttribute('aria-label', 'Name to claim with');
    acts.append(who, button('pri', 'Claim', 'check', act(() => api.step(b.id, f.n, 'claim', who.value))), h('span', 'sp'), h('span', 't3 small', 'The tester id comes from the name. It is not a wallet.'));
  } else acts.append(h('span', 't2', p.status === 'Claimed' ? `${f.tester} claimed ${p.amount} test units.` : `${p.status}.`));
  out.push(acts);
  return out;
}

function notChecked(b: Bounty) {
  const rows = [['World ID of the submitter', 'Not connected'], ['Collusion between submitter and company', 'No check exists'], ['Whether this works on a real robot', 'Simulated only'], ['Sandbox isolation', 'Shares the kernel, not a VM']];
  if (b.replay_rejudge === false) rows.push(['Replay re-judge', 'None for this robot']);
  const box = [sect('Not checked', String(rows.length))];
  for (const [k, v] of rows) box.push(h('div', 'kv', h('span', '', h('span', 'skip', icon('slash')), k), h('span', 't3', v)));
  const pad = h('div'); pad.style.height = '16px';
  box.push(pad);
  return box;
}

function findDetail(b: Bounty, inner: HTMLElement) {
  const named = b.narrowed ?? [];
  inner.append(h('div', 'dh', h('div', 'top', h('h1', '', b.title), statusTag(b)), h('p', 'req', `${b.company} wants new failures of the ${b.robot.toLowerCase()}.`)),
    h('div', 'facts', fact('Cap', `${b.cap} test units`), fact('Per failure', String(b.per_failure)), fact('Left', String(b.available)), fact('Dispute window', `${b.dispute_window_s} s`)), sect('Allowed worlds', `${Object.keys(b.limits!).length - named.length} more keep the schema range`));
  const table = h('table');
  const body = h('tbody');
  for (const k of named) body.append(h('tr', '', h('td', '', words(k)), h('td', 't2', `${b.limits![k][0]} to ${b.limits![k][1]}`)));
  table.append(body);
  inner.append(table, h('div', 'words small', 'The company chose these limits. A world inside them is not shown to be physically possible.'));
  if (S.error) inner.append(h('div', 'err', S.error));
  inner.append(sect('Submissions', button(S.subs.length ? 'sec' : 'pri', 'Submit a world', null, () => openSubmit(b))));
  if (!S.subs.length) inner.append(h('div', 'words small', 'No world yet.'));
  else {
    const subs = h('table', 'subs');
    const rows = h('tbody');
    for (const x of S.subs) rows.append(h('tr', '', h('td', '', x.tester), h('td', 't2', String(x.seed)), h('td', '', x.result ? (x.result.accepted ? tag('ok', 'ok', 'Accepted') : tag('bad', 'bad', cap1(words(x.result.code)))) : tag('live', 'loader', cap1(x.state), x.state === 'running')), h('td', 'num t2', x.payout?.amount ? `${x.payout.status}, ${x.payout.amount}` : 'Nothing held')));
    subs.append(rows);
    inner.append(subs);
  }
  inner.append(...notChecked(b));
}

function render() {
  drawList();
  drawLedger();
  drawDetail();
}

async function refreshPicked() {
  const b = picked();
  if (!b) { S.fixes = []; S.subs = []; return; }
  if (b.kind === 'fix_failure') { S.fixes = (await api.fixes(b.id)).fixes; S.subs = []; }
  else { S.subs = (await api.subs(b.id)).submissions; S.fixes = []; }
}

async function refresh() {
  try {
    const [list, budget] = await Promise.all([api.bounties(), api.budget()]);
    S.bounties = list.bounties;
    S.budget = budget;
    S.offline = false;
    if (S.picked === null && S.bounties.length) S.picked = S.bounties[0].id;
    await refreshPicked();
  } catch (e) {
    S.offline = !(e instanceof ApiError);
    if (S.offline) S.bounties = [];
  }
  const a = document.activeElement;
  if (!(a instanceof HTMLInputElement && detail.contains(a))) render();
}

function dialog(title: string, wide: boolean, body: HTMLElement, foot: HTMLElement[]) {
  const close = () => overlay.remove();
  const box = h('div', `dialog${wide ? ' wide' : ''}`, h('div', 'dhd', h('h2', '', title), h('span', 'sp'), h('span', 'warnline', icon('warn', 'i12'), LEDGER)), body, h('div', 'foot', ...foot));
  const overlay = h('div', 'overlay', box);
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function esc(e) { if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); } });
  document.body.append(overlay);
  return close;
}
const field = (label: string, input: HTMLElement, cls = '') => h('div', cls, h('label', '', label), input);

function openSubmit(b: Bounty) {
  const isFix = b.kind === 'fix_failure';
  const who = h('input') as HTMLInputElement;
  who.setAttribute('aria-label', 'Tester name');
  who.placeholder = 'Your name';
  const seed = h('input') as HTMLInputElement;
  seed.value = '1';
  const area = h('textarea') as HTMLTextAreaElement;
  area.spellcheck = false;
  area.setAttribute('aria-label', isFix ? 'Controller source' : 'World file');
  const error = h('span', 'bad');
  if (isFix) api.source(b.id).then(s => { area.value = s.source; area.dataset.ready = '1'; }).catch(e => { error.textContent = (e as Error).message; });
  const send = button('pri', 'Run check, then simulation', null, async () => {
    error.textContent = '';
    try {
      const r = isFix ? await api.submitFix(b.id, who.value, area.value) : await api.submitWorld(b.id, who.value, area.value, Number(seed.value));
      S.focus = r.n;
      close();
      await refresh();
    } catch (e) { error.textContent = (e as Error).message; }
  });
  const close = dialog(isFix ? 'Submit a fix' : 'Submit a world', true,
    h('div', 'body', field('Tester name, 5 submissions per name', who), isFix ? field('Base file', (() => { const i = h('input') as HTMLInputElement; i.value = b.controller!.file; i.disabled = true; return i; })()) : field('Seed', seed), h('div', 'full', area), h('div', 'full note2', isFix ? `${b.scope} Up to 60 KB. It runs in the sandbox with no network. One gate runs at a time.` : 'Up to 16 KB. One gate runs at a time.')),
    [error, h('span', 'sp'), button('sec', 'Cancel', null, () => close()), send]);
}

function openPost(ref: string | null) {
  const select = h('select') as HTMLSelectElement;
  select.setAttribute('aria-label', 'Failure');
  const titleIn = h('input') as HTMLInputElement;
  const company = h('input') as HTMLInputElement;
  const pay = h('input') as HTMLInputElement;
  const windowS = h('input') as HTMLInputElement;
  pay.type = windowS.type = 'number';
  company.value = 'Demo company (test)';
  pay.value = '40';
  windowS.value = '60';
  const error = h('span', 'bad');
  let rows: Fixable[] = [];
  const send = button('pri', 'Post the bounty', null, async () => {
    const pick = rows.find(r => r.ref === select.value);
    if (!pick) { error.textContent = 'Pick a failure first.'; return; }
    try {
      const made = await api.post({ session: pick.session, campaign: pick.cid, group: pick.group, title: titleIn.value, company: company.value, pay: Number(pay.value), window: Number(windowS.value) });
      S.picked = made.id;
      close();
      await refresh();
    } catch (e) { error.textContent = (e as Error).message; }
  });
  const close = dialog('Post a bounty', false,
    h('div', 'body', field('Failure from a real campaign', select, 'full'), field('Title', titleIn, 'full'), field('Company', company, 'full'), field('Pay, test units', pay), field('Dispute window, seconds', windowS), h('div', 'full note2', 'One fix wins the pay. Held-back worlds stay hidden. Test units are not money.')),
    [error, h('span', 'sp'), button('sec', 'Cancel', null, () => close()), send]);
  const fill = (r: Fixable) => { titleIn.value = titleIn.value || `Fix ${words(r.group)}`; };
  api.fixable().then(reply => {
    rows = reply.fixable.filter(r => !r.posted);
    if (ref && !rows.some(r => r.ref === ref)) error.textContent = 'This failure cannot be posted. It may be posted already.';
    select.replaceChildren(...rows.map(r => { const o = h('option', '', `${r.robot}, ${words(r.group)}: ${r.failed} of ${r.worlds} worlds, ${r.session.slice(0, 6)}/${r.cid}`) as HTMLOptionElement; o.value = r.ref; return o; }));
    if (ref && rows.some(r => r.ref === ref)) select.value = ref;
    const now = rows.find(r => r.ref === select.value);
    if (now) fill(now);
    if (!rows.length && !ref) error.textContent = 'No campaign has a failure to post yet.';
  }).catch(e => { error.textContent = (e as Error).message; });
  select.addEventListener('change', () => { titleIn.value = ''; const now = rows.find(r => r.ref === select.value); if (now) fill(now); });
}

const site = shell();
render();
refresh();
setInterval(refresh, POLL_MS);
const postRef = new URLSearchParams(location.search).get('post');
if (postRef) {
  void site.who.then(who => {
    if (who.kind === 'none') return; // The shell is on its way to login, and login brings the visitor back with this address.
    history.replaceState(null, '', location.pathname);  // A reload must not open the dialog again.
    openPost(postRef);
  });
}
