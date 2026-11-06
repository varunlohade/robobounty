import * as THREE from 'three';
import { AIR_GLSL, HASH_GLSL, HAZE } from './air.ts';

// An invented city far below the tower, built in the browser from a fixed seed: no buildings from the real world and nothing to download.
// It follows the layout of policy/render/city.py so the app matches the film render. It is scenery. It feeds nothing back to the physics.
const BLOCK = 86, STREET = 16, AVENUE_EVERY = 5;
const PALETTE = [[0.3, 0.3, 0.3], [0.36, 0.35, 0.33], [0.22, 0.24, 0.26], [0.42, 0.41, 0.39], [0.17, 0.19, 0.21], [0.33, 0.3, 0.27], [0.48, 0.47, 0.45], [0.13, 0.15, 0.17]];
const HUBS = [[-340, -520, 170], [420, -880, 210], [-1150, -700, 190], [150, -1700, 230], [-700, -2100, 210], [1300, -1450, 170], [-1900, -1500, 180], [620, 620, 170], [-800, 500, 190]];

class Rng {
  constructor(private s: number) {}
  next() { this.s = (this.s + 0x6d2b79f5) | 0; let t = Math.imul(this.s ^ (this.s >>> 15), 1 | this.s); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }
  uni(a: number, b: number) { return a + (b - a) * this.next(); }
  normal() { return Math.sqrt(-2 * Math.log(1 - this.next())) * Math.cos(6.2831853 * this.next()); }
}

class Soup {
  p: number[] = []; n: number[] = []; uv: number[] = []; c: number[] = []; k: number[] = []; i: number[] = [];
  quad(a: number[], b: number[], c: number[], d: number[], uvs: number[], col: number[], kind: number) {
    const base = this.p.length / 3;
    const ux = b[0] - a[0], uy = b[1] - a[1], uz = b[2] - a[2], vx = d[0] - a[0], vy = d[1] - a[1], vz = d[2] - a[2];
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const l = Math.hypot(nx, ny, nz) || 1; nx /= l; ny /= l; nz /= l;
    this.p.push(...a, ...b, ...c, ...d);
    for (let j = 0; j < 4; j++) { this.n.push(nx, ny, nz); this.c.push(col[0], col[1], col[2]); this.k.push(kind); }
    this.uv.push(...uvs);
    this.i.push(base, base + 1, base + 2, base, base + 2, base + 3);
  }
  // Walls and a roof. No floor: nobody sees under a building.
  box(cx: number, cy: number, w: number, d: number, z0: number, z1: number, rot: number, col: number[], kind = 0, roofKind = 1) {
    const c = Math.cos(rot), s = Math.sin(rot), hw = w / 2, hd = d / 2;
    const P = (x: number, y: number, z: number) => [cx + c * x - s * y, cy + s * x + c * y, z];
    const pts = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]], lens = [w, d, w, d];
    const seed = (cx * 0.37 + cy * 0.73) % 97;
    for (let i = 0; i < 4; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[(i + 1) % 4];
      this.quad(P(x0, y0, z0), P(x1, y1, z0), P(x1, y1, z1), P(x0, y0, z1), [seed, z0, seed + lens[i], z0, seed + lens[i], z1, seed, z1], col, kind);
    }
    this.quad(P(-hw, -hd, z1), P(hw, -hd, z1), P(hw, hd, z1), P(-hw, hd, z1), [0, 0, w, 0, w, d, 0, d], col, roofKind);
  }
}

function tower(m: Soup, rng: Rng, cx: number, cy: number, w: number, d: number, h: number, rot: number, col: number[], near: boolean) {
  const r0 = rng.next();
  let kind = r0 < 0.45 ? 0 : r0 < 0.7 ? 0.2 : 0.4;
  if (h > 90) kind = rng.next() < 0.3 ? 0.2 : 0.4;
  const c = Math.cos(rot), s = Math.sin(rot);
  const at = (ox: number, oy: number) => [cx + c * ox - s * oy, cy + s * ox + c * oy];
  let z = 0, W = w, D = d;
  if (h > 45 && rng.next() < 0.5) {
    const pod = rng.uni(10, 22);
    m.box(cx, cy, w * 1.12, d * 1.12, 0, pod, rot, col.map(x => x * 1.15), 0);
    z = pod;
  }
  let tiers = 1;
  if (h > 60 && rng.next() < 0.55) tiers = rng.next() < 0.6 ? 2 : 3;
  for (let t = 0; t < tiers; t++) {
    const top = t === tiers - 1 ? h : z + (h - z) * rng.uni(0.45, 0.72);
    m.box(cx, cy, W, D, z, top, rot, col, kind);
    z = top;
    if (t < tiers - 1) { W *= rng.uni(0.62, 0.84); D *= rng.uni(0.62, 0.84); }
  }
  if (!near) return;
  const rc = col.map(x => x * 0.8), pw = 0.5;
  for (const [ox, oy, bw, bd] of [[0, D / 2 - pw / 2, W, pw], [0, -D / 2 + pw / 2, W, pw], [W / 2 - pw / 2, 0, pw, D], [-W / 2 + pw / 2, 0, pw, D]]) {
    const [bx, by] = at(ox, oy);
    m.box(bx, by, bw, bd, z, z + 1.1, rot, rc, 1);
  }
  const plant = 2 + Math.floor(rng.next() * 4);
  for (let i = 0; i < plant; i++) {
    const [bx, by] = at(rng.uni(-0.32, 0.32) * W, rng.uni(-0.32, 0.32) * D);
    m.box(bx, by, rng.uni(2, W * 0.32 + 2), rng.uni(2, D * 0.32 + 2), z, z + rng.uni(1.5, 5), rot, rc, 1);
  }
  if (rng.next() < 0.3) {
    const [bx, by] = at(rng.uni(-0.3, 0.3) * W, rng.uni(-0.3, 0.3) * D);
    m.box(bx, by, 4.5, 4.5, z + 3.2, z + 7.5, rot + 0.5, [0.2, 0.17, 0.14], 1);
  }
  if (h > 120) {
    const [bx, by] = at(0, 0);
    if (rng.next() < 0.5) m.box(bx, by, W * 0.55, D * 0.55, z, z + rng.uni(6, 14), rot, col, kind);
    else m.box(bx, by, 1.4, 1.4, z, z + rng.uni(14, 34), rot, [0.2, 0.2, 0.21], 1);
  }
}

function tree(m: Soup, rng: Rng, x: number, y: number) {
  const r = rng.uni(3, 5.2), g = rng.uni(0.07, 0.13), col = [g * 0.72, g, g * 0.62], zero = [0, 0, 0, 0, 0, 0, 0, 0];
  for (let i = 0; i < 6; i++) {
    const a0 = (i * Math.PI) / 3 + 0.4, a1 = ((i + 1) * Math.PI) / 3 + 0.4;
    const b0 = [x + r * Math.cos(a0), y + r * Math.sin(a0), 1], b1 = [x + r * Math.cos(a1), y + r * Math.sin(a1), 1];
    const t0 = [x + r * 0.6 * Math.cos(a0), y + r * 0.6 * Math.sin(a0), 1 + r * 0.75], t1 = [x + r * 0.6 * Math.cos(a1), y + r * 0.6 * Math.sin(a1), 1 + r * 0.75];
    m.quad(b0, b1, t1, t0, zero, col, 1);
    m.quad(t0, t1, [x, y, 1 + r], [x, y, 1 + r], zero, col, 1);
  }
}

// Cars stand in the streets. They stand still because nothing in the record moves them.
function cars(m: Soup, rng: Rng, cx: number, cy: number) {
  const tones = [[0.5, 0.5, 0.5], [0.08, 0.08, 0.09], [0.32, 0.33, 0.34], [0.62, 0.62, 0.6], [0.14, 0.16, 0.2], [0.25, 0.1, 0.09]];
  const e = BLOCK / 2 + STREET / 2;
  for (let side = 0; side < 2; side++) {
    for (let i = 0; i < 7; i++) {
      if (rng.next() < 0.45) continue;
      const lane = (rng.next() < 0.5 ? -1 : 1) * rng.uni(1.8, 5.5), along = rng.uni(-BLOCK / 2, BLOCK / 2), col = tones[Math.floor(rng.next() * tones.length)];
      const [x, y, w, d] = side === 0 ? [cx + along, cy + e + lane, 4.4, 1.9] : [cx + e + lane, cy + along, 1.9, 4.4];
      m.box(x, y, w, d, 0.25, 0.95, 0, col, 1, 2);
      m.box(x, y, w * 0.55, d * 0.86, 0.95, 1.45, 0, [col[0] * 0.25, col[1] * 0.25, col[2] * 0.28], 1, 2);
    }
  }
}

function layout(tcx: number, tcy: number, radius: number): Soup {
  const rng = new Rng(1307), m = new Soup();
  const pitch = BLOCK + STREET, n = Math.floor(radius / pitch) + 1;
  for (let ix = -n; ix <= n; ix++) {
    for (let iy = -n; iy <= n; iy++) {
      let ox = 0, oy = 0;
      for (let k = 0; k < Math.abs(ix); k++) if (k % AVENUE_EVERY === 0) ox += STREET * 0.9;
      for (let k = 0; k < Math.abs(iy); k++) if (k % AVENUE_EVERY === 0) oy += STREET * 0.9;
      let cx = ix * pitch + Math.sign(ix) * ox + tcx + 34, cy = iy * pitch + Math.sign(iy) * oy + tcy + 30;
      const r = Math.hypot(cx, cy);
      if (r > radius) continue;
      // The city behind the tower only shows past its corner, so it ends sooner.
      if (cy > 60 && r > Math.min(radius, 2200)) continue;
      const ang = r < 1800 ? 0 : 0.22;
      if (ang) { const ca = Math.cos(ang), sa = Math.sin(ang); [cx, cy] = [ca * cx - sa * cy, sa * cx + ca * cy]; }
      if (cx - tcx > -22 - BLOCK / 2 && cx - tcx < 24 + BLOCK / 2 && cy - tcy > -30 - BLOCK / 2 && cy - tcy < 38 + BLOCK / 2) continue;
      const near = r < 1100;
      const gc = rng.uni(0.15, 0.2);
      m.box(cx, cy, BLOCK, BLOCK, 0, 0.35, ang, [gc, gc, gc * 0.98], 1, 3);
      if (rng.next() < 0.05 && r > 200) {
        m.box(cx, cy, BLOCK - 6, BLOCK - 6, 0.35, 0.5, ang, [0.07, 0.1, 0.07], 1);
        const count = near ? 22 : 0;
        for (let i = 0; i < count; i++) tree(m, rng, cx + rng.uni(-38, 38), cy + rng.uni(-38, 38));
        continue;
      }
      const heat = HUBS.reduce((sum, [hx, hy, hh]) => sum + hh * Math.exp(-((cx - hx) ** 2 + (cy - hy) ** 2) / (2 * 300 ** 2)), 0);
      const pick = rng.next();
      const lots = r < 3000 ? (pick < 0.25 ? 1 : pick < 0.55 ? 2 : pick < 0.75 ? 3 : 4) : 2;
      for (let k = 0; k < lots; k++) {
        let lx: number, ly: number, w: number, d: number;
        if (lots === 1) { lx = 0; ly = 0; w = BLOCK * rng.uni(0.72, 0.92); d = BLOCK * rng.uni(0.72, 0.92); }
        else if (lots === 2) { lx = (k - 0.5) * BLOCK * 0.5; ly = rng.uni(-3, 3); w = BLOCK * rng.uni(0.36, 0.45); d = BLOCK * rng.uni(0.7, 0.92); }
        else { lx = ((k % 2) - 0.5) * BLOCK * 0.5; ly = (Math.floor(k / 2) - 0.5) * BLOCK * 0.5; w = BLOCK * rng.uni(0.32, 0.44); d = BLOCK * rng.uni(0.32, 0.44); }
        const c = Math.cos(ang), s = Math.sin(ang);
        const base = Math.exp(Math.log(26) + 0.55 * rng.normal());
        const h = Math.min(base + heat * rng.uni(0.25, 1), 270);
        const tint = rng.uni(0.8, 1.2), pal = PALETTE[Math.floor(rng.next() * PALETTE.length)];
        const col = [pal[0] * tint * (1 + rng.normal() * 0.05), pal[1] * tint, pal[2] * tint * (1 + rng.normal() * 0.05)];
        tower(m, rng, cx + c * lx - s * ly, cy + s * lx + c * ly, w, d, h, ang, col, near);
      }
      if (r < 620) {
        cars(m, rng, cx, cy);
        for (let edge = 0; edge < 4; edge++) {
          for (let t = -3; t < 4; t++) {
            if (rng.next() >= 0.55) continue;
            const e = BLOCK / 2 + 2.5, a = t * 12 + rng.uni(-2, 2), q = edge % 2 ? e : -e;
            const [tx, ty] = edge < 2 ? [a, q] : [q, a];
            tree(m, rng, cx + tx, cy + ty);
          }
        }
      }
    }
  }
  // The street plane, out past the haze.
  m.quad([-40000, -40000, -0.05], [40000, -40000, -0.05], [40000, 40000, -0.05], [-40000, 40000, -0.05], [0, 0, 0, 0, 0, 0, 0, 0], [0.055, 0.057, 0.06], 4);
  return m;
}

const cache = new Map<number, THREE.BufferGeometry>();
export function cityGeometry(tcx: number, tcy: number, radius: number): THREE.BufferGeometry {
  const key = Math.round(radius * 100) + tcx * 1e6 + tcy * 1e9;
  const hit = cache.get(key);
  if (hit) return hit;
  const m = layout(tcx, tcy, radius);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(m.p), 3));
  g.setAttribute('normal', new THREE.BufferAttribute(new Int8Array(m.n.map(v => Math.round(v * 127))), 3, true));
  g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(m.uv), 2));
  g.setAttribute('aColor', new THREE.BufferAttribute(new Uint8Array(m.c.map(v => Math.min(255, Math.round(Math.sqrt(v) * 255)))), 3, true));
  g.setAttribute('aKind', new THREE.BufferAttribute(new Uint8Array(m.k.map(v => Math.round(v * 40))), 1, false));
  g.setIndex(new THREE.BufferAttribute(new Uint32Array(m.i), 1));
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 60000);
  cache.set(key, g);
  return g;
}

export function cityMaterial(noise: { value: THREE.Texture | null }) {
  return new THREE.ShaderMaterial({
    toneMapped: true,
    uniforms: { uHaze: { value: HAZE }, uNoise: noise, uClipY: { value: 1e9 } },
    vertexShader: /* glsl */`
      attribute vec3 aColor; attribute float aKind;
      varying vec3 vW; varying vec3 vN; varying vec2 vUv2; varying vec3 vCol; varying float vKind;
      void main() { vW = position; vN = normal; vUv2 = uv; vCol = aColor * aColor; vKind = aKind / 40.0; gl_Position = projectionMatrix * viewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */`
      varying vec3 vW; varying vec3 vN; varying vec2 vUv2; varying vec3 vCol; varying float vKind;
      uniform float uClipY;
      ${AIR_GLSL}
      ${HASH_GLSL}
      // A periodic pulse, box-filtered over the pixel, so far windows settle to their average and do not shimmer.
      float pulseI(float x, float lo, float hi) { return floor(x) * (hi - lo) + clamp(fract(x), lo, hi) - lo; }
      float pulse(float x, float lo, float hi, float w) { w = max(w, 1e-4); return (pulseI(x + w * 0.5, lo, hi) - pulseI(x - w * 0.5, lo, hi)) / w; }
      const vec3 SUN = vec3(-0.46, -0.58, 0.67);
      void main() {
        if (vW.y > uClipY) discard;
        vec3 n = normalize(vN);
        vec3 alb;
        float gloss = 0.0;
        if (vKind < 0.5) {
          vec2 g = vUv2 / vec2(2.8, 3.6);
          vec2 fw = fwidth(g);
          float ribbon = step(0.1, vKind), curtain = step(0.3, vKind);
          float wu = mix(pulse(g.x, 0.16, 0.84, fw.x), 1.0, ribbon);
          float wv = pulse(g.y, mix(mix(0.22, 0.32, ribbon), 0.04, curtain), mix(0.82, 0.96, curtain), fw.y);
          float win = wu * wv;
          float detail = 1.0 - smoothstep(0.25, 0.8, max(fw.x, fw.y));
          float cell = mix(0.5, hash12(floor(g) + 3.0), detail);
          vec3 glass = vec3(0.9, 1.0, 1.08) * (0.05 + 0.035 * cell);
          float grime = texture2D(uNoise, vUv2 * vec2(0.012, 0.004)).r;
          vec3 wall = mix(vCol, vec3(0.08), 0.5 * smoothstep(0.35, 0.7, grime));
          alb = mix(wall, glass, win);
          gloss = win * (0.22 + 0.2 * curtain);
          // A few rooms have the lights on.
          alb += vec3(1.0, 0.82, 0.62) * 0.1 * step(0.985, cell) * win * detail;
        } else if (vKind > 3.5) {
          alb = vCol;
        } else if (vKind > 2.5) {
          alb = vCol * (0.75 + 0.5 * texture2D(uNoise, vW.xy / 60.0).r);
        } else if (vKind > 1.5) {
          alb = vCol;
          gloss = 0.1;
        } else {
          float r = smoothstep(0.3, 0.7, texture2D(uNoise, vW.xy / 34.0).r);
          if (n.z > 0.8) {
            // Roof membrane: seams, patches, puddle stains.
            vec2 sq = vW.xy / vec2(7.0, 5.3), sf = fwidth(sq);
            float seam = pulse(sq.x, 0.0, 0.05, sf.x) + pulse(sq.y, 0.0, 0.05, sf.y);
            float patch_ = smoothstep(0.52, 0.6, texture2D(uNoise, vW.xy / 11.0 + 0.3).g);
            alb = mix(vec3(0.15, 0.148, 0.14), vec3(0.27, 0.265, 0.25), r) * (1.0 - 0.14 * clamp(seam, 0.0, 1.0)) * (1.0 - 0.18 * patch_);
            if (vCol.g < 0.12) alb = vCol;
          } else {
            // Plant rooms: louvres.
            float lv = pulse(vUv2.y / 0.45, 0.0, 0.42, fwidth(vUv2.y / 0.45));
            alb = (vCol * 0.75 + 0.1) * (1.0 - 0.45 * lv);
          }
        }
        // Overcast light: bright from above, a little direction from the thin spot in the cloud, and dark canyons.
        float sky = 0.66 + 0.42 * n.z;
        float sun = max(dot(n, SUN), 0.0) * 0.42;
        float canyon = mix(0.42, 1.0, smoothstep(0.0, 34.0, vW.z)) ;
        vec3 col = alb * (sky + sun) * 1.42 * (n.z > 0.8 ? mix(0.7, 1.0, smoothstep(0.0, 8.0, vW.z)) : canyon);
        vec3 v = normalize(cameraPosition - vW);
        col += gloss * uHaze * (0.5 + 0.9 * pow(1.0 - max(dot(n, v), 0.0), 4.0));
        gl_FragColor = vec4(mix(col, uHaze, clamp(airAmount(vW, cameraPosition), 0.0, 1.0)), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}
