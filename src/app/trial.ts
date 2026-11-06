// Reads one exported trial folder from public/trials/<id>/ (see policy/app_export.py).
import { lookOf, type Look } from '../view/real/look.ts';
import type { Failures } from './worlds_page.ts';

export interface Manifest {
  id: string; label: string; hz: number; nq: number; frames: number; python_mujoco: string;
  area: { x0: number; x1: number; z0: number; z1: number };
  friction: number; elements?: string[]; sim_sha256?: string; sim_label?: string;
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
  wind: number[]; dirt: Uint8Array; look?: Look; mocap?: number[][];
}

export const V5 = 'highrise.world.v5';
export const isV5 = (world: Record<string, unknown> | undefined) => world?.schema === V5;

// The world values the view and the rail read, from either schema.
export function worldFacts(world: Record<string, any> | undefined) {
  if (isV5(world)) {
    const w = world as Record<string, any>;
    return { wetness: w.weather.wetness, dirtLevel: w.area.dirt_level, steadyWind: w.wind.steady_ms, windDir: w.wind.dir_deg, suction: w.robot.suction_pa, leak: w.robot.seal_leak_mm2 };
  }
  const w = world ?? {};
  return { wetness: w.wetness, dirtLevel: w.dirt_level, steadyWind: w.steady_wind_ms, windDir: w.wind_dir_deg, suction: w.suction_pa, leak: w.seal_leak_mm2 };
}
export interface WorldRun {
  name: string; group: string; reason: string; seed: number; passed: boolean; failure: string | null;
  fired: Record<string, { t: number; value: number }>; time_s: number; coverage: number; min_pressure_pa: number;
  thumb: string[]; end: [number, number]; trial?: string | null; outcome?: string; index?: number; kind?: string; flaky?: boolean;
}
export interface WorldsData {
  total: number; count_reason: string; groups: { name: string; reason: string }[];
  not_tested: { factor: string; reason: string; source: string }[]; worlds: WorldRun[];
  chat: string; campaign: string; sim_sha256: string; campaign_seconds: number;
  requirements: { id: string; rule: string; severity: string; text: string }[];
  controls: { n: number; passed: number };
  failures: Failures; fix: { plain: string; [key: string]: unknown }; fix_summary: string; fix_log: string;
  fix_diff: { kind: 'add' | 'del' | 'same'; text: string }[];
}
export interface TrialEntry { id: string; label: string }

// A local file arrives in well under a second. Past this, the request is stuck, and it must not hold the chat's event queue.
const FETCH_DEADLINE_MS = 20_000;

async function get(url: string): Promise<Response> {
  const res = await fetch(url, { signal: AbortSignal.timeout(FETCH_DEADLINE_MS) });
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
  const world = JSON.parse(worldText);
  // A v5 world holds its own look. For an older world the look is scenery beside it, and an older export has no look.json, which means the default look.
  const look: Look = isV5(world) ? lookOf(world) : await fetch(`${base}/look.json`, { signal: AbortSignal.timeout(FETCH_DEADLINE_MS) }).then(r => (r.ok ? r.json() : {})).catch(() => ({}));
  const qpos = new Float64Array(q.frames.length * q.nq);
  q.frames.forEach((f: number[], i: number) => qpos.set(f, i * q.nq));
  return { manifest, xml, qpos, result, world, worldText, controller, trace, wind, dirt: new Uint8Array(dirt), look, mocap: q.mocap_frames };
}

export async function loadWorlds(): Promise<WorldsData> {
  return (await get('/trials/worlds.json')).json();
}
