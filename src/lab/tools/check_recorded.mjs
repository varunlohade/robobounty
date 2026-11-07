// The recorded fallback in a real browser: pick a robot, list, play, grid, click a red square, replay, with no AI and no sim. No child process may start.
// node src/lab/tools/check_recorded.mjs [--out DIR] [--film]. Needs vite on port 5199 and policy/runs/demo. --film writes a short mp4 of each moving grid.
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const FILM = process.argv.includes('--film');
const FILM_FRAMES = 40, FILM_FPS = 8;
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

const port = await freePort();
const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port), '--recorded', join(ROOT, 'policy/runs/demo')], { stdio: 'ignore' });
const childrenNow = () => { try { return execFileSync('pgrep', ['-P', String(server.pid)], { encoding: 'utf8' }).trim().split('\n').filter(Boolean).length; } catch { return 0; } };
let peakChildren = 0;
const watcher = setInterval(() => { peakChildren = Math.max(peakChildren, childrenNow()); }, 200);
const headers = { Origin: 'http://localhost:5199' };
for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers }); break; } catch { await wait(200); } }

const c = await openChrome();
const box = sel => c.js(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
const clickOn = async sel => { const b = await box(sel); await c.click(b.x, b.y); };
const seen = () => c.js(`document.body.innerText`);
// How many squares change their picture across one second.
const moving = () => c.js(`(async () => {
  const sums = () => [...document.querySelectorAll('.sq canvas')].map(v => { const d = v.getContext('2d').getImageData(0, 0, v.width, v.height).data; let s = 0; for (let i = 0; i < d.length; i += 40) s = (s + d[i]) % 65521; return s; });
  const a = sums(); await new Promise(r => setTimeout(r, 1000)); const b = sums();
  return { changed: a.filter((v, i) => v !== b[i]).length, squares: a.length, pictured: document.querySelectorAll('.sq[data-picture]').length };
})()`);

async function filmGrid(name) {
  const dir = mkdtempSync(join(tmpdir(), 'grid-film-'));
  for (let i = 0; i < FILM_FRAMES; i++) {
    const r = await c.send('Page.captureScreenshot', { format: 'jpeg', quality: 80 });
    writeFileSync(join(dir, `f${String(i).padStart(4, '0')}.jpg`), Buffer.from(r.result.data, 'base64'));
    await wait(1000 / FILM_FPS);
  }
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(FILM_FPS), '-i', join(dir, 'f%04d.jpg'), '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-vf', 'scale=1280:-2', '-crf', '30', join(OUT, name)]);
  rmSync(dir, { recursive: true, force: true });
  console.log('MP4', join(OUT, name));
}

try {
  const health = await (await fetch(`http://127.0.0.1:${port}/api/health`, { headers })).json();
  check('the server says recorded, with no AI and no sim', /Recorded run, no AI and no sim/.test(health.llm), health.llm);
  await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?server=${port}` });
  await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus')`, 'server up', 30);
  for (const pack of ['inspection', 'window']) {
    await clickOn('.chat-plus');
    await c.until(`document.querySelectorAll('.chat-menu-row').length >= 3`, 'menu', 8);
    await clickOn(`.chat-menu-row[data-pack=${pack}]`);
    await c.until(`document.getElementById('lab')?.dataset.pack === ${JSON.stringify(pack)} && document.querySelector('.chat-test') && !document.querySelector('.chat-test').hidden && !document.querySelector('.grid-page')`, `${pack} session`, 30);
    check(`${pack}: Recorded run is on screen after the pick`, /Recorded run/.test(await seen()));
    await clickOn('.chat-test');
    await c.until(`document.querySelector('.chat-run')`, 'scenario list', 15);
    const card = await c.js(`document.querySelector('.chat-list-card').innerText`);
    check(`${pack}: the list comes with the recorded label and the guess note`, /Recorded run/.test(card) && /guess/i.test(card));
    await c.shot(join(OUT, `recorded-${pack}-list.png`));
    await clickOn('.chat-run');
    await c.until(`document.querySelector('.grid-page')?.dataset.zoom === 'done'`, 'grid opens', 30);
    check(`${pack}: the grid says Recorded run`, await c.js(`!document.querySelector('.grid-recorded').hidden && document.querySelector('.grid-recorded').innerText === 'Recorded run'`));
    await c.until(`document.querySelectorAll('.sq[data-picture]').length >= 8`, 'squares show pictures', 45);
    if (FILM) await filmGrid(`grid-video-${pack}.mp4`);
    await c.until(`document.querySelector('.grid-page').dataset.done === 'true'`, 'recorded campaign ends', 90);
    await c.until(`document.querySelectorAll('.sq[data-picture=film]').length === document.querySelectorAll('.sq:not([data-held=true])').length`, 'every run has its film', 20);
    const moved = await moving();
    check(`${pack}: squares move on screen`, moved.changed >= moved.pictured * 0.7 && moved.pictured > 0, JSON.stringify(moved));
    await c.shot(join(OUT, `grid-video-${pack}.png`));
    const red = await c.js(`document.querySelector('.sq[data-status=failed], .sq[data-status=stuck]')?.dataset.index ?? null`);
    check(`${pack}: a red square exists`, red !== null, String(red));
    await clickOn(`.sq[data-index="${red}"]`);
    await c.until(`document.querySelector('.grid-replay .viewport')?.dataset.ready === 'true' && Number(document.querySelector('.grid-replay .viewport').dataset.frame) > 0`, 'replay plays', 30);
    const rail = await c.js(`document.querySelector('.grid-rail').innerText`);
    check(`${pack}: the panel shows the judge's reason and the log`, rail.includes('Judge') && rail.includes('Last log lines'));
    check(`${pack}: no Simulated tag on screen`, !/Simulated/.test(await seen()));
    await wait(1500);
    await c.shot(join(OUT, `recorded-${pack}-replay.png`));
    await clickOn('.grid-back');
    await wait(300);
  }
  check('no child process started, so no sim and no AI', peakChildren === 0, `peak ${peakChildren}`);
  check('no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 8).join('\n'));
} catch (err) {
  check('finished', false, String(err));
  try { await c.shot(join(OUT, 'recorded-failure.png')); } catch {}
} finally {
  clearInterval(watcher);
  c.close();
  server.kill();
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 400);
