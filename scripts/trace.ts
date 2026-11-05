import load from '@mujoco/mujoco';
import fs from 'node:fs';
import { Episode } from '../src/sim/core.ts';
import { FIXED, compile } from '../src/challenges/acme.ts';
const mj = await load();
const ep = new Episode(mj, fs.readFileSync('public/robots/acme-arm.xml', 'utf8'));
const f = compile(FIXED);
ep.reset(1, f);
const fx = (v: number[]) => v.map(x => x.toFixed(3)).join(',');
for (let i = 0; i < 600 && ep.tick(); i++) if (i % 25 === 0) { const o = ep.obs(); console.log(o.t.toFixed(2), 'grip', fx(o.grip), 'cmd', fx(ep.cmd), 'tgt', fx(ep.lastAction.target), 'cube', fx(o.cube), 'hold', o.holding); }
console.log(ep.result);
ep.reset(1, f);
for (let i = 0; i < 175; i++) ep.tick();
const qa = (n: string) => ep.model.jnt_qposadr[mj.mj_name2id(ep.model, mj.mjtObj.mjOBJ_JOINT.value, n)];
for (const [k, n] of ['yaw', 'shoulder', 'elbow', 'wrist', 'roll', 'finger_l'].entries()) console.log(n, 'q', ep.data.qpos[qa(n)].toFixed(3), 'ctrl', ep.data.ctrl[k].toFixed(3));
