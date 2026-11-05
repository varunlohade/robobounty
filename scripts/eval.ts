import load from '@mujoco/mujoco';
import fs from 'node:fs';
import { Episode, evaluate } from '../src/sim/core.ts';
import { BASELINE, FIXED, compile } from '../src/challenges/acme.ts';
const mj = await load();
const ep = new Episode(mj, fs.readFileSync('public/robots/acme-arm.xml', 'utf8'));
const seeds = Array.from({ length: 20 }, (_, i) => i + 1);
for (const [name, src] of [['baseline', BASELINE], ['fixed', FIXED]] as const) {
  const t0 = performance.now();
  const r = evaluate(ep, compile(src), seeds);
  console.log(name, 'success', (r.successRate * 100).toFixed(0) + '%', 'meanTime', r.meanTime, 'ms', Math.round(performance.now() - t0));
  const fails = r.runs.filter(x => !x.success).map(x => `${x.seed}:${x.reason}`);
  if (fails.length) console.log('  fails', fails.join(' | '));
}
