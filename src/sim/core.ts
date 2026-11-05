// Simulation core shared by the browser app and the node tests.
// One "episode" = one randomized attempt at the challenge task.

export type Vec3 = [number, number, number];

/** What a controller sees every control tick (50 Hz). */
export interface Obs {
  t: number;          // seconds since episode start
  cube: Vec3;         // cube centre, metres, world frame (z up)
  cubeYaw: number;    // cube rotation about z, radians
  grip: Vec3;         // point between the fingertips
  gripYaw: number;    // current finger axis angle about z, radians
  shelf: Vec3;        // centre of the shelf top surface
  holding: boolean;   // both fingers touch the cube
}

/** What a controller returns. The platform moves the gripper toward
 * `target` at a safe max speed and solves the joint angles (IK). */
export interface Action {
  target: Vec3;
  /** Finger axis angle about z (world), radians. Optional: default keeps the arm's natural angle. */
  yaw?: number;
  /** 1 = open, 0 = closed. */
  grip: number;
}

export type Controller = (obs: Obs) => Action;
export type ControllerFactory = () => Controller;

export interface EpisodeResult {
  seed: number;
  success: boolean;
  time: number | null;   // seconds until the cube rested on the shelf
  reason: string;
}

export interface Frame { t: number; qpos: Float64Array }

const DT_CONTROL = 0.02;
const EPISODE_SEC = 12;
const MAX_SPEED = 0.6;          // m/s for the commanded gripper point
const L1 = 0.25, L2 = 0.22, WR = 0.07;
const SHOULDER: Vec3 = [0.15, 0, 0.51];
const SHELF_TOP: Vec3 = [0.4, 0.22, 0.54];
const CUBE_HALF = 0.025;

export function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const wrapPi = (a: number) => Math.atan2(Math.sin(a), Math.cos(a));

/** Joint angles that put the fingertip point at p with the hand pointing down. */
export function ik(p: Vec3, yaw: number | undefined): number[] {
  const [x, y, z] = p;
  const base = Math.atan2(y - SHOULDER[1], x - SHOULDER[0]);
  const r = Math.hypot(x - SHOULDER[0], y - SHOULDER[1]);
  const h = z + WR - SHOULDER[2];
  let D = (r * r + h * h - L1 * L1 - L2 * L2) / (2 * L1 * L2);
  D = Math.max(-1, Math.min(1, D));
  const t2 = Math.acos(D);
  const t1 = Math.atan2(r, h) - Math.atan2(L2 * Math.sin(t2), L1 + L2 * Math.cos(t2));
  // Roll turns the finger axis away from the arm's own heading.
  // The hand points down, so a +roll turns the fingers by -roll about world z.
  const roll = yaw === undefined ? 0 : wrapPi(base - yaw);
  return [base, t1, t2, Math.PI - t1 - t2, roll];
}

type Mj = any;

export class Episode {
  mj: Mj; model: any; data: any;
  ids: { cube: number; grip: number; fingerL: number; fingerR: number; cubeGeom: number; cubeQ: number };
  seed = 0;
  cmd: Vec3 = [0.3, 0, 0.75];
  ctrlFn: Controller | null = null;
  t = 0;
  restSince: number | null = null;
  result: EpisodeResult | null = null;
  lastAction: Action = { target: [0.3, 0, 0.75], grip: 1 };

  constructor(mj: Mj, xml: string) {
    this.mj = mj;
    this.model = mj.MjModel.from_xml_string(xml);
    this.data = new mj.MjData(this.model);
    const id = (type: string, name: string) => mj.mj_name2id(this.model, mj.mjtObj[type].value, name);
    const cubeJnt = id('mjOBJ_JOINT', 'cube_free');
    this.ids = {
      cube: id('mjOBJ_BODY', 'cube'),
      grip: id('mjOBJ_SITE', 'grip'),
      fingerL: id('mjOBJ_GEOM', 'finger_l'),
      fingerR: id('mjOBJ_GEOM', 'finger_r'),
      cubeGeom: id('mjOBJ_GEOM', 'cube'),
      cubeQ: this.model.jnt_qposadr[cubeJnt],
    };
  }

  reset(seed: number, factory: ControllerFactory | null) {
    const { mj, model, data } = this;
    mj.mj_resetData(model, data);
    const rnd = mulberry32(seed * 9973 + 17);
    const x = 0.42 + rnd() * 0.16, y = -0.25 + rnd() * 0.17, yaw = (rnd() * 2 - 1) * (Math.PI / 4);
    const a = this.ids.cubeQ;
    data.qpos[a] = x; data.qpos[a + 1] = y; data.qpos[a + 2] = 0.4 + CUBE_HALF;
    data.qpos[a + 3] = Math.cos(yaw / 2); data.qpos[a + 4] = 0; data.qpos[a + 5] = 0; data.qpos[a + 6] = Math.sin(yaw / 2);
    mj.mj_forward(model, data);
    this.seed = seed; this.t = 0; this.restSince = null; this.result = null;
    this.cmd = this.gripPos();
    this.ctrlFn = factory ? factory() : null;
  }

  gripPos(): Vec3 { const s = this.data.site_xpos, i = this.ids.grip * 3; return [s[i], s[i + 1], s[i + 2]]; }
  cubePos(): Vec3 { const s = this.data.xpos, i = this.ids.cube * 3; return [s[i], s[i + 1], s[i + 2]]; }
  cubeQuat() { const q = this.data.xquat, i = this.ids.cube * 4; return [q[i], q[i + 1], q[i + 2], q[i + 3]]; }

  obs(): Obs {
    const q = this.cubeQuat();
    const cubeYaw = Math.atan2(2 * (q[0] * q[3] + q[1] * q[2]), 1 - 2 * (q[2] * q[2] + q[3] * q[3]));
    const qpos = this.data.qpos;
    const jBase = this.model.jnt_qposadr[this.mj.mj_name2id(this.model, this.mj.mjtObj.mjOBJ_JOINT.value, 'yaw')];
    const gripYaw = wrapPi(qpos[jBase] - qpos[jBase + 4]);
    return {
      t: this.t, cube: this.cubePos(), cubeYaw, grip: this.gripPos(), gripYaw,
      shelf: [SHELF_TOP[0], SHELF_TOP[1], SHELF_TOP[2]], holding: this.holding(),
    };
  }

  holding(): boolean {
    const c = this.data.contact; let l = false, r = false;
    try {
      for (let i = 0; i < this.data.ncon; i++) {
        const k = c.get(i); if (!k) continue;
        const g = [k.geom1, k.geom2];
        if (g.includes(this.ids.cubeGeom)) { if (g.includes(this.ids.fingerL)) l = true; if (g.includes(this.ids.fingerR)) r = true; }
      }
    } finally { c.delete(); }
    return l && r;
  }

  /** Advance one control tick (20 ms). Returns false when the episode is over. */
  tick(manual?: Action): boolean {
    if (this.result) return false;
    const { mj, model, data } = this;
    let act: Action = this.lastAction;
    try { act = manual ?? (this.ctrlFn ? this.ctrlFn(this.obs()) : this.lastAction); }
    catch (e) { this.finish(false, 'Controller crashed: ' + (e as Error).message); return false; }
    if (!act || !Array.isArray(act.target) || act.target.length !== 3 || act.target.some(v => !Number.isFinite(v))) {
      this.finish(false, 'Controller returned an invalid action'); return false;
    }
    this.lastAction = act;
    // Safety: clamp the workspace and the speed of the commanded point.
    const goal: Vec3 = [clamp(act.target[0], 0.2, 0.75), clamp(act.target[1], -0.45, 0.45), clamp(act.target[2], 0.405, 0.9)];
    const d = [0, 1, 2].map(k => goal[k] - this.cmd[k]); const n = Math.hypot(...d); const maxStep = MAX_SPEED * DT_CONTROL;
    if (n > maxStep) for (let k = 0; k < 3; k++) this.cmd[k] += d[k] * maxStep / n; else this.cmd = goal;
    const q = ik(this.cmd, act.yaw);
    const g = clamp(act.grip, 0, 1) * 0.035;
    for (let k = 0; k < 5; k++) data.ctrl[k] = q[k];
    data.ctrl[5] = g;
    const sub = Math.round(DT_CONTROL / model.opt.timestep);
    for (let i = 0; i < sub; i++) mj.mj_step(model, data);
    this.t += DT_CONTROL;
    this.judge(act);
    return !this.result;
  }

  judge(act: Action) {
    const c = this.cubePos(), q = this.cubeQuat();
    const upright = Math.abs(1 - 2 * (q[1] * q[1] + q[2] * q[2])) > 0.95;
    if (c[2] < 0.3) return this.finish(false, 'Cube fell off the table');
    const onShelf = Math.abs(c[0] - SHELF_TOP[0]) < 0.1 && Math.abs(c[1] - SHELF_TOP[1]) < 0.1 && c[2] > SHELF_TOP[2] && c[2] < SHELF_TOP[2] + 0.04;
    const released = act.grip > 0.5 && !this.holding();
    if (onShelf && upright && released) {
      if (this.restSince === null) this.restSince = this.t;
      if (this.t - this.restSince >= 0.5) return this.finish(true, 'Placed upright on the shelf', this.restSince);
    } else this.restSince = null;
    if (this.t >= EPISODE_SEC) this.finish(false, onShelf && !upright ? 'Cube on shelf but tipped over' : 'Ran out of time');
  }

  finish(success: boolean, reason: string, time: number | null = null) {
    this.result = { seed: this.seed, success, time: success ? round2(time ?? this.t) : null, reason };
  }

  run(seed: number, factory: ControllerFactory): EpisodeResult {
    this.reset(seed, factory);
    while (this.tick()) { /* step */ }
    return this.result!;
  }
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
const round2 = (v: number) => Math.round(v * 100) / 100;

/** Score a controller over N seeded episodes. */
export function evaluate(ep: Episode, factory: ControllerFactory, seeds: number[]) {
  const runs = seeds.map(s => ep.run(s, factory));
  const ok = runs.filter(r => r.success);
  const meanTime = ok.length ? round2(ok.reduce((a, r) => a + (r.time ?? 0), 0) / ok.length) : null;
  return { runs, successRate: ok.length / runs.length, meanTime };
}
