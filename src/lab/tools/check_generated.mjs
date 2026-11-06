// The whole generated-object path in lab.html with a saved model: typed words, one real AI call, the saved model, the robot's run against it, and the result beside the same world without it.
// node src/lab/tools/check_generated.mjs [--out DIR]. Needs vite on port 5199. It costs no GPU time: the model comes from the cache.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const SAY = arg('say', "add a rusty pump in the robot's path");
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

const port = await freePort();
const server = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port)], { stdio: 'ignore' });
for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers: { Origin: 'http://localhost:5199' } }); break; } catch { await wait(200); } }
const c = await openChrome();
const events = () => c.js(`(async () => { const base = window.__lab.grid().deps.base; const r = await fetch(base + '/events?since=0'); return r.text(); })()`);
try {
  await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?server=${port}` });
  await c.until(`document.getElementById('lab')?.dataset.server === 'up' && document.querySelector('.chat-plus')`, 'server up', 30);
  await c.js(`document.querySelector('.chat-plus').click()`);
  await c.until(`document.querySelector('.chat-menu-row[data-pack=inspection]')`, 'menu', 8);
  await c.js(`document.querySelector('.chat-menu-row[data-pack=inspection]').click()`);
  await c.until(`document.getElementById('lab')?.dataset.pack === 'inspection' && document.querySelector('.viewport')?.dataset.ready === 'true'`, 'inspection session', 30);
  await wait(800);
  await c.shot(join(OUT, 'generated-before.png'));
  await c.js(`(() => { const t = document.querySelector('.chat-input'); t.value = ${JSON.stringify(SAY)}; document.querySelector('.chat-send').click(); })()`);
  await c.until(`/Using the saved model|GPU server is off|did not come out right|refused/.test(document.querySelector('.chat-list').innerText)`, 'the model step', 240);
  const chat = () => c.js(`document.querySelector('.chat-list').innerText`);
  check('the chat says the model came from the cache, with no GPU', /Using the saved model of .*It needs no GPU/.test(await chat()), (await chat()).slice(-400));
  await c.until(`Number(document.querySelector('.viewport')?.dataset.frame ?? 0) > 5 || /stopped|refused/.test(document.querySelector('.chat-list').innerText)`, 'the run plays', 400);
  await c.until(`window.__lab.view()?.scene?.children.some(o => o.name.startsWith('generated:'))`, 'the GLB is drawn', 40);
  check('the view holds the textured GLB', true);
  const textured = await c.js(`(() => { let n = 0, maps = 0; window.__lab.view().scene.traverse(o => { if (o.isMesh && o.parent?.parent?.parent?.parent?.name?.startsWith('generated:') ) { n++; if (o.material.map) maps++; } }); return JSON.stringify({ n, maps }); })()`);
  check('the GLB has a texture map', JSON.parse(textured).maps > 0, textured);
  await wait(6000);
  await c.shot(join(OUT, 'generated-pump-walk.png'));
  await c.until(`/not reach|fell|stuck|did not|reached all/i.test(document.querySelector('.chat-list').innerText)`, 'the verdict', 60);
  const said = await chat();
  console.log(said.slice(-900));
  check('the run result changed from the clean run', !/reached all 3 waypoints/.test(said), said.slice(-300));
  check('no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 6).join('\n'));
  const last = await c.js(`document.querySelector('.scrub input').max * 1`);
  await c.js(`window.__lab.jump(${JSON.stringify(0)} + Math.round(${last} * 0.5))`);
  await wait(1200);
  await c.shot(join(OUT, 'generated-pump-hit.png'));
} catch (err) {
  check('finished', false, String(err));
} finally {
  c.close();
  server.kill();
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 400);
