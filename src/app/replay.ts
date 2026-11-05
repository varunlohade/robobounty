import load from '@mujoco/mujoco';
import type { Trial } from './trial.ts';

export type Xyz = [number, number, number];

let wasm: Promise<any> | null = null;
export const loadMujoco = () => (wasm ??= load());

// Holds the model and sets recorded states. It never calls mj_step: Python's MuJoCo version differs,
// so stepping here would not reproduce the recorded run.
export class Replay {
  mj: any; model: any; data: any;
  frame = -1;
  readonly frames: number;
  readonly version: string;

  constructor(mj: any, private trial: Trial) {
    this.mj = mj;
    this.model = mj.MjModel.from_xml_string(trial.xml);
    if (this.model.nq !== trial.manifest.nq) throw new Error(`model nq ${this.model.nq}, recorded nq ${trial.manifest.nq}`);
    this.data = new mj.MjData(this.model);
    this.frames = trial.manifest.frames;
    this.version = mj.mj_versionString();
  }

  static async open(trial: Trial): Promise<Replay> {
    return new Replay(await loadMujoco(), trial);
  }

  dispose() {
    this.data.delete();
    this.model.delete();
  }

  seek(frame: number) {
    const nq = this.trial.manifest.nq;
    this.frame = Math.max(0, Math.min(this.frames - 1, frame));
    this.data.qpos.set(this.trial.qpos.subarray(this.frame * nq, (this.frame + 1) * nq));
    this.mj.mj_forward(this.model, this.data);
  }

  bodyPos(name: string): Xyz {
    const id = this.mj.mj_name2id(this.model, this.mj.mjtObj.mjOBJ_BODY.value, name);
    const p = this.data.xpos, i = id * 3;
    return [p[i], p[i + 1], p[i + 2]];
  }

  /** Robot body position at every recorded frame, from the free joint in qpos. */
  path(): Float32Array {
    const { qpos, manifest } = this.trial;
    const j = this.mj.mj_name2id(this.model, this.mj.mjtObj.mjOBJ_JOINT.value, 'robot_free');
    const adr = this.model.jnt_qposadr[j];
    const out = new Float32Array(this.frames * 3);
    for (let f = 0; f < this.frames; f++) {
      const o = f * manifest.nq + adr;
      out[f * 3] = qpos[o]; out[f * 3 + 1] = qpos[o + 1]; out[f * 3 + 2] = qpos[o + 2];
    }
    return out;
  }
}
