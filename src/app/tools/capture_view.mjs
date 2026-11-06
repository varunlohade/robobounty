// Headless capture of the simulation pane. No visible window, no user input.
// node src/app/tools/capture_view.mjs <out prefix> [--gl metal|swiftshader] [--query "?recorded=1"] [--trial id] [--frames 440,1200] [--fps] [--quality q] [--size 1440x900] [--extra "js expr"]
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const has = name => process.argv.includes(`--${name}`);
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const OUT = resolve(process.argv[2]);
mkdirSync(dirname(OUT), { recursive: true });
const GL = arg('gl', 'metal');
const TRIAL = arg('trial', 'dubai-final-world-016');
const FRAMES = arg('frames', '440').split(',').map(Number);
const QUALITY = arg('quality', '');
const [W, H] = arg('size', '1440x900').split('x').map(Number);
const PORT = 9400 + Math.floor(Math.random() * 400);
const DSF = arg('dsf', '1');
const profile = mkdtempSync(join(tmpdir(), 'crashlab-capture-'));
const glFlags = GL === 'metal'
  ? ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist', '--enable-unsafe-webgpu']
  : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, `--window-size=${W},${H}`,
  `--force-device-scale-factor=${DSF}`, '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', ...glFlags, 'about:blank'], { stdio: 'ignore' });
const finish = code => { chrome.kill(); setTimeout(() => { try { rmSync(profile, { recursive: true, force: true }); } catch {} process.exit(code); }, 300); };
const wait = ms => new Promise(r => setTimeout(r, ms));
let url = null;
for (let i = 0; i < 60 && !url; i++) {
  try { url = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === 'page')?.webSocketDebuggerUrl; } catch {}
  if (!url) await wait(200);
}
const ws = new WebSocket(url);
await new Promise(r => ws.addEventListener('open', r));
let id = 1; const pending = new Map(); const problems = [];
ws.addEventListener('message', m => {
  const msg = JSON.parse(m.data);
  if (msg.id) { pending.get(msg.id)?.(msg); pending.delete(msg.id); return; }
  if (msg.method === 'Runtime.exceptionThrown') problems.push(msg.params.exceptionDetails.exception?.description ?? msg.params.exceptionDetails.text);
  if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(msg.params.type)) problems.push(`${msg.params.type}: ${msg.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 600)}`);
});
const send = (method, params = {}) => new Promise(r => { const n = id++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
  return r.result.result.value;
};
const until = async (expr, what, tries = 400) => { for (let i = 0; i < tries; i++) { if (await js(expr)) return; await wait(200); } console.log('problems', problems.slice(0, 12).join('\n'), await js(`document.querySelector('.sim-error')?.textContent ?? ''`)); finish(1); throw new Error(`timed out: ${what}`); };
const shot = async (name, clip) => {
  const r = await send('Page.captureScreenshot', { format: 'png', ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
  writeFileSync(name, Buffer.from(r.result.data, 'base64'));
  console.log('wrote', name);
};
await send('Runtime.enable'); await send('Page.enable');
const q = QUALITY ? `&quality=${QUALITY}` : '';
const query = arg('query', `?trial=${TRIAL}${q}`);
const t0 = Date.now();
await send('Page.navigate', { url: `${arg('base', 'http://localhost:5199')}/app.html${query}` });
await wait(500);
if (query.includes('recorded')) {
  await until(`[...document.querySelectorAll('button')].some(b => /passed|fell|detach|slip|fail|lost/i.test(b.textContent) && b.closest('.card'))`, 'replay button');
  await js(`[...document.querySelectorAll('.card button')].find(b => /passed|fell|detach|slip|fail|lost/i.test(b.textContent)).click()`);
}
await until(`(document.querySelector('.viewport')?.dataset.ready === 'true' && !!document.querySelector('input[aria-label=Timeline]')) || !!document.querySelector('.sim-error')`, 'viewport ready', 600);
console.log('ready after', Date.now() - t0, 'ms', await js(`document.querySelector('.sim-error')?.textContent ?? ''`));
await until(`!document.querySelector('.viewport').dataset.loading`, 'scene assets', 200).catch(() => console.log('no asset flag'));
const info = await js(`(() => { const c = document.querySelector('.viewport canvas'); const g = c.getContext('webgl2'); const e = g && g.getExtension('WEBGL_debug_renderer_info'); const v = document.querySelector('.viewport'); return JSON.stringify({ renderer: e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown', w: c.width, h: c.height, cssW: v.clientWidth, cssH: v.clientHeight, quality: v.dataset.quality ?? 'n/a', sceneMs: v.dataset.sceneMs ?? 'n/a' }); })()`);
console.log('gl', info);
const seek = f => js(`(() => { const s = document.querySelector('input[aria-label=Timeline]'); s.value = String(${f}); s.dispatchEvent(new Event('input', { bubbles: true })); })()`);
const box = await js(`(() => { const r = document.querySelector('.viewport').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })()`);
const settle = Number(arg('settle', '1500'));
if (has('fps')) {
  await js(`document.querySelector('.viewport').dataset.playing === 'false' && document.querySelector('[aria-label^="Play or pause (Space)"]').click()`);
  await seek(FRAMES[0]);
  await js(`document.querySelector('[aria-label^="Play or pause (Space)"]').click()`);
  const speed = arg('speed', '8');
  await js(`(() => { const s = document.querySelector('select[aria-label="Playback speed"]'); s.value = '${speed}'; s.dispatchEvent(new Event('change')); })()`);
  await wait(1500);
  const r = await js(`new Promise(done => { const ts = []; let last = performance.now(); const f0 = Number(document.querySelector('.viewport').dataset.frame); const step = now => { ts.push(now - last); last = now; if (ts.length < 240) requestAnimationFrame(step); else { const s = ts.slice(5).sort((a, b) => a - b); done(JSON.stringify({ fps: 1000 / (s.reduce((a, b) => a + b) / s.length), p50ms: s[s.length >> 1], p95ms: s[Math.floor(s.length * 0.95)], worstMs: s[s.length - 1], framesMoved: Number(document.querySelector('.viewport').dataset.frame) - f0, playing: document.querySelector('.viewport').dataset.playing, quality: document.querySelector('.viewport').dataset.quality ?? 'n/a' })); } }; requestAnimationFrame(step); })`);
  console.log('fps while playing', r);
}
const out = [];
const moveView = async () => {
  const drag = arg('drag', ''), wheel = Number(arg('wheel', '0'));
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  if (drag) {
    const [dx, dy] = drag.split(',').map(Number);
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: cx, y: cy });
    await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: cx, y: cy, button: 'left', buttons: 1, clickCount: 1 });
    for (let i = 1; i <= 8; i++) { await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: cx + (dx * i) / 8, y: cy + (dy * i) / 8, button: 'left', buttons: 1 }); await wait(30); }
    await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: cx + dx, y: cy + dy, button: 'left', buttons: 0, clickCount: 1 });
  }
  for (let i = 0; i < Math.abs(wheel); i++) { await send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: cx, y: cy, deltaX: 0, deltaY: Math.sign(wheel) * 240 }); await wait(30); }
};
let moved = false;
for (const f of FRAMES) {
  await seek(f);
  if (!moved) { moved = true; await wait(settle); await moveView(); }
  await wait(settle);
  await js(`new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))`);
  const state = await js(`(() => { const v = document.querySelector('.viewport'); return JSON.stringify({ frame: v.dataset.frame, robot: v.dataset.robot, drawn: v.dataset.drawnRobot ?? null }); })()`);
  console.log(f, state);
  out.push(state);
  await shot(`${OUT}-f${f}.png`);
  await shot(`${OUT}-f${f}-pane.png`, box);
}
const extra = arg('extra', '');
if (extra) console.log('extra', await js(extra));
if (problems.length) console.log('problems', [...new Set(problems)].slice(0, 20).join('\n'));
finish(0);
