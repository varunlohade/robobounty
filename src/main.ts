import load from '@mujoco/mujoco';
import { Episode } from './sim/core.ts';
import { Scene3D } from './view/scene3d.ts';
import { BASELINE, FIXED, compile } from './challenges/acme.ts';

const hud = document.getElementById('hud')!;
const mj = await load();
const xml = await (await fetch('/robots/acme-arm.xml')).text();
const ep = new Episode(mj, xml);
const view = new Scene3D(document.getElementById('view')!, ep.model);
const ctrls = { baseline: compile(BASELINE), fixed: compile(FIXED) };
let which: 'baseline' | 'fixed' = 'baseline', seed = 9;
ep.reset(seed, ctrls[which]);
addEventListener('keydown', e => {
  if (e.key === 'b' || e.key === 'f') { which = e.key === 'b' ? 'baseline' : 'fixed'; ep.reset(seed, ctrls[which]); }
  if (e.key === 'n') { seed++; ep.reset(seed, ctrls[which]); }
});
let acc = 0, last = performance.now();
function frame(now: number) {
  acc += Math.min(0.1, (now - last) / 1000); last = now;
  while (acc >= 0.02) { if (!ep.tick()) { /* hold last pose */ } acc -= 0.02; }
  view.sync(ep.data);
  hud.textContent = `controller: ${which}  (b / f to switch, n = next cube)\nrun #${seed}  t=${ep.t.toFixed(1)}s\n${ep.result ? (ep.result.success ? '✓ ' : '✗ ') + ep.result.reason : 'running…'}`;
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
