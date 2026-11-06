// The blueprint build effect in lab.html, for both robots and a new object: frames at each stage, frame rate, no replay on reload, nothing left behind.
// node src/lab/tools/check_blueprint.mjs [--out DIR] [--only window|inspection]. Needs vite on port 5199. It starts its own servers on free ports and stored AI replies, so no paid call.
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/blueprint')));
const ONLY = arg('only', null);
mkdirSync(OUT, { recursive: true });
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail !== '' ? `: ${detail}` : ''}`); };

const VIEW = `window.__lab.view()`;
const COUNT_FRAMES = `(() => { const f = window.__fps = { times: [], on: true }; const tick = t => { if (!f.on) return; f.times.push(t); requestAnimationFrame(tick); }; requestAnimationFrame(tick); })()`;
const READ_FRAMES = `(() => { const f = window.__fps; f.on = false; const d = f.times.slice(1).map((t, i) => t - f.times[i]); const total = f.times.at(-1) - f.times[0]; return JSON.stringify({ fps: Math.round((d.length / total) * 10000) / 10, frames: d.length, worstMs: Math.round(Math.max(...d)), over25: d.filter(x => x > 25).length, seconds: Math.round(total / 100) / 10 }); })()`;
const SCENE_STATE = `(() => { const v = ${VIEW}; let lines = 0, clipped = 0, meshes = 0; v.scene.traverse(o => { if (o.isLineSegments2) lines++; if (o.isMesh) { meshes++; const m = o.material; if (m && m.clippingPlanes && m.clippingPlanes.length) clipped++; } }); return JSON.stringify({ lines, clipped, meshes, local: v.renderer.localClippingEnabled, cam: [...v.camera.position.toArray(), ...v.controls.target.toArray()].map(n => Number(n.toFixed(3))), geometries: v.renderer.info.memory.geometries }); })()`;

// One still at each named moment, with the effect's clock held.
async function stages(c, tag, moments) {
  for (const [name, t] of moments) {
    await c.js(`${VIEW}.builds[0].hold = ${t}`);
    await wait(350);
    await c.shot(join(OUT, `${tag}-${name}.png`));
  }
  await c.js(`${VIEW}.builds[0] && (${VIEW}.builds[0].hold = null)`);
}

// Films the effect as it really runs, from the moment it starts until it ends, with a still at each named moment.
async function film(c, tag, moments) {
  const dir = join(tmpdir(), `blueprint-${tag}-${process.pid}`);
  mkdirSync(dir, { recursive: true });
  const t0 = Date.now(), left = [...moments];
  let n = 0;
  while (await c.js(`Boolean(document.querySelector('.viewport')?.dataset.build)`)) {
    const r = await c.send('Page.captureScreenshot', { format: 'png' });
    const t = (Date.now() - t0) / 1000;
    const png = Buffer.from(r.result.data, 'base64');
    writeFileSync(join(dir, `f${String(n++).padStart(4, '0')}.png`), png);
    while (left.length && t >= left[0][1]) { writeFileSync(join(OUT, `${tag}-${left.shift()[0]}.png`), png); }
  }
  const seconds = (Date.now() - t0) / 1000;
  console.log(`${tag}: filmed ${n} frames over ${seconds.toFixed(1)} s`);
  spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-framerate', String(n / seconds), '-i', join(dir, 'f%04d.png'), '-vf', 'crop=1004:800:436:72', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', join(OUT, `${tag}.mp4`)]);
  rmSync(dir, { recursive: true, force: true });
}

async function windowRobot() {
  const port = await freePort();
  const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port), '--recorded', join(ROOT, 'policy/runs/builder')], { stdio: 'ignore' });
  for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers: { Origin: 'http://localhost:5199' } }); break; } catch { await wait(200); } }
  const c = await openChrome();
  const say = text => c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(text)}; document.querySelector('.chat-send').click(); })()`);
  try {
    await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?server=${port}` });
    await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-input')`, 'server up', 30);
    // First, free of any held clock, the frame rate.
    await say('make the tower 200 m tall');
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'first'`, 'first build starts', 60);
    await c.js(COUNT_FRAMES);
    await c.until(`!document.querySelector('.viewport')?.dataset.build`, 'first build ends', 30);
    console.log('window fps', await c.js(READ_FRAMES));
    await c.js(`(() => { const v = ${VIEW}; const f = () => { if (window.__busy) { v.dirty = true; requestAnimationFrame(f); } }; window.__busy = true; f(); })()`);
    await c.js(COUNT_FRAMES);
    await wait(3000);
    await c.js(`window.__busy = false`);
    console.log('window fps with no effect', await c.js(READ_FRAMES));
    await c.js(`sessionStorage.clear()`);
    await c.send('Page.reload');
    await wait(1000);
    await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-input')`, 'server up', 30);
    await say('make the tower 200 m tall');
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'first'`, 'first build starts', 60);
    await c.js(COUNT_FRAMES);
    const before = JSON.parse(await c.js(SCENE_STATE));
    const hash = await c.js(`document.querySelector('.viewport').dataset.hash`);
    await film(c, 'window', [['1-lines', 1.05], ['2-blueprint', 2.85], ['3-city', 3.85], ['4-wall', 4.75], ['5-robot', 6.15]]);
    await wait(300);
    await c.shot(join(OUT, 'window-6-end.png'));
    const after = JSON.parse(await c.js(SCENE_STATE));
    check('window: nothing left behind', after.lines === 0 && after.clipped === 0 && !after.local, JSON.stringify(after));
    // A run that lands during the effect is a new view whose camera follows the robot, and it may carry a new hash.
    if (!(await c.js(`document.querySelector('.viewport').dataset.tid ?? ''`))) {
      check('window: camera did not move', JSON.stringify(after.cam) === JSON.stringify(before.cam), `${before.cam} -> ${after.cam}`);
      check('window: the hash did not change', (await c.js(`document.querySelector('.viewport').dataset.hash`)) === hash);
    } else console.log('window: a run landed during the effect, and it ended at once');
    // Wait for the run, then the antenna on the roof.
    await c.until(`document.querySelector('.viewport')?.dataset.tid`, 'the run', 240);
    await c.until(`document.querySelector('.chat-send') && !document.querySelector('.chat-send').disabled && document.getElementById('lab').dataset.idle >= 1`, 'idle', 120);
    await c.js(`${VIEW}.frameOn([20, -12, 195, 40, 0, 215])`);
    await wait(1800);
    await say('add an antenna on the roof');
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'object'`, 'object build starts', 90);
    await c.js(`${VIEW}.builds[0].hold = 0.4`);
    const names = await c.js(`Object.keys(${VIEW}.drawnScene().geoms).filter(n => n.includes('antenna')).map(n => ${VIEW}.drawnScene().geoms[n])`);
    const box = [Math.min(...names.map(b => b[0])), Math.min(...names.map(b => b[1])), Math.min(...names.map(b => b[2])), Math.max(...names.map(b => b[3])), Math.max(...names.map(b => b[4])), Math.max(...names.map(b => b[5]))];
    console.log('antenna box', JSON.stringify(box));
    await c.js(`${VIEW}.frameOn(${JSON.stringify(box)})`);
    await wait(1800);
    const cam = JSON.parse(await c.js(SCENE_STATE)).cam;
    await stages(c, 'antenna', [['1-lines', 0.4], ['2-blueprint', 0.8], ['3-reveal', 1.2]]);
    await c.until(`!document.querySelector('.viewport')?.dataset.build`, 'object build ends', 10);
    await wait(300);
    await c.shot(join(OUT, 'antenna-4-end.png'));
    const end = JSON.parse(await c.js(SCENE_STATE));
    check('antenna: nothing left behind', end.lines === 0 && end.clipped === 0 && !end.local, JSON.stringify(end));
    check('antenna: camera did not move', JSON.stringify(end.cam) === JSON.stringify(cam));
    // A solid new object shows first in the run that tests it, with the camera on the robot.
    await c.js(`${VIEW}.backToRobot()`);
    const shownTid = await c.js(`document.querySelector('.viewport').dataset.tid`);
    await say("put a big box in the robot's path");
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'object' || (document.querySelector('.viewport')?.dataset.tid && document.querySelector('.viewport').dataset.tid !== ${JSON.stringify(shownTid)})`, 'the box builds', 240);
    await stages(c, 'box', [['1-lines', 0.5], ['2-blueprint', 0.8], ['3-reveal', 1.2]]);
    await wait(1200);
    await c.shot(join(OUT, 'box-4-end.png'));
    await c.send('Page.reload');
    await wait(1500);
    await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true' || document.querySelector('.viewport')?.dataset.tid`, 'reload shows the world', 60);
    await wait(2000);
    check('window: a reload does not build again', (await c.js(`document.querySelector('.viewport').dataset.buildsRun ?? ''`)) === '');
    check('window: no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 5).join('\n'));
  } catch (err) {
    check('window finished', false, String(err));
    await c.shot(join(OUT, 'window-failed.png'));
  } finally { c.close(); server.kill(); }
}

async function fps(page) {
  // A clean run with nothing holding the clock.
  const port = await freePort();
  const server = spawn(process.execPath, [join(ROOT, 'src/lab/tools/fake_lab_server.mjs'), '--port', String(port)], { stdio: 'ignore' });
  for (let i = 0; i < 50; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`); break; } catch { await wait(100); } }
  return { port, server, page };
}

async function inspection() {
  const { port, server } = await fps();
  const c = await openChrome();
  try {
    await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?server=${port}` });
    await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus')`, 'server up', 30);
    await c.js(`document.querySelector('.chat-plus').click()`);
    await c.until(`document.querySelector('.chat-menu-row[data-pack=inspection]')`, 'menu', 8);
    await c.js(`document.querySelector('.chat-menu-row[data-pack=inspection]').click()`);
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'first'`, 'first build starts', 60);
    await c.js(COUNT_FRAMES);
    const before = JSON.parse(await c.js(SCENE_STATE));
    await c.until(`!document.querySelector('.viewport')?.dataset.build`, 'first build ends', 30);
    console.log('inspection fps', await c.js(READ_FRAMES));
    // The same view, drawing every frame with no effect: this machine's rate right now, to read the number above against.
    await c.js(`(() => { const v = ${VIEW}; const f = () => { if (window.__busy) { v.dirty = true; requestAnimationFrame(f); } }; window.__busy = true; f(); })()`);
    await c.js(COUNT_FRAMES);
    await wait(3000);
    await c.js(`window.__busy = false`);
    console.log('inspection fps with no effect', await c.js(READ_FRAMES));
    const after = JSON.parse(await c.js(SCENE_STATE));
    check('inspection: nothing left behind', after.lines === 0 && after.clipped === 0 && !after.local, JSON.stringify(after));
    check('inspection: camera did not move', JSON.stringify(after.cam) === JSON.stringify(before.cam));
    await c.send('Page.reload');
    await wait(1500);
    await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true'`, 'reload', 60);
    check('inspection: a reload does not build again', (await c.js(`document.querySelector('.viewport').dataset.buildsRun ?? ''`)) === '');
    await c.js(`sessionStorage.clear()`);
    await c.js(`sessionStorage.setItem('crashlab-pack', 'inspection')`);
    await c.send('Page.reload');
    await wait(800);
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'first'`, 'a new session builds', 60);
    await film(c, 'plant', [['1-lines', 1.35], ['2-blueprint', 2.85], ['3-reveal', 3.95], ['4-reveal', 5.25], ['5-small', 6.45]]);
    await wait(300);
    await c.shot(join(OUT, 'plant-6-end.png'));
    await c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = 'add an antenna mast'; document.querySelector('.chat-send').click(); })()`);
    await c.until(`document.querySelector('.viewport')?.dataset.build === 'object'`, 'object build starts', 30);
    await stages(c, 'plant-antenna', [['1-lines', 0.45], ['2-blueprint', 0.8], ['3-reveal', 1.2]]);
    await c.until(`!document.querySelector('.viewport')?.dataset.build`, 'object build ends', 10);
    await wait(300);
    await c.shot(join(OUT, 'plant-antenna-4-end.png'));
    const end = JSON.parse(await c.js(SCENE_STATE));
    check('plant antenna: nothing left behind', end.lines === 0 && end.clipped === 0 && !end.local, JSON.stringify(end));
    check('inspection: no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 5).join('\n'));
  } catch (err) {
    check('inspection finished', false, String(err));
    await c.shot(join(OUT, 'plant-failed.png'));
  } finally { c.close(); server.kill(); }
}

if (ONLY !== 'window') await inspection();
if (ONLY !== 'inspection') await windowRobot();
console.log(failed ? `${failed} FAILED` : 'ALL PASS');
process.exit(failed ? 1 : 0);
