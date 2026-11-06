// Drives the robot menu and the test grid in lab.html in a real browser, with real mouse moves.
// node src/lab/tools/check_grid.mjs [--out DIR] [--real inspection|window] [--limit N]. Needs vite on port 5199.
// With no --real it starts fake_lab_server.mjs, whose verdicts are invented. With --real it starts its own real server on a free port with stored AI replies: real physics, real verdicts, no paid call.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const REAL_PACK = arg("real", null); // inspection or window: start the real server with stored AI replies.
const LIMIT = arg("limit", "8");
const REAL = REAL_PACK !== null;
const SQUARES = 50;
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

const servers = [];
async function fakeServer(args) {
  const port = await freePort();
  const child = spawn(process.execPath, [join(ROOT, 'src/lab/tools/fake_lab_server.mjs'), '--port', String(port), ...args], { stdio: 'inherit' });
  servers.push(child);
  for (let i = 0; i < 50; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`); break; } catch { await wait(100); } }
  return port;
}

async function realServer() {
  const port = await freePort();
  const child = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port), '--recorded', join(ROOT, 'policy/server/fixtures'), '--scenario-limit', LIMIT], { stdio: 'ignore' });
  servers.push(child);
  for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers: { Origin: 'http://localhost:5199' } }); break; } catch { await wait(200); } }
  return port;
}

const COUNT_CONTEXTS = `(() => {
  const made = [], gl = window.__gl = { created: 0, peak: 0, get live() { return made.filter(c => !c.isContextLost()).length; } };
  const real = HTMLCanvasElement.prototype.getContext;
  const seen = new WeakSet();
  HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
    const ctx = real.call(this, kind, ...rest);
    if (ctx && /webgl/.test(kind) && !seen.has(ctx)) {
      seen.add(ctx);
      made.push(ctx);
      gl.created++;
      gl.peak = Math.max(gl.peak, gl.live);
    }
    return ctx;
  };
})()`;
const SAMPLE = seconds => `new Promise(done => {
  const times = []; let last = performance.now(); const end = last + ${seconds * 1000};
  const g = window.__lab.grid(); const ms0 = g.drawMs, n0 = g.drawn;
  const tick = now => { times.push(now - last); last = now; if (now < end) requestAnimationFrame(tick); else {
    const s = [...times].slice(1).sort((a, b) => a - b);
    done({ frames: s.length, mean: s.reduce((a, b) => a + b, 0) / s.length, p95: s[Math.floor(s.length * 0.95)], max: s[s.length - 1], over33: s.filter(x => x > 33.4).length, drawMs: (g.drawMs - ms0) / Math.max(1, g.drawn - n0), running: document.querySelectorAll('.sq[data-status=running]').length });
  } };
  requestAnimationFrame(tick);
})`;
const fmt = t => `mean ${t.mean.toFixed(1)} ms, p95 ${t.p95.toFixed(1)} ms, max ${t.max.toFixed(1)} ms, ${t.over33} of ${t.frames} frames over 33 ms, grid draw ${t.drawMs.toFixed(2)} ms, ${t.running} live`;

const c = await openChrome();
const page = port => `http://localhost:5199/lab.html?server=${port}`;
const shot = name => c.shot(join(OUT, REAL && !name.startsWith('grid-real') ? name.replace('grid-', `grid-real-${REAL_PACK}-`) : name));
const box = sel => c.js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height }; })()`);
const clickOn = async sel => { const b = await box(sel); await c.click(b.x, b.y); };
const gl = () => c.js('({ created: window.__gl.created, live: window.__gl.live, peak: window.__gl.peak })');

try {
  await c.send('Page.addScriptToEvaluateOnNewDocument', { source: COUNT_CONTEXTS });
  const port = REAL ? await realServer() : await fakeServer(['--procs', '6', '--speed', '5']);
  const PACK = REAL_PACK ?? 'inspection';
  const tag = REAL ? `grid-real-${PACK}` : 'grid';
  await c.send('Page.navigate', { url: page(port) });
  await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus')`, 'server up', 30);

  // Task 1: the robot menu.
  await clickOn('.chat-plus');
  await c.until(`document.querySelectorAll('.chat-menu-row').length >= 3`, 'menu', 8);
  const menu = await c.js(`document.querySelector('.chat-menu').innerText`);
  check('the menu lists both robots', /Window cleaning robot/.test(menu) && /Inspection robot/.test(menu), menu.replaceAll('\n', ' | '));
  check('import says Not yet, and cannot be pressed', /Import a robot file\s*Not yet/.test(menu) && await c.js(`document.querySelector('.chat-menu-import').disabled`));
  await shot('grid-picker.png');
  if (PACK === 'inspection') {
    await clickOn('.chat-menu-row[data-pack=inspection]');
    await c.until(`document.getElementById('lab')?.dataset.pack === 'inspection' && document.querySelector('.viewport')?.dataset.ready === 'true'`, 'inspection session', 30);
    check('choosing a robot starts its session', await c.js(`sessionStorage.getItem('crashlab-pack') === 'inspection'`));
  } else {
    await c.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape' });
    await c.js(`document.querySelector('.chat-menu').hidden = true`);
  }
  await wait(600);
  if (PACK === 'inspection') {
    await shot(`${tag}-plant-preview.png`);
    check('the plant shows with one WebGL context', (await gl()).live === 1, JSON.stringify(await gl()));
  }
  const say = PACK === 'inspection' ? (REAL ? 'add a control cabinet beside the walkway' : 'walk the route') : 'Window robot for towers in Dubai. High floor.';
  await c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(say)}; document.querySelector('.chat-send').click(); })()`);
  // The window robot asks questions first. The first option answers them, as check_lab does.
  for (let i = 0; i < 480 && !(await c.js(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 5`)); i++) {
    await c.js(`[...document.querySelectorAll('.chat-option:not(:disabled)')][0]?.click()`);
    await wait(500);
  }
  check(`the ${PACK} robot plays in the main area`, await c.js(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 5`) && (await gl()).live === 1, JSON.stringify(await gl()));
  await wait(3000);
  await shot(`${tag}-single-view.png`);

  // List, then run.
  await c.until(`!document.querySelector('.chat-test').hidden`, 'test button', 20);
  await clickOn('.chat-test');
  await c.until(`document.querySelector('.chat-run') || /No scenario list/.test(document.querySelector('.chat-list').innerText)`, 'scenario list', 240);
  const cardText = await c.js(`document.querySelector('.chat-list-card').innerText`);
  check('the list shows the count and the guess note', /scenarios/.test(cardText) && /guess/i.test(cardText));
  await shot('grid-list.png');
  await clickOn('.chat-run');
  await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'moving' || document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'grid opens', 30);
  await wait(300);
  await shot('grid-zoom-mid.png');
  await c.until(`document.querySelector('.grid-page').dataset.zoom === 'done'`, 'zoom ends', 5);
  await wait(400);
  const squares = await c.js(`document.querySelectorAll('.sq canvas').length`);
  check(`one canvas per scenario`, REAL ? squares > 0 : squares === SQUARES, String(squares));
  const after = await gl();
  check('the WebGL view closes behind the grid, so no extra context', after.live === 0 && after.peak === 1, JSON.stringify(after));
  check('status bar still says Simulated', await c.js(`document.querySelector('.lab-status').innerText.includes('Simulated')`));

  const t1 = await c.js(SAMPLE(6));
  check(`smooth at ${squares} squares`, t1.p95 < 25 && t1.over33 < t1.frames * 0.05, fmt(t1));
  await shot('grid-running.png');

  // Hover.
  const target = await box('.sq[data-index="2"]');
  await c.mouse('mouseMoved', target.x, target.y);
  await c.until(`!document.querySelector('.grid-hover').hidden`, 'hover card', 3);
  const hover = await c.js(`document.querySelector('.grid-hover').innerText`);
  check('hover gives the name and the reason', hover.includes('Reasoned guess:'), hover.replaceAll('\n', ' | ').slice(0, 140));
  await shot('grid-hover.png');
  await c.mouse('mouseMoved', 20, 400);

  // A stuck world goes red.
  if (!REAL) await c.until(`document.querySelector('.sq[data-status=stuck]')`, 'a stuck world', 60);
  if (!REAL) {
  await wait(200);
  const red = await c.js(`(() => {
    const b = document.querySelector('.sq[data-status=stuck]'); const v = b.querySelector('canvas'); const d = v.getContext('2d').getImageData(4, Math.floor(v.height / 2), 1, 1).data;
    return { border: getComputedStyle(b).borderTopColor, fill: [...d].slice(0, 3), index: b.dataset.index, label: b.getAttribute('aria-label') };
  })()`);
  check('a stuck world goes red', red.border === 'rgb(207, 58, 47)' && red.fill[0] > red.fill[1] + 8, JSON.stringify(red));
  check('the counts say so', Number(await c.js(`document.querySelector('.grid-count[data-status=stuck] b').textContent`)) >= 1);
  await shot('grid-stuck.png');

  // Click: a run still going opens the panel over the grid, with no replay.
  await clickOn(`.sq[data-index="${red.index}"]`);
  await c.until(`document.querySelector('.grid-rail')?.dataset.index === ${JSON.stringify(red.index)}`, 'stuck detail', 10);
  const stuckText = await c.js(`document.querySelector('.grid-rail').innerText`);
  check('a live run says its replay comes later', /replay comes when this run ends/.test(stuckText));
  check('no replay opens for it, so no WebGL', (await gl()).live === 0);
  await shot('grid-stuck-detail.png');
  await clickOn('.grid-back');
  }

  // A finished run: the full replay in the main view.
  const ENDED = '.sq[data-status=failed], .sq[data-status=passed]';
  await c.until(`document.querySelector('${REAL ? ENDED : '.sq[data-status=failed]'}')`, 'a finished world', REAL ? 600 : 60);
  const index = await c.js(`(document.querySelector('.sq[data-status=failed]') ?? document.querySelector('.sq[data-status=passed]')).dataset.index`);
  const statesBefore = await c.js(`document.querySelectorAll('.sq[data-status=passed], .sq[data-status=failed]').length`);
  const updatesBefore = await c.js(`Number(document.querySelector('.grid-page').dataset.updates)`);
  const stillRunning = await c.js(`document.querySelector('.grid-page').dataset.running === 'true'`);
  await clickOn(`.sq[data-index="${index}"]`);
  await c.until(`document.querySelector('.grid-replay .viewport')?.dataset.ready === 'true' && Number(document.querySelector('.grid-replay .viewport').dataset.frame) > 0`, 'replay plays', 30);
  const rail = await c.js(`document.querySelector('.grid-rail').innerText`);
  for (const word of ['Judge', 'Why this scenario', 'Numbers', 'Last log lines', 'Open file']) check(`detail has ${word}`, rail.includes(word));
  check('one WebGL context with the replay open', (await gl()).live === 1, JSON.stringify(await gl()));
  await wait(2500);
  await shot('grid-detail.png');
  const updatesDuring = await c.js(`Number(document.querySelector('.grid-page').dataset.updates)`);
  if (stillRunning) check('the grid keeps taking events behind the replay', updatesDuring > updatesBefore, `${updatesBefore} -> ${updatesDuring}`);
  await clickOn('.grid-back');
  await wait(300);
  const statesAfter = await c.js(`document.querySelectorAll('.sq[data-status=passed], .sq[data-status=failed]').length`);
  check('returning to the grid keeps state', statesAfter >= statesBefore && await c.js(`document.querySelectorAll('.sq canvas').length`) === squares, `${statesBefore} ended before, ${statesAfter} after`);
  const blank = await c.js(`(() => { const v = document.querySelector('.sq[data-index="0"] canvas'); return v.width > 0 && v.offsetWidth > 0; })()`);
  check('the squares draw again', blank);
  check('the replay context is gone', (await gl()).live === 0, JSON.stringify(await gl()));

  // Not tested.
  await clickOn('.grid-bar .grid-btn');
  await c.until(`document.querySelector('.grid-rail')?.dataset.mode === 'not_tested'`, 'not tested list', 3);
  check('the not tested list opens', (await c.js(`document.querySelectorAll('.grid-nt').length`)) > 0);
  await shot('grid-not-tested.png');
  await clickOn('.grid-back');

  await c.until(`document.querySelector('.grid-page').dataset.done === 'true'`, 'campaign done', REAL ? 900 : 120);
  await wait(300);
  await shot('grid-done.png');
  // What the top says matches what the squares say.
  const said = await c.js(`(() => {
    const word = l => l.split('. ')[1] ?? '';
    const labels = [...document.querySelectorAll('.sq')].map(b => word(b.getAttribute('aria-label')));
    const chip = k => Number(document.querySelector('.grid-count[data-status=' + k + '] b').textContent);
    return { stuckSquares: labels.filter(l => /^Stuck|^Froze/.test(l)).length, stuck: chip('stuck'), backSquares: labels.filter(l => /^Held back/.test(l)).length, back: chip('held'), holdSquares: labels.filter(l => /^Safe hold/.test(l)).length, hold: chip('safe_hold'), failedSquares: document.querySelectorAll('.sq[data-status=failed]').length, failed: chip('failed') };
  })()`);
  check('a square that says Stuck counts under Stuck', said.stuckSquares === said.stuck, JSON.stringify(said));
  check('held back and safe hold each count their own squares', said.backSquares === said.back && said.holdSquares === said.hold && said.failedSquares === said.failed);
  if (REAL) {
    const marks = await c.js(`[...document.querySelectorAll('.sq')].map(b => Number(b.dataset.marks))`);
    check('every square carries marks from its scenario', marks.every(n => n > 0), marks.join(','));
    await c.shot(join(OUT, `grid-real-${PACK}.png`));
    await c.until(`document.querySelectorAll('.sq[data-picture=film]').length === document.querySelectorAll('.sq:not([data-held=true])').length`, 'every run has its film', 30);
    const moved = await c.js(`(async () => {
      const sums = () => [...document.querySelectorAll('.sq canvas')].map(v => { const d = v.getContext('2d').getImageData(0, 0, v.width, v.height).data; let s = 0; for (let i = 0; i < d.length; i += 40) s = (s + d[i]) % 65521; return s; });
      const a = sums(); await new Promise(r => setTimeout(r, 1000)); const b = sums();
      return { changed: a.filter((v, i) => v !== b[i]).length, pictured: document.querySelectorAll('.sq[data-picture]').length };
    })()`);
    check('squares move on screen', moved.pictured > 0 && moved.changed >= moved.pictured * 0.7, JSON.stringify(moved));
    await c.shot(join(OUT, `grid-video-${PACK}.png`));
  }
  check('Finished line shows', /Finished in/.test(await c.js(`document.querySelector('.grid-clock').textContent`)));

  // A reload finds the finished grid again.
  await c.send('Page.reload');
  await c.until(`document.querySelector('.grid-page')?.dataset.done === 'true'`, 'grid after reload', 30);
  check('a reload brings the finished grid back', (await c.js(`document.querySelectorAll('.sq canvas').length`)) === squares);

  check('no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 8).join('\n'));

  // Worst case: every square live at once, and the window robot's outline.
  if (!REAL) {
    const stress = await fakeServer(['--procs', '50', '--speed', '0.25']);
    await c.js(`sessionStorage.clear(); sessionStorage.setItem('crashlab-pack', 'window')`);
    await c.send('Page.navigate', { url: page(stress) });
    await c.until(`document.getElementById('lab')?.dataset.server === 'up'`, 'stress server', 20);
    await wait(800);
    const id = await c.js(`sessionStorage.getItem('crashlab-session')`);
    const post = (action) => fetch(`http://127.0.0.1:${stress}/api/sessions/${id}/action`, { method: 'POST', body: JSON.stringify({ action }) });
    await post('list_scenarios');
    await c.until(`document.querySelector('.chat-run')`, 'list on stress', 10);
    await post('run_campaign');
    await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'grid on stress', 15);
    await wait(3000);
    const t2 = await c.js(SAMPLE(6));
    check('smooth with every square live', t2.p95 < 25 && t2.over33 < t2.frames * 0.05, fmt(t2));
    await shot('grid-window-all-live.png');
  }
} catch (err) {
  check('finished', false, String(err));
  try { await shot('grid-failure.png'); } catch {}
} finally {
  c.close();
  for (const s of servers) s.kill();
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 400);
