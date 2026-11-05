// Headless check of app.html. No user input, no visible window: node src/app/tools/check_app.mjs <out dir>
// Needs `npx vite --port 5199` running.
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://localhost:5199';
const OUT = resolve(process.argv[2] ?? '/tmp/crashlab-app-check');
const ROOT = resolve(import.meta.dirname, '../../..');
mkdirSync(OUT, { recursive: true });
const profile = mkdtempSync(join(tmpdir(), 'crashlab-chrome-'));
const PORT = 9333;
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--mute-audio', 'about:blank',
], { stdio: 'ignore' });

process.on('exit', () => chrome.kill());
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ': ' + detail : ''}`); };
const wait = ms => new Promise(r => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* Chrome still starting */ }
    await wait(200);
  }
  throw new Error('Chrome did not start');
}

const ws = new WebSocket(await target());
await new Promise(r => ws.addEventListener('open', r));
let nextId = 1;
const pending = new Map();
const problems = [];
ws.addEventListener('message', m => {
  const msg = JSON.parse(m.data);
  if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); return; }
  if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
  if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(msg.params.type)) problems.push(`${msg.params.type}: ${msg.params.args.map(a => a.value ?? a.description).join(' ')}`);
  if (msg.method === 'Log.entryAdded' && ['error', 'warning'].includes(msg.params.entry.level)) problems.push(`${msg.params.entry.level}: ${msg.params.entry.text} ${msg.params.entry.url ?? ''}`);
});
const send = (method, params = {}) => new Promise(r => { const id = nextId++; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails)}`);
  return r.result.result.value;
};
const shot = async name => {
  const r = await send('Page.captureScreenshot', { format: 'png' });
  const path = join(OUT, name);
  writeFileSync(path, Buffer.from(r.result.data, 'base64'));
  return path;
};
const until = async (expr, what) => {
  for (let i = 0; i < 600; i++) { if (await js(expr)) return true; await wait(200); }
  throw new Error(`timed out: ${what}`);
};
const open = async query => {
  await send('Page.navigate', { url: `${BASE}/app.html${query}` });
  await wait(300);
  await until(`document.querySelector('.viewport')?.dataset.ready === 'true' || !!document.querySelector('.sim-error')`, 'app ready');
  check(`no load error ${query}`, !(await js(`!!document.querySelector('.sim-error')`)), await js(`document.querySelector('.sim-error')?.textContent ?? ''`));
};
const scrubTo = async frame => {
  await js(`(() => { const s = document.querySelector('.scrub input'); s.value = ${frame}; s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await wait(500);
  return JSON.parse(await js(`document.querySelector('.viewport').dataset.robot`));
};
const roller = async () => JSON.parse(await js(`document.querySelector('.viewport').dataset.roller`));
const key = async (code, k, modifiers = 0) => {
  const base = { code, key: k, modifiers, text: k === ' ' ? ' ' : undefined };
  await send('Input.dispatchKeyEvent', { type: 'keyDown', ...base });
  await send('Input.dispatchKeyEvent', { type: 'keyUp', ...base });
};

await send('Runtime.enable');
await send('Log.enable');
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

// Replay against the recorded state.
for (const id of ['nominal-seed1', 'dubai-world-013']) {
  await open(`?trial=${id}`);
  const ref = JSON.parse(readFileSync(join(ROOT, 'public/trials', id, 'reference.json'), 'utf8'));
  let worst = 0;
  for (const r of ref) {
    const got = await scrubTo(r.frame);
    const wheel = await roller();
    worst = Math.max(worst, ...got.map((v, i) => Math.abs(v - r.robot[i])), ...wheel.map((v, i) => Math.abs(v - r.roller[i])));
  }
  check(`${id}: browser robot and roller positions equal Python mj_forward at ${ref.length} frames`, worst < 1e-6, `worst difference ${worst.toExponential(2)} m`);
  const a = ref[Math.floor(ref.length * 0.3)], b = ref[Math.floor(ref.length * 0.7)];
  const pa = await scrubTo(a.frame);
  console.log(`${id} frame ${a.frame}: robot`, pa.map(v => v.toFixed(4)).join(' '), 'recorded', a.robot.map(v => v.toFixed(4)).join(' '));
  await shot(`${id}-a.png`);
  const pb = await scrubTo(b.frame);
  console.log(`${id} frame ${b.frame}: robot`, pb.map(v => v.toFixed(4)).join(' '), 'recorded', b.robot.map(v => v.toFixed(4)).join(' '));
  await shot(`${id}-b.png`);
  check(`${id}: robot moved between the two captures`, Math.hypot(pa[0] - pb[0], pa[2] - pb[2]) > 0.05);
  const marks = await js(`document.querySelectorAll('.mark').length`);
  const fired = Object.keys(JSON.parse(readFileSync(join(ROOT, 'public/trials', id, 'result.json'), 'utf8')).fired).length;
  check(`${id}: one red timeline mark per fired rule`, marks === fired, `${marks} of ${fired}`);
  check(`${id}: label shows`, (await js(`document.querySelector('.sim-label').textContent`)) === 'Simulated. Replay of a recorded run.');
}

await open('?trial=nominal-seed1');
await send('Page.bringToFront');
await shot('start-of-chat.png');

// Space toggles playback when focus is not in a text box.
await js(`document.activeElement?.blur()`);
const was = await js(`document.querySelector('.viewport').dataset.playing`);
await key('Space', ' ');
await wait(100);
check('Space toggles play and pause', (await js(`document.querySelector('.viewport').dataset.playing`)) !== was);
const f1 = await js(`document.querySelector('.viewport').dataset.frame`);
await wait(50);

// Chat: hostile HTML and long text stay plain text.
const typeAndSend = async (text, send = 'click') => {
  await js(`(() => { const t = document.querySelector('.chat-input textarea'); t.focus(); t.value = ${JSON.stringify(text)}; t.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  if (send === 'click') await js(`document.querySelector('.send').click()`);
  else await key('Enter', 'Enter', 4);
  await wait(200);
};
const hostile = `<img src=x onerror="window.__pwned=1"><script>window.__pwned=2</scr` + `ipt><b>bold</b><svg onload="window.__pwned=3">`;
await typeAndSend(hostile);
const users = () => js(`[...document.querySelectorAll('.msg-user')].map(e => e.textContent)`);
check('hostile HTML shows as plain text', (await users()).includes(hostile));
check('hostile HTML made no elements', (await js(`document.querySelectorAll('.msg *, .chat-list img, .chat-list script').length`)) === 0);
check('hostile HTML did not run', (await js(`window.__pwned === undefined`)));
await typeAndSend('Sent with Cmd+Enter', 'key');
check('Cmd+Enter sends', (await users()).includes('Sent with Cmd+Enter'));
const long = 'x'.repeat(20000) + ' ' + 'long words '.repeat(500);
await typeAndSend(long);
check('long text fits the chat width', await js(`(() => { const l = document.querySelector('.chat-list'); return l.scrollWidth <= l.clientWidth; })()`));
check('input stays on screen after long text', await js(`document.querySelector('.chat-input').getBoundingClientRect().bottom <= innerHeight - 20`));
await shot('chat-hostile-long.png');
await js(`document.querySelector('.diff .btn-primary').click()`);
check('Accept says nothing changed', (await js(`document.querySelector('.diff-note').textContent`)).includes('nothing changed'));

// Divider drag, no visible mouse: synthetic CDP events inside the headless page.
const before = await js(`document.querySelector('.chat').getBoundingClientRect().width`);
const mouse = (type, x, buttons = 1) => send('Input.dispatchMouseEvent', { type, x, y: 400, button: 'left', buttons, clickCount: 1 });
await mouse('mousePressed', before + 0.5);
await mouse('mouseMoved', 520);
await mouse('mouseReleased', 520, 0);
await wait(100);
const after = await js(`document.querySelector('.chat').getBoundingClientRect().width`);
check('divider resizes the chat', Math.abs(after - 520) < 2, `${before} to ${after}`);

// Tabs.
await js(`[...document.querySelectorAll('.tab')].find(t => t.textContent === 'Code').click()`);
await wait(100);
const code = readFileSync(join(ROOT, 'public/trials/nominal-seed1/controller.py.txt'), 'utf8');
check('Code tab shows controller.py', (await js(`document.querySelectorAll('.code-line').length`)) === code.replace(/\n$/, '').split('\n').length);
check('label stays on Code tab', (await js(`document.querySelector('.status span').textContent`)) === 'Simulated. Replay of a recorded run.');
await shot('tab-code.png');
await js(`[...document.querySelectorAll('.tab')].find(t => t.textContent.endsWith(' worlds')).click()`);
await wait(100);
const worldsData = JSON.parse(readFileSync(join(ROOT, 'public/trials/worlds.json'), 'utf8'));
check('worlds tab shows one square per recorded world', (await js(`document.querySelectorAll('.cell').length`)) === worldsData.worlds.length);
check('worlds tab heading uses the recorded count', (await js(`document.querySelector('.worlds-head h1').textContent`)) === `${worldsData.worlds.filter(w => !w.passed && w.failure && w.failure !== 'sim_diverged').length} of ${worldsData.worlds.length} tested worlds failed`);
await shot('tab-worlds.png');
await js(`[...document.querySelectorAll('.tab')].find(t => t.textContent === 'World').click()`);
await wait(200);

// Diff text grows on a large screen and still fits.
const diffSize = () => js(`parseFloat(getComputedStyle(document.querySelector('.diff-line')).fontSize)`);
const small = await diffSize();
await send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
await js(`document.documentElement.style.removeProperty('--chat-width')`);
await wait(300);
const big = await diffSize();
check('diff text scales up at 1920 wide', big > small + 2, `${small}px to ${big}px`);
check('diff fits its panel at 1920 wide', await js(`document.querySelector('.chat-list').scrollWidth <= document.querySelector('.chat-list').clientWidth`));
await shot('projector-1920.png');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await wait(300);

// Layout: no clipped text or text under 13px.
const layout = await js(`(() => { const out = [];
  document.querySelectorAll('#app *').forEach(e => {
    if (e.closest('svg') || e.closest('.chat-list') || e.closest('.code') || e.tagName === 'OPTION') return;
    const hasText = [...e.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
    if (!hasText || !e.getClientRects().length) return;
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    if (parseFloat(s.fontSize) < 13) out.push('SMALL ' + e.textContent.slice(0, 40));
    if (r.right > innerWidth + 0.5 || r.bottom > innerHeight + 0.5) out.push('OFF ' + e.textContent.slice(0, 40));
    if (e.scrollWidth > e.clientWidth + 1 && s.display !== 'inline') out.push('WIDE ' + e.textContent.slice(0, 40));
  }); return out; })()`);
check('no clipped or undersized text', layout.length === 0, layout.join(' | '));

// Default width captures: the worlds tab, and the end of a failed run.
await open('?trial=dubai-world-009');
const end = await js(`document.querySelector('.scrub input').max`);
await scrubTo(Number(end));
await shot('failed-run-end.png');
check('failed run says the robot left the glass', !(await js(`document.querySelector('.sim-off').hidden`)));
await js(`[...document.querySelectorAll('.tab')].find(t => t.textContent.endsWith(' worlds')).click()`);
await wait(200);
await shot('worlds-default.png');

// Source rules.
const files = [];
const walk = d => { for (const f of readdirSync(d)) { const p = join(d, f); if (statSync(p).isDirectory()) { if (f !== 'tools') walk(p); } else files.push(p); } };
walk(join(ROOT, 'src/app'));
const banned = /innerHTML|outerHTML|insertAdjacentHTML|document\.write|new Function|eval\(|challenges\/acme|mj_step/;
const hits = files.filter(f => banned.test(readFileSync(f, 'utf8').replace(/never calls mj_step/, '')));
check('source has no innerHTML, new Function, acme import or mj_step', hits.length === 0, hits.join(' '));
// A software-GL readback note comes from taking screenshots here, not from the app.
const real = problems.filter(p => !p.includes('GPU stall due to ReadPixels'));
check('no console errors, warnings or exceptions', real.length === 0, [...new Set(real)].slice(0, 8).join(' | '));

ws.close();
chrome.kill();
await wait(300);
rmSync(profile, { recursive: true, force: true });
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
