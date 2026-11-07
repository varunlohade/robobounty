// Headless check of lab.html: band sizes, canvas fit, playback, banned words, console errors.
// node src/lab/tools/check_lab_shell.mjs <screenshot.png> [--gl metal|swiftshader] [--trial id]
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const OUT = resolve(process.argv[2]);
const TRIAL = arg('trial', 'dubai-final-world-016');
const PORT = 9800 + Math.floor(Math.random() * 150);
const profile = mkdtempSync(join(tmpdir(), 'crashlab-lab-check-'));
const glFlags = arg('gl', 'metal') === 'metal'
  ? ['--use-angle=metal', '--enable-gpu', '--ignore-gpu-blocklist']
  : ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'];
const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,900',
  '--force-device-scale-factor=1', '--hide-scrollbars', '--mute-audio', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', ...glFlags, 'about:blank'], { stdio: 'ignore' });
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
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') problems.push(msg.params.args.map(a => a.value ?? a.description).join(' ').slice(0, 600));
  if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') problems.push(`${msg.params.entry.text} ${msg.params.entry.url ?? ''}`);
});
const send = (method, params = {}) => new Promise(r => { const n = id++; pending.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
const js = async expr => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result.exceptionDetails) throw new Error(`${expr}: ${JSON.stringify(r.result.exceptionDetails).slice(0, 500)}`);
  return r.result.result.value;
};

await send('Runtime.enable'); await send('Page.enable'); await send('Log.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
await send('Page.navigate', { url: `${arg('base', 'http://localhost:5199')}/lab.html?trial=${TRIAL}` });
let ready = false;
for (let i = 0; i < 600 && !ready; i++) {
  await wait(200);
  ready = await js(`document.querySelector('.viewport')?.dataset.ready === 'true' && !document.querySelector('.viewport').dataset.loading || !!document.querySelector('.sim-error')`);
}

const results = [];
const check = (name, ok, detail) => { results.push(ok); console.log(ok ? 'PASS' : 'FAIL', name, detail ?? ''); };
const rect = sel => js(`(() => { const e = document.querySelector('${sel}'); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; })()`);
const near = (a, b) => Math.abs(a - b) <= 1;

check('page ready, no error panel', ready && !(await js(`!!document.querySelector('.sim-error')`)));
for (const [sel, side, want] of [['.lab-title', 'h', 36], ['.sh-rail', 'w', 56], ['.chat', 'w', 380], ['.lab-tabs', 'h', 36], ['.player', 'h', 40], ['.lab-status', 'h', 24]]) {
  const r = await rect(sel);
  check(`${sel} ${side} ${want}`, !!r && near(r[side], want), JSON.stringify(r));
}
const chat = await rect('.chat'), main = await rect('.lab-main');
check('chat left of main', chat.x + chat.w <= main.x + 1 && near(chat.x, 56), `chat x ${chat.x}`);
const view = await rect('.viewport'), canvas = await rect('.viewport canvas'), tabs = await rect('.lab-tabs'), player = await rect('.player');
check('viewport fills between tab and player', near(view.y, tabs.y + tabs.h) && near(view.y + view.h, player.y) && near(view.w, main.w), JSON.stringify(view));
check('canvas fills viewport', ['x', 'y', 'w', 'h'].every(k => near(canvas[k], view[k])), JSON.stringify(canvas));
const gl = await js(`(() => { const c = document.querySelector('.viewport canvas'); const g = c.getContext('webgl2'); const e = g && g.getExtension('WEBGL_debug_renderer_info'); return JSON.stringify({ webgl2: !!g, renderer: e ? g.getParameter(e.UNMASKED_RENDERER_WEBGL) : 'unknown', w: c.width, h: c.height }); })()`);
check('WebGL2 canvas', JSON.parse(gl).webgl2, gl);

const state = () => js(`(() => { const d = document.querySelector('.viewport').dataset; return { frame: Number(d.frame), robot: d.robot, drawn: d.drawnRobot, playing: d.playing }; })()`);
const a = await state();
await wait(4000);
const b = await state();
check('playing moves the frame', b.frame > a.frame, `${a.frame} -> ${b.frame}`);
check('playing moves the robot', a.robot !== b.robot, `${a.robot} -> ${b.robot}`);
await js(`document.querySelector('[aria-label^="Play or pause"]').click()`);
await wait(300);
const c = await state();
await wait(800);
const d = await state();
check('pause holds the frame', c.playing === 'false' && c.frame === d.frame, `${c.frame} -> ${d.frame}`);
await js(`document.querySelector('[aria-label^="Play or pause"]').click()`);
await wait(1000);
const e = await state();
check('play resumes', e.frame > d.frame, `${d.frame} -> ${e.frame}`);

const text = await js(`document.body.innerText`);
const banned = text.match(/\b(fix|bounty|report|worlds|inspector)\b|controller\.py/gi);
check('no banned words on screen', !banned, banned?.join(', '));
check('replay label visible', await js(`(() => { const e = document.querySelector('.sim-label'); return !!e && e.offsetParent !== null && e.textContent === 'Replay of a recorded run.'; })()`));
check('rail hidden', await js(`document.querySelector('.rail').offsetParent === null`));
const scroll = await js(`document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight`);
check('no page overflow', scroll);
check('fonts loaded', await js(`document.fonts.ready.then(() => document.fonts.check('13px Inter') && document.fonts.check('12px "JetBrains Mono"'))`));

await wait(1500);
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(OUT, Buffer.from(shot.result.data, 'base64'));
console.log('wrote', OUT);
check('no console errors', problems.length === 0, [...new Set(problems)].slice(0, 12).join('\n'));
const failed = results.filter(r => !r).length;
console.log(failed ? `${failed} failed` : 'all passed');
finish(failed ? 1 : 0);
