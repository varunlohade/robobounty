// Plays a pack's replay in lab.html and compares the drawn pose with the recorded npz at 3 frames.
// node src/lab/tools/check_poses.mjs [--name plant] [--out DIR]. Needs vite on port 5199.
import { execFileSync } from 'node:child_process';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const NAME = arg('name', 'plant');
const TOLERANCE_M = 0.002;
const TOLERANCE_Q = 0.001; // Per quaternion component. The file rounds to 0.0001.
const dir = 'policy/packs/inspection/out';
let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };
const c = await openChrome();
try {
  await c.send('Page.navigate', { url: `http://localhost:5199/lab.html?poses=/${dir}/${NAME}.replay.json.gz` });
  await c.until(`document.querySelector('.viewport')?.dataset.ready === 'true'`, 'player ready', 30);
  await c.until(`Number(document.querySelector('.viewport').dataset.robotParts) > 0`, 'robot meshes', 20);
  await wait(1500);
  const f0 = await c.js(`Number(document.querySelector('.viewport').dataset.frame)`);
  await wait(800);
  const f1 = await c.js(`Number(document.querySelector('.viewport').dataset.frame)`);
  check('it plays', f1 > f0, `${f0} -> ${f1}`);
  check('the label has no Simulated tag', await c.js(`!document.querySelector('.sim-label')?.textContent.includes('Simulated')`));
  check('status bar has no Simulated tag', await c.js(`!document.querySelector('.lab-status').textContent.includes('Simulated')`));
  check('one canvas', await c.js(`document.querySelectorAll('.viewport canvas').length === 1`));

  const count = await c.js(`document.querySelector('.scrub input').max * 1 + 1`);
  const frames = [40, Math.floor(count / 2), count - 1];
  const times = await c.js(`(async () => { const b = new Uint8Array(await (await fetch('/${dir}/${NAME}.replay.json.gz')).arrayBuffer()); const t = b[0] === 0x1f ? await new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream('gzip'))).text() : new TextDecoder().decode(b); const d = JSON.parse(t); return JSON.stringify(${JSON.stringify(frames)}.map(f => d.frames[f].t)); })()`);
  const record = JSON.parse(execFileSync(join(ROOT, 'policy/.venv/bin/python'), ['-c', `
import json, numpy as np, sys
d = np.load(sys.argv[1], allow_pickle=True)
out = []
for t in json.loads(sys.argv[2]):
    i = int(np.argmin(np.abs(d['t'] - t)))
    out.append({'t': float(d['t'][i]), 'q': d['body_q'][i].tolist()})
print(json.dumps(out))`, join(ROOT, dir, `${NAME}.npz`), times], { encoding: 'utf8' }));
  for (const [n, f] of frames.entries()) {
    const drawn = JSON.parse(await c.js(`(() => {
      const app = window.__lab; app.jump(${f}); const v = app.view();
      const bodies = []; for (let i = 0; i < 17; i++) bodies.push(v.drawnBody(i));
      return JSON.stringify({ base: v.robot(), bodies, screen: v.robotOnScreen(), frame: v.frame });
    })()`));
    const q = record[n].q;
    const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const turn = (a, b) => { const sign = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3] < 0 ? -1 : 1; return Math.max(...a.map((v, k) => Math.abs(v - sign * b[k]))); };
    let worst = dist(drawn.base, q[0]), worstTurn = 0;
    for (let i = 0; i < 17; i++) {
      worst = Math.max(worst, dist(drawn.bodies[i].position, q[i]));
      worstTurn = Math.max(worstTurn, turn(drawn.bodies[i].quaternion, q[i].slice(3)));
    }
    check(`frame ${f} (t ${record[n].t.toFixed(2)} s) matches the record`, worst < TOLERANCE_M && worstTurn < TOLERANCE_Q, `worst ${(worst * 1000).toFixed(2)} mm, quaternion ${worstTurn.toFixed(5)} over 17 bodies`);
    check(`frame ${f}: every body draws a real mesh`, drawn.bodies.every(b => b.meshes > 0), drawn.bodies.map(b => b.meshes).join(','));
    check(`frame ${f}: the camera stays on the robot`, drawn.screen.inFrame, `screen ${drawn.screen.x.toFixed(2)}, ${drawn.screen.y.toFixed(2)}`);
  }
  await c.js(`window.__lab.jump(${Math.round((17.1 / (count / 25)) * count)})`);
  await wait(800);
  await c.shot(join(OUT, NAME === 'plant' ? 'poses-anymal.png' : `poses-${NAME}.png`));
  check('no console errors', c.problems.length === 0, [...new Set(c.problems)].slice(0, 8).join('\n'));
} catch (err) {
  check('finished', false, String(err));
} finally {
  c.close();
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 400);
