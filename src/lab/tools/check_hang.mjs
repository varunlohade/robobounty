// Injects real failures into lab.html and proves the page recovers: node src/lab/tools/check_hang.mjs [--out DIR]
// Needs vite on port 5199. It starts its own supervisor, its own fault server on a free port and its own Chrome profile, and uses stored AI replies. It touches no other server or tab. See policy/server/fault_server.py.
import { execFileSync, spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const PY = join(ROOT, 'policy/.venv/bin/python');
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });
const PORT = await freePort();
const DEBUG = await freePort();
const SERVER = `http://127.0.0.1:${PORT}`;
const ORIGIN = 'http://localhost:5199';
const PAGE = `${ORIGIN}/lab.html?server=${PORT}`;
const BRIEF = 'Window robot for towers in Dubai. High floor.', CHANGE = 'Make the wind stronger and wet the glass.';
const work = mkdtempSync(join(tmpdir(), 'crashlab-hang-'));
const FAULTS = join(work, 'faults.json');
writeFileSync(FAULTS, '{}');
mkdirSync(OUT, { recursive: true });
const wait = ms => new Promise(r => setTimeout(r, ms));

const supervisor = spawn(PY, [join(ROOT, 'policy/server/supervise.py'), '--port', String(PORT), '--script', join(ROOT, 'policy/server/fault_server.py'), '--faults', FAULTS, '--recorded', join(ROOT, 'policy/server/fixtures_lab')], { stdio: 'ignore' });
const chrome = spawn('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', `--remote-debugging-port=${DEBUG}`, `--user-data-dir=${work}/profile`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows',
  '--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', 'about:blank'], { stdio: 'ignore' });
const finish = code => { chrome.kill(); supervisor.kill(); setTimeout(() => { try { rmSync(work, { recursive: true, force: true }); } catch {} process.exit(code); }, 800); };

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `: ${detail}` : ''}`); };
const faults = obj => writeFileSync(FAULTS, JSON.stringify(obj));
const pageErrors = [];

async function openTab(url) {
  const info = await (await fetch(`http://127.0.0.1:${DEBUG}/json/new?${encodeURIComponent(url)}`, { method: 'PUT' })).json();
  const ws = new WebSocket(info.webSocketDebuggerUrl);
  await new Promise(r => ws.addEventListener('open', r));
  let n = 1;
  const pending = new Map();
  ws.addEventListener('message', m => {
    const msg = JSON.parse(m.data);
    if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); return; }
    if (msg.method === 'Runtime.exceptionThrown') pageErrors.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
  });
  const send = (method, params = {}) => new Promise(r => { const i = n++; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const js = async expr => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 400)}`);
    return r.result.result.value;
  };
  await send('Runtime.enable');
  await send('Page.enable');
  const until = async (expr, what, seconds) => {
    const t0 = Date.now();
    while (Date.now() - t0 < seconds * 1000) { if (await js(expr)) return (Date.now() - t0) / 1000; await wait(200); }
    console.log('chat at timeout:', await js(`document.querySelector('.chat-list')?.innerText`));
    throw new Error(`timed out: ${what}`);
  };
  const tab = {
    send, js, until,
    type: text => js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`),
    idle: () => js(`Number(document.getElementById('lab').dataset.idle ?? 0)`),
    idleAfter: (k, seconds) => until(`Number(document.getElementById('lab').dataset.idle ?? 0) > ${k}`, 'job finished', seconds),
    chat: () => js(`document.querySelector('.chat-list').innerText`),
    frame: () => js(`Number(document.querySelector('.viewport')?.dataset.frame ?? -1)`),
    tid: () => js(`document.querySelector('.viewport')?.dataset.tid ?? ''`),
    slow: () => js(`(() => { const s = document.querySelector('.player select'); s.value = '1'; s.dispatchEvent(new Event('input')); s.dispatchEvent(new Event('change')); })()`),
    shot: async name => { const r = await send('Page.captureScreenshot', { format: 'png' }); const data = Buffer.from(r.result.data, 'base64'); writeFileSync(join(OUT, name), data); console.log('PNG', join(OUT, name)); return data.length; },
    brief: async text => {
      let k = await tab.idle();
      await tab.type(text);
      await tab.idleAfter(k, 120);
      while (await js(`[...document.querySelectorAll('.chat-option')].some(b => !b.disabled)`)) {
        k = await tab.idle();
        await js(`[...document.querySelectorAll('.chat-card')].pop().querySelector('.chat-option:not(:disabled)').click()`);
        await tab.idleAfter(k, 120);
      }
    },
    moving: async () => { const a = await tab.frame(); await wait(1200); const b = await tab.frame(); return { a, b, ok: b > a }; },
    lines: async text => (await tab.chat()).split('\n').filter(l => l.includes(text)).length,
  };
  return tab;
}
const health = async () => (await fetch(`${SERVER}/api/health`, { headers: { Origin: ORIGIN } })).json();
const up = async seconds => { const t0 = Date.now(); while (Date.now() - t0 < seconds * 1000) { try { return await health(); } catch {} await wait(250); } throw new Error('server did not come back'); };

try {
  await up(30);
  for (let i = 0; i < 40; i++) { try { await fetch(`http://127.0.0.1:${DEBUG}/json/version`); break; } catch { await wait(200); } }
  const t = await openTab(PAGE);
  await t.until(`document.getElementById('lab')?.dataset.server === 'up'`, 'server up', 30);

  // A done step never looks stuck, even while the page fetches its replay. The stalled fetch here also proves the fetch deadline.
  faults({ stall_trial: 1 });
  await t.type(BRIEF);
  for (let i = 0; i < 300 && readFileSync(FAULTS, 'utf8').includes('stall_trial'); i++) {
    await t.js(`[...document.querySelectorAll('.chat-option:not(:disabled)')][0]?.click()`);
    await wait(200);
  }
  await wait(1000);
  check('the working row is clear while the replay file is stuck', await t.js(`document.querySelector('.chat-live').hidden && !document.querySelector('.viewport')?.dataset.tid`));
  const fetched = await t.until(`document.querySelector('.chat-list').innerText.includes('The replay did not load in time, so I am fetching it again.')`, 'fetch deadline line', 30);
  check('a stuck replay fetch misses its deadline and the chat says so', fetched >= 10, `${fetched.toFixed(1)} s`);
  await t.until(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 0`, 'replay after retry', 30);
  check('the retry brings the replay', (await t.moving()).ok);
  await t.slow();

  // A lost event stream.
  faults({ cut_streams: 1 });
  const back = await t.until(`document.querySelector('.chat-list').innerText.includes('I lost the connection to the run server, so I reconnected.')`, 'stream reconnected', 20);
  check('a cut event stream reconnects by itself, with one line', (await t.lines('I lost the connection')) === 1, `${back.toFixed(1)} s`);
  check('the replay keeps playing through it', (await t.moving()).ok);
  check('the log has it', readFileSync(join(ROOT, `policy/runs/server/recovery-${PORT}.log`), 'utf8').includes('the page lost its event stream'));

  // WebGL context loss.
  const before = await t.frame();
  const size1 = await t.shot('hang-before-loss.png');
  await t.js(`document.querySelector('.viewport canvas').getContext('webgl2').getExtension('WEBGL_lose_context').loseContext()`);
  const restored = await t.until(`Number(document.querySelector('.viewport').dataset.rebuilt ?? 0) === 1`, 'view rebuilt', 10);
  check('a lost WebGL context rebuilds the view', await t.js(`!document.querySelector('.viewport canvas').getContext('webgl2').isContextLost()`), `${restored.toFixed(1)} s`);
  check('the chat says it in one line', (await t.lines('lost its graphics')) === 1);
  const after = await t.moving();
  check('playback goes on from the same place', after.ok && after.a >= before, `${before} then ${after.a} then ${after.b}`);
  await wait(500);
  const size2 = await t.shot('hang-after-loss.png');
  check('the rebuilt view draws a picture', size2 > size1 * 0.5, `${size1} and ${size2} bytes`);

  // Playback that stops while set to play: the frame loops die, as they do after an exception in a frame.
  await t.js(`(() => { window.__raf = window.requestAnimationFrame; window.requestAnimationFrame = () => 0; })()`);
  await wait(300);
  await t.js(`window.requestAnimationFrame = window.__raf`);
  const frozen = await t.frame();
  await wait(3000);
  check('the injected stall really stops playback', (await t.frame()) === frozen, `frame ${frozen}`);
  const restart = await t.until(`Number(document.querySelector('.viewport').dataset.playbackRestarts ?? 0) === 1`, 'playback restarted', 10);
  const resumed = await t.moving();
  check('a stopped replay restarts from the same frame', resumed.ok && resumed.a >= frozen && resumed.a < frozen + 2000, `${(3 + restart).toFixed(1)} s, frame ${frozen} then ${resumed.a} then ${resumed.b}`);
  check('the chat says it in one line', (await t.lines('The replay stopped moving')) === 1);

  // A reply that never comes.
  faults({ stall_post: 1 });
  const late = Date.now();
  const lateIdle = await t.idle();
  await t.type(CHANGE);
  await t.until(`document.querySelector('.chat-list').innerText.includes('did not answer within 15 s')`, 'late reply line', 25);
  check('a missing reply is called out at its deadline', Date.now() - late < 20000 && !(await t.js(`document.querySelector('.chat-send').disabled`)), `${((Date.now() - late) / 1000).toFixed(1)} s`);
  await t.idleAfter(lateIdle, 90); // The stalled request ends after 40 s and its message runs. The next step waits for that.
  await t.slow();

  // A frozen server, then a killed one. The page only reconnects by itself.
  // Each message sets a new wind. A stored v5 reply sets one value, so sending the same one again rightly changes nothing.
  for (const [signal, words, change] of [['-STOP', 'The run server froze, so I restarted it.', 'make the wind 6 m/s'], ['-KILL', 'The run server crashed, so I restarted it.', 'make the wind 7 m/s']]) {
    const { pid } = await health();
    const lostLines = await t.lines('I lost the connection');
    const start = Date.now();
    execFileSync('kill', [signal, String(pid)]);
    await t.until(`document.querySelector('.chat-list')?.innerText.includes(${JSON.stringify(words)})`, `${signal} line`, 60);
    check(`kill ${signal}: the page reconnects by itself and says so`, (await health()).pid !== pid, `${((Date.now() - start) / 1000).toFixed(1)} s`);
    check(`kill ${signal}: one line, not two`, (await t.lines(words)) === 1 && (await t.lines('I lost the connection')) === lostLines);
    check(`kill ${signal}: the replay kept playing`, (await t.moving()).ok);
    const tidBefore = await t.tid();
    const k = await t.idle();
    await t.type(change);
    await t.idleAfter(k, 60);
    await t.until(`document.querySelector('.viewport')?.dataset.tid !== ${JSON.stringify(tidBefore)} && Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 0`, 'new run plays', 30);
    check(`kill ${signal}: the next message runs the same chat`, (await t.chat()).includes('Changed the world') && (await t.moving()).ok, await t.tid());
    await t.slow();
  }

  // Seven tabs, each with a live stream. The newest still plays a run.
  const tabs = [t];
  for (let i = 0; i < 6; i++) {
    const next = await openTab(PAGE);
    await next.until(`document.getElementById('lab')?.dataset.server === 'up'`, `tab ${i + 2} up`, 20);
    tabs.push(next);
  }
  const newest = tabs.at(-1);
  await newest.brief(BRIEF);
  const played = await newest.until(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 0`, 'newest tab plays', 30);
  check('with 7 tabs open the newest tab plays its run', (await newest.moving()).ok, `${played.toFixed(1)} s after its last step`);
  const streams = async () => (await health()).streams;
  check('every tab holds one stream', (await streams()) === 7, await streams());
  for (let i = 0; i < 3; i++) {
    await newest.send('Page.reload');
    await newest.until(`document.getElementById('lab')?.dataset.server === 'up'`, 'reload up', 20);
    await wait(800);
  }
  check('reloads hold no more streams: the server keeps one for each chat', (await streams()) === 7, await streams());
  await t.send('Page.bringToFront');
  await wait(500);
  check('and the first tab still plays', (await t.moving()).ok);

  // Two pages on one chat: the newer closes the older.
  const sid = await newest.js(`sessionStorage.getItem('crashlab-session')`);
  const older = await fetch(`${SERVER}/api/sessions/${sid}/events?page=1&after=999999`, { headers: { Origin: ORIGIN } });
  const reader = older.body.getReader();
  await fetch(`${SERVER}/api/sessions/${sid}/events?page=1&after=999999`, { headers: { Origin: ORIGIN } }).then(r => { void r; });
  let text = '';
  const stop = setTimeout(() => reader.cancel(), 3000);
  try { while (true) { const { value, done } = await reader.read(); if (done) break; text += new TextDecoder().decode(value); } } catch {}
  clearTimeout(stop);
  check('a newer stream for a chat closes the older one', text.includes('event: replaced'));
  check('no uncaught error in any tab', pageErrors.length === 0, [...new Set(pageErrors)].slice(0, 5).join(' | '));
  const lsof = execFileSync('lsof', ['-nP', '-iTCP:5198', '-sTCP:LISTEN']).toString().split('\n')[1]?.split(/\s+/)[1];
  console.log('the server on 5198, untouched by this check: pid', lsof);
} catch (err) {
  check('the flow finished', false, String(err));
}
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
