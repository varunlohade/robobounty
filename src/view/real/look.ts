import * as THREE from 'three';
import { HAZE } from './air.ts';

// The look: scenery only. It feeds nothing to physics. The run server validates it first, and this file checks it again, so only these typed values reach a shader.
export interface Look { building?: string; glass_tint?: string; frames?: string; time?: 'noon' | 'dusk' | 'night'; fog?: number; city?: 'default' | 'dubai' | 'generic_desert' | 'generic_coast'; rain?: boolean; snow?: boolean; dust_air?: boolean }

const HEX = /^#[0-9a-f]{6}$/i;

export function parseLook(raw: unknown): Look {
  const out: Look = {};
  if (typeof raw !== 'object' || raw === null) return out;
  const r = raw as Record<string, unknown>;
  for (const k of ['building', 'glass_tint', 'frames'] as const) { const v = r[k]; if (typeof v === 'string' && HEX.test(v)) out[k] = v; }
  if (r.time === 'noon' || r.time === 'dusk' || r.time === 'night') out.time = r.time;
  if (r.fog === 0 || r.fog === 1 || r.fog === 2 || r.fog === 3) out.fog = r.fog;
  if (r.city === 'default' || r.city === 'dubai' || r.city === 'generic_desert' || r.city === 'generic_coast') out.city = r.city;
  if (typeof r.rain === 'boolean') out.rain = r.rain;
  if (typeof r.snow === 'boolean') out.snow = r.snow;
  if (typeof r.dust_air === 'boolean') out.dust_air = r.dust_air;
  return out;
}

const rgb = (r: number, g: number, b: number) => new THREE.Color(r, g, b);
export const TIMES = {
  noon: { haze: HAZE.clone(), sun: rgb(1, 0.965, 0.92), sunLevel: 0.95, env: 0.85, flat: rgb(0.5, 0.54, 0.55), body: rgb(1.75, 1.75, 1.72), day: 1, lights: 0, rooms: 0, skyMix: 0, skyLow: rgb(1, 1, 1), skyHigh: rgb(1, 1, 1) },
  dusk: { haze: rgb(0.5, 0.27, 0.17), sun: rgb(1, 0.52, 0.27), sunLevel: 0.85, env: 0.55, flat: rgb(0.34, 0.24, 0.21), body: rgb(0.85, 0.6, 0.47), day: 0.4, lights: 0.75, rooms: 0.3, skyMix: 1, skyLow: rgb(1.5, 0.62, 0.24), skyHigh: rgb(0.16, 0.2, 0.46) },
  night: { haze: rgb(0.012, 0.017, 0.034), sun: rgb(0.6, 0.72, 1), sunLevel: 1.4, env: 0.32, flat: rgb(0.03, 0.036, 0.06), body: rgb(0.1, 0.11, 0.16), day: 0.05, lights: 2.2, rooms: 1, skyMix: 1, skyLow: rgb(0.022, 0.03, 0.07), skyHigh: rgb(0.003, 0.005, 0.016) },
};
export const CITIES = {
  default: { tint: rgb(1, 1, 1), ground: rgb(1, 1, 1), haze: rgb(1, 1, 1), lift: 1, shore: -1e9 },
  dubai: { tint: rgb(1.25, 1.08, 0.82), ground: rgb(3.6, 2.8, 1.8), haze: rgb(1.12, 0.98, 0.78), lift: 1.8, shore: -2300 },
  generic_desert: { tint: rgb(1.3, 1.05, 0.72), ground: rgb(5, 3.7, 2.1), haze: rgb(1.2, 0.98, 0.68), lift: 0.55, shore: -1e9 },
  generic_coast: { tint: rgb(1.05, 1.05, 1.08), ground: rgb(1, 1, 1), haze: rgb(0.84, 0.98, 1.14), lift: 0.8, shore: -760 },
};
export const FOG_THICKNESS = [1, 3.5, 9, 24];
// What the air does to the picture. Each multiplies the time of day, so a night stays dark. Scenery only.
export const AIR = {
  rain: { haze: rgb(0.62, 0.66, 0.72), fog: 4, skyFog: 0.75, sun: 0.4, city: rgb(0.8, 0.82, 0.85), ground: rgb(0.8, 0.82, 0.85) },
  snow: { haze: rgb(1.55, 1.6, 1.7), fog: 5, skyFog: 0.8, sun: 0.65, city: rgb(1.5, 1.55, 1.62), ground: rgb(4.5, 4.6, 4.8) },
  dust: { haze: rgb(1.55, 1.02, 0.56), fog: 8, skyFog: 0.92, sun: 0.5, city: rgb(1.12, 0.95, 0.72), ground: rgb(1.5, 1.15, 0.75) },
};

// A tint keeps its hue at any brightness, so a dark colour still reads as that colour on the glass.
export function tintOf(hex: string): THREE.Color {
  const c = new THREE.Color(hex);
  const top = Math.max(c.r, c.g, c.b, 1e-3);
  return top < 0.04 ? c.multiplyScalar(4) : c.multiplyScalar(1 / top);
}
export const luminance = (c: THREE.Color) => 0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b;
