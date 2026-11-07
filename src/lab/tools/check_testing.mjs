// Drives limits, Find the limit and Re-run failures in a real browser, on a real server with stored AI replies: real physics, real verdicts, no AI call. It starts its own server, site server and vite, with its own suite folder.
// node src/lab/tools/check_testing.mjs --real window|inspection [--limit N] [--patch FILE] [--out DIR]. Results are simulated.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const PACK = arg('real', 'window');
const LIMIT = arg('limit', '20');
const PATCH = arg('patch', null);
const RECORDED = process.argv.includes('--recorded'); // Plays policy/runs/demo: no sim, and the stored real results.
const SUITE = arg('suite', mkdtempSync(join(tmpdir(), 'check-testing-suite-')));
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

const [RUN, SITE, WEB] = [await freePort(), await freePort(), await freePort()];
const env = { ...process.env, CRASHLAB_WEB_PORT: String(WEB), CRASHLAB_SITE_PORT: String(SITE), VITE_RUN_PORT: String(RUN), CRASHLAB_REGRESSIONS_ROOT: SUITE };
const PY = join(ROOT, 'policy/.venv/bin/python');
const kids = [
  spawn(PY, [join(ROOT, 'policy/server/server.py'), '--port', String(RUN), '--recorded', join(ROOT, RECORDED ? 'policy/runs/demo' : 'policy/server/fixtures'), ...(RECORDED ? [] : ['--scenario-limit', LIMIT])], { stdio: 'ignore', env }),
  spawn(PY, [join(ROOT, 'policy/server/site_data.py'), '--port', String(SITE)], { stdio: 'ignore', env }),
  spawn(join(ROOT, 'node_modules/.bin/vite'), ['--port', String(WEB), '--strictPort'], { stdio: 'ignore', env, cwd: ROOT }),
];
for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${RUN}/api/health`); await fetch(`http://127.0.0.1:${WEB}/lab.html`); break; } catch { await wait(200); } }

const c = await openChrome({ width: 1600, height: 1000 });
const shot = name => c.shot(join(OUT, name));
const box = sel => c.js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
const clickOn = async sel => { const b = await box(sel); await c.click(b.x, b.y); };
const say = text => c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`);
const chatHas = (re, seconds = 30) => c.until(`${re}.test(document.querySelector('.chat').innerText)`, String(re), seconds);
const rail = () => c.js(`document.querySelector('.grid-rail').innerText`);
const key = PACK === 'window' ? { word: 'wind', factor: 'Wind', bad: 'wind limit 0 to 99' } : { word: 'payload', factor: 'Payload', bad: 'payload limit 0 to 99' };

try {
  await c.send('Page.navigate', { url: `http://localhost:${WEB}/lab.html?server=${RUN}` });
  await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus')`, 'server up', 40);
  if (PACK === 'inspection') {
    await clickOn('.chat-plus');
    await c.until(`document.querySelectorAll('.chat-menu-row').length >= 3`, 'menu', 8);
    await clickOn('.chat-menu-row[data-pack=inspection]');
    await c.until(`document.getElementById('lab')?.dataset.pack === 'inspection'`, 'inspection session', 30);
  }
  await wait(800);
  if (RECORDED) {
    await c.until(`!document.querySelector('.chat-test').hidden`, 'test button', 60);
    await clickOn('.chat-test');
    await c.until(`document.querySelector('.chat-run')`, 'scenario list', 60);
    await clickOn('.chat-run');
    await c.until(`document.querySelector('.grid-page')?.dataset.done === 'true'`, 'recorded batch ends', 120);
    await wait(3000);
    const strip = await c.js(`document.querySelector('.t-strip').innerText`);
    check('a recorded batch shows coverage', /of 10/.test(strip), strip.replaceAll('\n', ' ').slice(0, 140));
    await shot(`limits-recorded-${PACK}.png`);
    await clickOn('.sq[data-status=failed]');
    await c.until(`document.querySelector('.grid-find')`, 'Find the limit button', 20);
    await c.js(`document.querySelector('.grid-find').click()`);
    await c.until(`document.querySelector('.grid-rail').dataset.mode === 'boundary' && document.querySelector('.t-search')`, 'stored search', 20);
    await wait(500);
    const found = await rail();
    check('the stored search plays, labelled recorded', /Recorded result/.test(found) && /seeds/.test(found), found.replaceAll('\n', ' ').slice(0, 240));
    await shot(`boundary-recorded-${PACK}.png`);
    await wait(1500);
    await clickOn('.grid-back');
    await c.js(`[...document.querySelectorAll('.grid-btn')].find(b => b.textContent === 'Re-run failures').click()`);
    await c.until(`document.querySelector('.t-go')`, 'suite panel', 10);
    await clickOn('.t-go');
    await c.until(`document.querySelector('.t-suite')`, 'stored suite', 20);
    await wait(500);
    const suite = await rail();
    check('the stored suite plays, labelled recorded', /Recorded result/.test(suite), suite.replaceAll('\n', ' ').slice(0, 200));
    await shot(`regressions-recorded-${PACK}.png`);
    check('no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 5).join('\n'));
    throw 'done';
  }
  await say(PACK === 'inspection' ? 'add a control cabinet beside the walkway' : 'Window robot for towers in Dubai. High floor.');
  for (let i = 0; i < 480 && !(await c.js(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 5`)); i++) {
    await c.js(`[...document.querySelectorAll('.chat-option:not(:disabled)')][0]?.click()`);
    await wait(500);
  }

  // Limits, in chat.
  await c.until(`!document.querySelector('.chat-test').hidden`, 'test button', 60);
  await say(`set the ${key.word} limit to 0 to 12`);
  await chatHas(new RegExp(`${key.factor} limit is now 0 to 12`, 'i'));
  check('set_limits works from the chat', true);
  await wait(800);
  await say(key.bad);
  await chatHas(/That limit was refused/);
  check('a limit outside the physics is refused in the chat', true);
  await wait(800);
  await shot(`limits-chat-${PACK}.png`);

  // List, run.
  await c.until(`!document.querySelector('.chat-test').hidden`, 'test button', 20);
  await clickOn('.chat-test');
  await c.until(`document.querySelector('.chat-run')`, 'scenario list', 240);
  await clickOn('.chat-run');
  await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'grid', 40);
  await c.until(`!document.querySelector('.t-strip').hidden`, 'limits strip', 40);
  check('the strip names each factor', await c.js(`document.querySelectorAll('.t-factor').length`) === (PACK === 'window' ? 7 : 4));
  await c.until(`document.querySelector('.grid-page')?.dataset.running === 'false' && document.querySelector('.grid-page')?.dataset.done === 'true'`, 'campaign ends', 900);
  await wait(3000);
  const strip = await c.js(`document.querySelector('.t-strip').innerText`);
  check('the strip gives plain numbers, and says tested', /Tested/.test(strip) && /of 10/.test(strip) && !/\bsafe\b/i.test(strip.replace('Not a safety claim', '')), strip.replaceAll('\n', ' ').slice(0, 200));
  check('the strip does not push the page wider', await c.js(`document.querySelector('.t-strip').scrollWidth <= document.querySelector('.t-strip').clientWidth + 1`));
  check('the bar fits', await c.js(`document.querySelector('.grid-bar').scrollWidth <= document.querySelector('.grid-bar').clientWidth + 1`));
  await shot(`limits-grid-${PACK}.png`);
  await clickOn('.t-factor');
  await c.until(`document.querySelector('.grid-rail')?.dataset.mode === 'limits'`, 'limits panel', 5);
  const panel = await rail();
  check('the panel lists what was dropped, with a reason', /Dropped, outside the limits/.test(panel) && /limit of/.test(panel), panel.slice(0, 100));
  check('the panel says tested is not safe', /does not mean the robot is safe/.test(panel));
  await wait(400);
  await shot(`limits-panel-${PACK}.png`);
  await c.js(`document.querySelector('.grid-rail').scrollTop = 1e6`);
  await wait(200);
  await shot(`limits-dropped-${PACK}.png`);
  await clickOn('.grid-back');

  // Find the limit, from a failed square.
  const failedIndex = await c.js(`(async () => { const base = window.__lab.grid().deps.base; for (const s of document.querySelectorAll('.sq[data-status=failed], .sq[data-status=stuck]')) { const d = await (await fetch(base + '/worlds/' + s.dataset.index)).json(); const moved = (d.changes ?? []).some(l => /^set_(robot|wind|weather|floor|payload)|add_(steps|valve|cable_tray|grating)/.test(l)); if (moved) return s.dataset.index; } return document.querySelector('.sq[data-status=failed], .sq[data-status=stuck]')?.dataset.index; })()`);
  check('a failed square exists', failedIndex !== undefined && failedIndex !== null, String(failedIndex));
  await clickOn(`.sq[data-index="${failedIndex}"]`);
  await c.until(`document.querySelector('.grid-find')`, 'Find the limit button', 20);
  await wait(1500);
  await c.js(`document.querySelector('.grid-find').scrollIntoView()`);
  await shot(`boundary-button-${PACK}.png`);
  await clickOn('.grid-find');
  await c.until(`document.querySelector('.grid-rail').dataset.mode === 'boundary'`, 'boundary panel', 10);
  await c.until(`document.querySelector('.t-tile[data-status=running]')`, 'live run', 60);
  check('runs show live, in the square colours', await c.js(`getComputedStyle(document.querySelector('.t-tile[data-status=running]')).borderTopColor`) !== '');
  await shot(`boundary-running-${PACK}.png`);
  await c.until(`document.querySelector('.grid-rail-title')?.textContent === 'The limit'`, 'search ends', 1800);
  await wait(800);
  const found = await rail();
  check('the search says what it found, in words', /between .* and .*seeds|No clean boundary/.test(found), found.replaceAll('\n', ' ').slice(0, 300));
  check('the panel has no Simulated tag', !/Simulated/.test(found));
  await c.js(`document.querySelector('.grid-rail').scrollTop = 0`);
  await shot(`boundary-done-${PACK}.png`);
  await clickOn('.grid-back');

  // Re-run failures on the same code: no fix can be claimed.
  await wait(3000); // The job's last chat lines come after its last state.
  await c.js(`[...document.querySelectorAll('.grid-btn')].find(b => b.textContent === 'Re-run failures').click()`);
  await c.until(`document.querySelector('.grid-rail').dataset.mode === 'regressions' && document.querySelector('.t-go')`, 'suite panel', 10);
  const size = await c.js(`document.querySelector('.t-go').textContent`);
  check('the suite holds the campaign failures', /Run [1-9]/.test(size), size);
  await shot(`regressions-idle-${PACK}.png`);
  await clickOn('.t-go');
  await c.until(`document.querySelector('.t-suite')`, 'suite rows', 30);
  await c.until(`document.querySelector('.t-suite[data-status=running]')`, 'live suite run', 60);
  await shot(`regressions-running-${PACK}.png`);
  await c.until(`document.querySelector('.t-suite') && !document.querySelector('.t-suite[data-change=running]')`, 'suite ends', 1800);
  await wait(800);
  const first = await rail();
  check('same code: nothing is called fixed', /\b0\s*Fixed/.test(first), first.replaceAll('\n', ' ').slice(0, 120));
  await shot(`regressions-same-code-${PACK}.png`);

  // Re-run failures on an edited controller.
  if (PATCH) {
    const res = await c.js(`fetch('http://127.0.0.1:${RUN}/api/sessions/' + (window.__lab.grid().deps.base.split('/sessions/')[1].split('/')[0]) + '/code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: ${JSON.stringify(JSON.stringify({ source: readFileSync(resolve(PATCH), 'utf8') }))} }).then(r => r.status)`);
    check('the edited controller is accepted', res === 200, String(res));
    await wait(3000);
    await clickOn('.grid-back');
    await c.js(`[...document.querySelectorAll('.grid-btn')].find(b => b.textContent === 'Re-run failures').click()`);
    await c.until(`document.querySelector('.t-go')`, 'suite panel', 10);
    await clickOn('.t-go');
    await c.until(`document.querySelector('.t-suite[data-status=running]')`, 'live suite run', 200);
    await c.until(`document.querySelector('.t-suite') && !document.querySelector('.t-suite[data-change=running]')`, 'suite ends', 1800);
    await wait(800);
    const second = await rail();
    console.log(second.replaceAll('\n', ' ').slice(0, 900));
    await shot(`regressions-edited-${PACK}.png`);
  }

  // Data page.
  await c.js(`localStorage.setItem('crashlab-guest', '1'); sessionStorage.setItem('crashlab-guest', '1')`);
  await c.send('Page.navigate', { url: `http://localhost:${WEB}/data.html?c=demo-${PACK}` });
  await c.until(`document.querySelector('.coverage table')`, 'coverage table', 40);
  await c.until(`document.querySelector('.suites h2')`, 'suite table', 20);
  const data = await c.js(`document.querySelector('.coverage').innerText + document.querySelector('.suites').innerText`);
  check('Data shows the limits and the suite', /Operating limits/.test(data) && /Regression suite/.test(data) && /Bands tested/.test(data), data.replaceAll('\n', ' ').slice(0, 160));
  await c.js(`document.querySelector('.coverage').scrollIntoView()`);
  await wait(400);
  await shot(`limits-data-${PACK}.png`);
  await c.js(`document.querySelector('.suites').scrollIntoView()`);
  await wait(400);
  await shot(`regressions-data-${PACK}.png`);
  const problems = c.problems.filter(p => !/\/api\/(bounties|budget)/.test(p)); // This check starts no board server, and the sidebar asks for one.
  check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 5).join('\n'));
} catch (err) {
  if (err === 'done') { for (const k of kids) k.kill('SIGTERM'); c.close(); console.log(failed ? `${failed} FAILED` : 'ALL PASS'); process.exit(failed ? 1 : 0); }
  failed++;
  console.log('FAIL', String(err));
  await shot(`testing-error-${PACK}.png`).catch(() => {});
}
c.close();
for (const k of kids) k.kill('SIGTERM');
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
