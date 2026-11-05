// Reads one exported trial folder from public/trials/<id>/ (see policy/app_export.py).
export interface Manifest {
  id: string; label: string; hz: number; nq: number; frames: number; python_mujoco: string;
  area: { x0: number; x1: number; z0: number; z1: number };
  friction: number;
  dirt: { nx: number; nz: number; every_steps: number; scale: number; clean_below: number; count: number };
}
export interface TrialResult {
  passed: boolean; failure: string | null; seed: number; time_s: number; coverage: number; steps: number;
  fired: Record<string, { t: number; value: number }>; [key: string]: unknown;
}
export interface Trial {
  manifest: Manifest; xml: string; qpos: Float64Array; result: TrialResult; world: Record<string, unknown>;
  worldText: string; controller: string;
  trace: { columns: string[]; rows: (string | number | null)[][] };
  wind: number[]; dirt: Uint8Array;
}
export interface WorldRun {
  name: string; group: string; reason: string; seed: number; passed: boolean; failure: string | null;
  fired: Record<string, { t: number; value: number }>; time_s: number; coverage: number; min_pressure_pa: number;
  thumb: string[]; end: [number, number]; trial: string | null; outcome?: string; index?: number;
}
export interface WorldsData {
  total: number; count_reason: string; groups: { name: string; reason: string }[];
  not_tested: { factor: string; reason: string; source: string }[]; worlds: WorldRun[];
}
export interface TrialEntry { id: string; label: string }

async function get(url: string): Promise<Response> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res;
}

export async function trialIndex(): Promise<TrialEntry[]> {
  return (await get('/trials/index.json')).json();
}

export const loadTrial = (id: string) => loadTrialFrom(`/trials/${encodeURIComponent(id)}`);

export async function loadTrialFrom(base: string): Promise<Trial> {
  const [manifest, xml, q, result, worldText, controller, trace, wind, dirt] = await Promise.all([
    get(`${base}/manifest.json`).then(r => r.json()),
    get(`${base}/model.xml`).then(r => r.text()),
    get(`${base}/qpos.json`).then(r => r.json()),
    get(`${base}/result.json`).then(r => r.json()),
    get(`${base}/world.json`).then(r => r.text()),
    get(`${base}/controller.py.txt`).then(r => r.text()),
    get(`${base}/trace.json`).then(r => r.json()),
    get(`${base}/wind.json`).then(r => r.json()),
    get(`${base}/dirt.bin`).then(r => r.arrayBuffer()),
  ]);
  const qpos = new Float64Array(q.frames.length * q.nq);
  q.frames.forEach((f: number[], i: number) => qpos.set(f, i * q.nq));
  return { manifest, xml, qpos, result, world: JSON.parse(worldText), worldText, controller, trace, wind, dirt: new Uint8Array(dirt) };
}

export async function loadWorlds(): Promise<WorldsData> {
  return (await get('/trials/worlds.json')).json();
}
