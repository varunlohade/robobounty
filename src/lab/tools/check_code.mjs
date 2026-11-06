// The code tab end to end on the real server and real physics, with stored scenario replies.
// node src/lab/tools/check_code.mjs [--out DIR] [--group VERDICT] [--fix-patch FILE]. Needs vite on port 5199. It starts its own server on a free port and its own Chrome profile.
// One real AI call runs for the fix. With --fix-patch that file stands in for the AI's edit, and the chat says so. Results are simulated.
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const FIX_PATCH = arg('fix-patch', null);
const GROUP = arg('group', null);
const FROZEN = ['policy/highrise5/controller5.py', 'policy/highrise5/judge5.py', 'policy/highrise5/world5.py', 'policy/highrise5/sim5.py', 'policy/packs/inspection/controller.py'];
const hashes = () => Object.fromEntries(FROZEN.map(f => [f, createHash('sha256').update(readFileSync(join(ROOT, f))).digest('hex')]));
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

const before = hashes();
const port = await freePort();
const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port), '--recorded', join(ROOT, 'policy/server/fixtures'), ...(FIX_PATCH ? ['--fix-patch', resolve(FIX_PATCH)] : ['--live-fix'])], { stdio: ['ignore', 'ignore', 'inherit'] });
for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers: { Origin: 'http://localhost:5199' } }); break; } catch { await wait(200); } }

// The inspection robot, through the server's routes. RouteFollower only, in the sandbox, with Warp's cache cloned for each run.
async function inspectionPart() {
  const p2 = await freePort();
  const s2 = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(p2), '--recorded', join(ROOT, 'policy/server/fixtures'), '--scenario-limit', '4'], { stdio: ['ignore', 'ignore', 'inherit'] });
  const api = async (path, body) => {
    const res = await fetch(`http://127.0.0.1:${p2}${path}`, { method: body ? 'POST' : 'GET', headers: { Origin: 'http://localhost:5199', 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    return { status: res.status, body: await res.json() };
  };
  try {
    for (let i = 0; i < 150; i++) { try { await api('/api/health'); break; } catch { await wait(200); } }
    const sid = (await api('/api/sessions', { pack: 'inspection' })).body.id;
    const idle = async what => { for (let i = 0; i < 600; i++) { const st = (await api(`/api/sessions/${sid}/state`)).body; if (!st.busy) return; await wait(1000); } throw new Error(`timed out: ${what}`); };
    await idle('open');
    await api(`/api/sessions/${sid}/action`, { action: 'list_scenarios' });
    await idle('list');
    await api(`/api/sessions/${sid}/action`, { action: 'run_campaign' });
    await wait(1000);
    await idle('campaign');
    const grid = (await api(`/api/sessions/${sid}/campaigns/c1/grid`)).body;
    const row = grid.rows.find(r => !r.held_back);
    const code = (await api(`/api/sessions/${sid}/code`)).body;
    const refused = await api(`/api/sessions/${sid}/code`, { source: code.source.replace('self.scale = float(action_scale)', 'self.scale = 2.0'), run: 'one', campaign: 'c1', index: row.index });
    check('inspection: an edit of WalkPolicy gets a plain refusal', refused.status === 422 && /WalkPolicy stays fixed/.test(refused.body.reasons.join()), refused.body.reasons?.join(' | '));
    const edited = code.source.replace('SPEED_MPS = 0.8', 'SPEED_MPS = 0.0');
    const started = await api(`/api/sessions/${sid}/code`, { source: edited, run: 'one', campaign: 'c1', index: row.index });
    await wait(1000);
    await idle('inspection edit');
    const detail = (await api(`/api/sessions/${sid}/campaigns/c1/worlds/${row.index}`)).body;
    check('inspection: a RouteFollower edit runs in the sandbox and changes the result', started.status === 202 && detail.verdict !== row.verdict && detail.verdict !== 'controller_crashed' && detail.first?.verdict === row.verdict, `${row.verdict} -> ${detail.verdict}: ${detail.verdict_reason}`);
    const traced = (await api(`/api/sessions/${sid}/campaigns/c1/worlds/${row.index}/trace`)).body;
    check('inspection: the line stays active code, not traced', traced.traced === false && !traced.code?.traced);
  } finally {
    s2.kill();
  }
}

const c = await openChrome();
const shot = name => c.shot(join(OUT, name));
const box = sel => c.js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; })()`);
const clickOn = async sel => { const b = await box(sel); await c.click(b.x, b.y); };
const clickText = async (sel, words) => {
  const b = await c.js(`(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].find(x => x.innerText.includes(${JSON.stringify(words)}) && x.offsetParent); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
  if (!b) throw new Error(`no ${sel} with ${words}`);
  await c.click(b.x, b.y);
};
const row = index => `window.__lab.grid().squares.get(${index}).row`;
const openSquare = async index => {
  const list = await c.js(`document.querySelector('.grid-back').hidden`);
  if (!list) { await clickOn('.grid-back'); await wait(300); }
  await clickOn(`.sq[data-index="${index}"]`);
  await c.until(`[...document.querySelectorAll('.grid-rail button')].some(b => b.innerText === 'Open file')`, 'detail rail', 30);
  await wait(200);
};
const doc = () => c.js(`window.__lab.code().view.state.doc.toString()`);
const replaceAll = text => c.js(`(() => { const v = window.__lab.code().view; v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: ${JSON.stringify(text)} } }); })()`);
const typeAtTop = async text => {
  await c.js(`(() => { const v = window.__lab.code().view; v.focus(); v.dispatch({ selection: { anchor: 0 } }); })()`);
  await c.send('Input.insertText', { text });
};
const bodyText = sel => c.js(`document.querySelector(${JSON.stringify(sel)})?.innerText ?? ''`);

try {
  await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?server=${port}` });
  await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus') && window.__lab`, 'server up', 90);
  await c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = 'Window robot for towers in Dubai. High floor.'; document.querySelector('.chat-send').click(); })()`);
  for (let i = 0; i < 480 && !(await c.js(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 5`)); i++) {
    await c.js(`[...document.querySelectorAll('.chat-option:not(:disabled)')][0]?.click()`);
    await wait(500);
  }
  await c.until(`!document.querySelector('.chat-test').hidden`, 'test button', 30);
  await clickOn('.chat-test');
  await c.until(`document.querySelector('.chat-run')`, 'scenario list', 120);
  await clickOn('.chat-run');
  await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'grid', 60);
  await c.until(`document.querySelector('.grid-page').dataset.running === 'false'`, 'campaign end', 300);
  await wait(500);

  const rows = await c.js(`[...window.__lab.grid().squares.values()].map(s => ({ index: s.row.index, name: s.row.name, status: s.row.status, verdict: s.row.verdict, held: s.row.held_back }))`);
  const failedRows = rows.filter(r => r.status === 'failed' || r.status === 'stuck');
  console.log('campaign', failedRows.length, 'failed of', rows.length);
  const sizes = {};
  for (const r of failedRows) sizes[r.verdict] = (sizes[r.verdict] ?? 0) + 1;
  console.log('failure groups', JSON.stringify(sizes));
  const biggest = Object.entries(sizes).sort((a, b) => b[1] - a[1])[0][0];
  const fixGroup = GROUP ?? biggest;
  const target = failedRows.find(r => r.verdict === 'false_done') ?? failedRows[0]; // More suction clears this failure, which the edit below needs.
  check('a real world failed', Boolean(target), target ? `${target.name}: ${target.verdict}` : '');

  // Open file at the line.
  await openSquare(target.index);
  await shot('code-rail.png');
  await clickText('.grid-rail button', 'Open file');
  await c.until(`Boolean(document.querySelector('.code-page .cm-content'))`, 'editor', 20);
  check('Open file opens a tab beside the grid', await c.js(`document.querySelector('.code-tab.on .code-tab-name').innerText === 'controller5.py' && !document.querySelector('.lab-tab-grid').classList.contains('on')`));
  await shot('code-active.png');
  await c.until(`/^Traced/.test(document.querySelector('.code-chip').innerText) || !/Tracing/.test(document.querySelector('.code-why-text').innerText)`, 'trace', 200);
  await wait(400);
  const chip = await bodyText('.code-chip');
  const focusOk = await c.js(`(() => { const f = document.querySelector('.cm-code-focus'); if (!f) return false; const r = f.getBoundingClientRect(), e = document.querySelector('.code-editor').getBoundingClientRect(); return r.top >= e.top && r.bottom <= e.bottom; })()`);
  const line = Number(chip.match(/line (\d+)/)?.[1]);
  const fromDoc = (await doc()).split('\n')[line - 1];
  const focusText = await c.js(`document.querySelector('.cm-code-focus')?.innerText ?? ''`);
  check('the editor scrolled to the marked line', focusOk && fromDoc.trim() === focusText.trim(), `${chip}: ${focusText.trim()}`);
  check('the window robot gets a real trace', /^Traced/.test(chip), await bodyText('.code-why-text'));
  check('the file is highlighted Python', await c.js(`document.querySelectorAll('.cm-content span[class*="ͼ"]').length > 20`));
  await shot('code-open.png');

  // The world file is read only.
  await clickText('.code-why button', 'World file');
  await c.until(`document.querySelector('.code-tab.on .code-tab-name')?.innerText.endsWith('.world.json')`, 'world tab', 5);
  await wait(300);
  const worldBefore = await c.js(`window.__lab.code().worldView.state.doc.toString()`);
  await c.js(`window.__lab.code().worldView.focus()`);
  await c.send('Input.insertText', { text: 'x' });
  check('the world file shows and refuses typing', worldBefore.includes('"tower"') && worldBefore === await c.js(`window.__lab.code().worldView.state.doc.toString()`));
  await shot('code-world.png');
  await clickText('.code-tab-name', 'controller5.py');
  await wait(300);

  // A syntax error, then a banned import: a plain refusal, nothing runs.
  const original = await doc();
  const idleAt = await c.js(`Number(document.getElementById('lab').dataset.idle)`);
  await typeAtTop('def (\n');
  await clickText('.code-bar button', 'Run this world');
  await c.until(`!document.querySelector('.code-refused').hidden`, 'syntax refusal', 10);
  const syntax = await bodyText('.code-refused');
  check('a syntax error gets a plain refusal', /Refused/.test(syntax) && /line 1/.test(syntax) && /does not parse/.test(syntax), syntax.replaceAll('\n', ' | '));
  await shot('code-refused-syntax.png');
  await replaceAll(original);
  await typeAtTop('import os\n');
  await clickText('.code-bar button', 'Run this world');
  await c.until(`/import os/.test(document.querySelector('.code-refused').innerText) && !document.querySelector('.code-refused').hidden`, 'import refusal', 10);
  const banned = await bodyText('.code-refused');
  check('a banned import gets a plain refusal', /Refused/.test(banned) && /import os is not allowed/.test(banned), banned.replaceAll('\n', ' | '));
  await shot('code-refused-import.png');
  check('a refusal started no job', await c.js(`Number(document.getElementById('lab').dataset.idle)`) === idleAt && await c.js(`document.querySelector('.code-results').hidden`));
  await replaceAll(original);

  // A user edit that changes the result.
  const edit = 'SUCTION_CLEAN = 1.0';
  const firstVerdict = await c.js(`${row(target.index)}.verdict`);
  await replaceAll(original.replace('SUCTION_CLEAN = 0.85', edit));
  await clickText('.code-bar button', 'Run this world');
  await c.until(`!document.querySelector('.code-results').hidden && document.querySelector('.code-results').innerText.length > 40`, 'edited run', 200);
  await wait(500);
  const now = await c.js(`({ verdict: ${row(target.index)}.verdict, status: ${row(target.index)}.status, first: ${row(target.index)}.first?.verdict, reason: ${row(target.index)}.verdict_reason })`);
  check('a user edit changes the result of that world', now.verdict !== firstVerdict && now.first === firstVerdict && now.verdict !== 'controller_crashed', `${firstVerdict} -> ${now.verdict}: ${now.reason}`);
  check('old and new show side by side', (await bodyText('.code-results')).toLowerCase().includes(target.name.split('_')[0]), (await bodyText('.code-results')).replaceAll('\n', ' | '));
  check('the source files have not changed', JSON.stringify(hashes()) === JSON.stringify(before));
  await shot('code-results.png');
  await clickOn('.lab-tab-grid');
  await wait(800);
  check('the square updated', await c.js(`${row(target.index)}.verdict`) === now.verdict);
  await shot('code-grid-updated.png');
  await openSquare(target.index);
  check('the rail shows the first run and the latest run', /First run/.test(await bodyText('.grid-rail')) && /Latest run/.test(await bodyText('.grid-rail')));
  await c.until(`document.querySelector('.grid-replay .viewport')?.dataset.ready === 'true' || /no replay|could not/i.test(document.querySelector('.grid-replay').innerText)`, 'replay of the edited run', 60);
  check('the edited run replays, after export5 replayed its actions with no controller', await c.js(`document.querySelector('.grid-replay .viewport')?.dataset.ready === 'true'`));
  await wait(1000);
  await shot('code-rail-old-new.png');

  // Reset, then Run all: the sandbox gives back every first verdict.
  await clickText('.grid-rail button', 'Open file');
  await wait(600);
  await clickText('.code-bar button', 'Reset to source');
  await c.until(`document.querySelector('.code-state').innerText === 'Same as source'`, 'reset', 10);
  await wait(800);
  const started = Date.now();
  await clickText('.code-bar button', 'Run all');
  await c.until(`Number(document.querySelector('.code-results').querySelectorAll('.code-row').length) > 5`, 'run all', 400);
  await wait(800);
  const after = await c.js(`[...window.__lab.grid().squares.values()].map(s => ({ index: s.row.index, verdict: s.row.verdict, first: s.row.first?.verdict ?? s.row.verdict, held: s.row.held_back }))`);
  const differ = after.filter(r => !r.held && r.verdict !== r.first);
  check('Run all with the source text gives every first verdict back, in the sandbox', differ.length === 0, `${after.filter(r => !r.held).length} worlds in ${((Date.now() - started) / 1000).toFixed(0)} s, ${differ.length} differ`);
  await shot('code-run-all.png');

  {
    // One AI fix, or the check's stand-in for its edit.
    const group = failedRows.find(r => r.verdict === fixGroup);
    await clickOn('.lab-tab-grid');
    await wait(300);
    await openSquare(group.index);
    await clickText('.grid-rail button', 'Open file');
    await wait(1500);
    await c.until(`!document.querySelector('.code-ai').disabled`, 'AI button', 300);
    console.log('button:', await bodyText('.code-ai'));
    const t0 = Date.now();
    await clickOn('.code-ai');
    await c.until(`Boolean(document.querySelector('.code-fix')) || Boolean(document.querySelector('.chat-fail:last-child')?.innerText.includes('fix'))`, 'AI fix', 590);
    await wait(500);
    const card = await bodyText('.code-fix');
    console.log(`AI FIX after ${((Date.now() - t0) / 1000).toFixed(0)} s\n${card}`);
    const status = await c.js(`document.querySelector('.code-fix').dataset.status`);
    check('the fix shows a diff and counts in the chat, or says why not', status !== 'helped' || (card.includes('Better') && await c.js(`document.querySelectorAll('.code-diff-line').length > 0`)), status);
    const sessionCode = async () => (await fetch(`http://127.0.0.1:${port}/api/sessions/${await c.js(`window.__lab.code().deps.session()`)}/code`, { headers: { Origin: 'http://localhost:5199' } })).json();
    check('the fix is not applied before a decision', !(await sessionCode()).edited);
    await c.js(`document.querySelector('.code-fix').scrollIntoView()`);
    await shot(FIX_PATCH ? 'code-fix-standin.png' : 'code-fix.png');
    if (status === 'helped') {
      await clickOn('.code-fix-accept');
      await c.until(`/Accepted/.test(document.querySelector('.code-fix-state').innerText)`, 'accept', 20);
      await wait(1000);
      check('Accept changes the session copy only', (await sessionCode()).edited && JSON.stringify(hashes()) === JSON.stringify(before));
      await shot('code-fix-accepted.png');
      await clickOn('.lab-tab-grid');
      await wait(800);
      await shot('code-fix-grid.png');
    } else {
      check('a fix that did not help has no Accept button', !(await c.js(`Boolean(document.querySelector('.code-fix-accept'))`)));
    }
  }
  // A fix that lowers the low-pressure guard: tested with no AI call, and flagged.
  const session = await c.js(`window.__lab.code().deps.session()`);
  const folder = join(ROOT, 'policy/runs/server', session, 'campaigns/c1');
  const weak = join(folder, 'weak_controller5.py');
  writeFileSync(weak, readFileSync(join(ROOT, 'policy/highrise5/controller5.py'), 'utf8').replace('LOW_PRESSURE_PA = 1500.0', 'LOW_PRESSURE_PA = 900.0'));
  const failing = (await c.js(`[...window.__lab.grid().squares.values()].map(s => s.row)`)).find(r => r.status === 'failed');
  const weakRun = spawnSync(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/crashlab/fix.py'), 'run', folder, '--base', join(ROOT, 'policy/highrise5/controller5.py'), '--group', failing.verdict, '--patch', weak, '--out', join(folder, 'weak_check')], { encoding: 'utf8' });
  const weakReport = JSON.parse(readFileSync(join(folder, 'weak_check/report.json'), 'utf8'));
  check('a diff that lowers a guard is flagged as weakening a safety check', weakRun.status === 0 && weakReport.flags.length === 2 && /safety check/.test(weakReport.flags[0].words), `${weakReport.status}: ${weakReport.words}`);

  await inspectionPart();

  check('the source files are unchanged at the end', JSON.stringify(hashes()) === JSON.stringify(before));
  const problems = c.problems.filter(p => !/status of 422/.test(p)); // A refusal is a 422, on purpose.
  check('no page errors', problems.length === 0, problems.slice(0, 3).join(' | '));
} catch (err) {
  failed++;
  console.log(`FAIL ${err}`);
  await shot('code-failure.png').catch(() => {});
} finally {
  c.close();
  server.kill();
}
console.log(failed ? `FAILED ${failed}` : 'PASS');
process.exit(failed ? 1 : 0);
