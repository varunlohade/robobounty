import * as THREE from 'three';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';

// The window robot, at the sim's sizes: a 0.36 m square, chassis 0.02 to 0.10 m off the glass, tracks on the MJCF's roller lines,
// pad at the sim's PAD_X. Local z points out of the glass, as in the MJCF, so the recorded pose applies unchanged. It follows policy/render/scene.py.
const S = 0.36, R = 0.052, ZLO = 0.02, ZTOP = 0.1;
type Pt = [number, number, number];

function roundedRing(side: number, radius: number, z: number, corner = 12): Pt[] {
  const half = side / 2, r = Math.min(radius, half), out: Pt[] = [];
  for (const [cx, cy, a0] of [[half - r, half - r, 0], [-half + r, half - r, 90], [-half + r, -half + r, 180], [half - r, -half + r, 270]]) {
    for (let i = 0; i <= corner; i++) {
      const a = ((a0 + (90 * i) / corner) * Math.PI) / 180;
      out.push([cx + r * Math.cos(a), cy + r * Math.sin(a), z]);
    }
  }
  return out;
}

function loft(rings: Pt[][], closeTop = true): THREE.BufferGeometry {
  const n = rings[0].length, v: number[] = [], f: number[] = [];
  for (const ring of rings) for (const p of ring) v.push(...p);
  for (let k = 0; k < rings.length - 1; k++) {
    for (let i = 0; i < n; i++) {
      const a = k * n + i, b = k * n + (i + 1) % n;
      f.push(a, b, b + n, a, b + n, a + n);
    }
  }
  if (closeTop) {
    const c = v.length / 3, top = (rings.length - 1) * n;
    v.push(0, 0, rings[rings.length - 1][0][2]);
    for (let i = 0; i < n; i++) f.push(top + i, top + (i + 1) % n, c);
  }
  return finish(v, f);
}

function finish(v: number[], f: number[], flat = false): THREE.BufferGeometry {
  let g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
  g.setIndex(f);
  if (flat) g = g.toNonIndexed();
  g.computeVertexNormals();
  // Planar uv in metres for wear maps, and a vertex colour that soils the low parts of the body.
  const pos = g.attributes.position, uv = new Float32Array(pos.count * 2), col = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const z = pos.getZ(i), t = Math.min(1, Math.max(0, (z - 0.03) / 0.055)), shade = 0.62 + 0.38 * t;
    uv[i * 2] = pos.getX(i) + z * 0.7; uv[i * 2 + 1] = pos.getY(i) + z * 0.7;
    col[i * 3] = shade; col[i * 3 + 1] = shade; col[i * 3 + 2] = shade * 0.985;
  }
  g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  return g;
}

function box(x0: number, y0: number, z0: number, x1: number, y1: number, z1: number): THREE.BufferGeometry {
  const v = [x0, y0, z0, x1, y0, z0, x1, y1, z0, x0, y1, z0, x0, y0, z1, x1, y0, z1, x1, y1, z1, x0, y1, z1];
  const f = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6, 3, 0, 4, 3, 4, 7];
  return finish(v, f, true);
}

function fillet(z0: number, z1: number, i0: number, i1: number, seg: number): [number, number][] {
  const out: [number, number][] = [];
  for (let k = 0; k <= seg; k++) {
    const t = (k / seg) * (Math.PI / 2);
    out.push([i0 + (i1 - i0) * (1 - Math.cos(t)), z0 + (z1 - z0) * Math.sin(t)]);
  }
  return out;
}

// A belt with cross tread every 12 mm, swept across y.
function track(yc: number, width: number, halfLen: number, radius: number, zc: number): THREE.BufferGeometry {
  const path: [number, number][] = [];
  const seg = 14;
  for (const [cx, a0] of [[halfLen, -90], [-halfLen, 90]]) {
    for (let i = 0; i <= seg; i++) {
      const a = ((a0 + (180 * i) / seg) * Math.PI) / 180;
      path.push([cx + radius * Math.cos(a), zc + radius * Math.sin(a)]);
    }
  }
  // Resample the loop every 3 mm and push the lugs out.
  const pts: [number, number][] = [];
  const step = 0.003;
  let carry = 0, s = 0;
  for (let i = 0; i < path.length; i++) {
    const a = path[i], b = path[(i + 1) % path.length], l = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const nx = (b[1] - a[1]) / l, nz = -(b[0] - a[0]) / l;
    for (let d = carry; d < l; d += step) {
      const lug = Math.floor(s / 0.003) % 4 < 2 ? 0.0016 : 0;
      pts.push([a[0] + ((b[0] - a[0]) * d) / l + nx * lug, a[1] + ((b[1] - a[1]) * d) / l + nz * lug]);
      s += step;
      carry = d + step - l;
    }
  }
  const n = pts.length, v: number[] = [], f: number[] = [];
  for (const y of [yc - width / 2, yc + width / 2]) for (const [x, z] of pts) v.push(x, y, z);
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    f.push(i, i + n, j + n, i, j + n, j);
  }
  const c0 = v.length / 3; v.push(0, yc - width / 2, zc);
  const c1 = v.length / 3; v.push(0, yc + width / 2, zc);
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    f.push(c0, i, j, c1, j + n, i + n);
  }
  return finish(v, f, true);
}

function lathe(profile: [number, number][], seg = 28): THREE.BufferGeometry {
  const v: number[] = [], f: number[] = [];
  for (const [r, z] of profile) for (let i = 0; i < seg; i++) { const a = (2 * Math.PI * i) / seg; v.push(r * Math.cos(a), r * Math.sin(a), z); }
  for (let k = 0; k < profile.length - 1; k++) for (let i = 0; i < seg; i++) {
    const a = k * seg + i, b = k * seg + (i + 1) % seg;
    f.push(a, b, b + seg, a, b + seg, a + seg);
  }
  return finish(v, f);
}

function wearTextures(renderer: THREE.WebGLRenderer) {
  // Scuffs and blotches on the plastic, tiled every 40 cm. R is the colour, G the roughness.
  const size = 512, data = new Uint8Array(size * size * 4), roughData = new Uint8Array(size * size * 4);
  let seed = 991;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const lat = new Float32Array(64 * 64).map(() => rnd());
  const noise = (x: number, y: number, per: number) => {
    const xi = Math.floor(x), yi = Math.floor(y); let fx = x - xi, fy = y - yi;
    fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy);
    const at = (a: number, b: number) => lat[((a % per) + per) % per * 64 + ((b % per) + per) % per];
    return (at(xi, yi) * (1 - fx) + at(xi + 1, yi) * fx) * (1 - fy) + (at(xi, yi + 1) * (1 - fx) + at(xi + 1, yi + 1) * fx) * fy;
  };
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    const u = x / size, v = y / size;
    const blot = 0.4 * noise(u * 16, v * 16, 16) + 0.35 * noise(u * 32, v * 32, 32) + 0.25 * noise(u * 63, v * 63, 63);
    const scuff = noise(u * 4, v * 64, 64) > 0.78 ? 1 : 0;
    const speck = rnd() > 0.992 ? 1 : 0;
    const soil = Math.min(1, Math.max(0, (blot - 0.42) / 0.26));
    const c = 255 * (1 - 0.07 * soil - 0.05 * scuff - 0.2 * speck);
    const rough = 255 * (0.48 + 0.3 * soil + 0.18 * scuff), at = (y * size + x) * 4;
    data.set([c, c, c, 255], at);
    roughData.set([rough, rough, rough, 255], at);
  }
  const make = (bytes: Uint8Array) => {
    const tex = new THREE.DataTexture(bytes, size, size, THREE.RGBAFormat);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(2.5, 2.5);
    tex.magFilter = THREE.LinearFilter;
    tex.minFilter = THREE.LinearMipmapLinearFilter;
    tex.generateMipmaps = true;
    tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
    tex.needsUpdate = true;
    return tex;
  };
  return { color: make(data), rough: make(roughData) };
}

export function buildRobot(renderer: THREE.WebGLRenderer) {
  const ring = (inset: number, z: number, minR = 0.006) => roundedRing(S - 2 * inset, Math.max(R - inset, minR), z);
  const { color: colorMap, rough: wear } = wearTextures(renderer);

  const shellMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(0.74, 0.74, 0.725), map: colorMap, roughnessMap: wear, roughness: 0.75, metalness: 0, clearcoat: 0.7, clearcoatRoughness: 0.1, vertexColors: true, envMapIntensity: 1 });
  const panelMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(0.28, 0.285, 0.29), map: colorMap, roughnessMap: wear, roughness: 0.85, clearcoat: 0.2, clearcoatRoughness: 0.25 });
  const rubberMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.02, 0.021, 0.023), roughness: 0.62 });
  const trackMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.03, 0.031, 0.032), roughness: 0.55 });
  const fibreMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.55, 0.55, 0.53), roughness: 0.95, side: THREE.DoubleSide, vertexColors: true });
  const metalMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.55, 0.55, 0.56), metalness: 1, roughness: 0.38 });
  const tetherMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.55, 0.56, 0.56), roughness: 0.5 });

  const pz = ZTOP - 0.0065, rim = 0.027, pin = rim + 0.0012;
  const rubber: THREE.BufferGeometry[] = [
    loft([ring(0.006, ZLO + 0.001), ring(0.007, ZLO + 0.001)]),
    loft([roundedRing(S - 0.13, 0.03, 0.0012), roundedRing(S - 0.124, 0.03, 0.004), roundedRing(S - 0.124, 0.03, ZLO + 0.002)], false),
    loft([ring(0.0016, ZLO + 0.0214), ring(0.0013, ZLO + 0.0225), ring(0.0016, ZLO + 0.0236)], false),
    loft([roundedRing(S - 2 * (rim + 0.0002), 0.028, pz - 0.0005), roundedRing(S - 2 * (rim + 0.0012), 0.028, pz + 0.0014), roundedRing(S - 2 * (pin + 0.0024), 0.028, pz + 0.0003)], false),
  ];
  for (let k = 0; k < 7; k++) { const y = -0.03 + k * 0.01; rubber.push(box(-0.112, y - 0.0016, pz, -0.066, y + 0.0016, pz + 0.0005)); }
  const tracks = mergeGeometries([track(0.15, 0.05, 0.12, 0.0335, 0.035), track(-0.15, 0.05, 0.12, 0.0335, 0.035)]);

  // Pad bar at the sim's PAD_X with a worn microfibre edge. The fringe shows past the body. Art only: no contact geometry changes.
  const padX = -0.13, padParts: THREE.BufferGeometry[] = [box(padX - 0.045, -0.118, 0.0015, padX + 0.04, 0.118, 0.018)];
  let s = 4242; const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const fv: number[] = [];
  for (let k = 0; k < 2600; k++) {
    const side = rnd();
    let bx: number, by: number, dx: number, dy: number;
    if (side < 0.76) { bx = padX - 0.045; by = -0.118 + rnd() * 0.236; dx = -1; dy = rnd() - 0.5; }
    else { const sg = rnd() < 0.5 ? 1 : -1; bx = padX - 0.045 + rnd() * 0.085; by = sg * 0.118; dx = rnd() - 0.5; dy = sg; }
    const L = 0.004 + rnd() * 0.013, w = 0.001 + rnd() * 0.0012, z = 0.002 + rnd() * 0.014;
    fv.push(bx, by - w, z, bx, by + w, z, bx + dx * L, by + dy * L, z + rnd() * 0.007 - 0.004);
  }
  const fringe = new THREE.BufferGeometry();
  fringe.setAttribute('position', new THREE.Float32BufferAttribute(fv, 3));
  fringe.computeVertexNormals();
  const fc = new Float32Array(fv.length); for (let i = 0; i < fc.length; i += 9) { const t = 0.3 + 0.7 * rnd(); fc.set([t * 0.5, t * 0.5, t * 0.5, t, t, t, t, t, t * 0.97], i); }
  fringe.setAttribute('color', new THREE.BufferAttribute(fc, 3));
  fringe.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(fv.length / 3 * 2), 2));
  padParts.push(fringe);
  const pad = mergeGeometries(padParts.map(g => (g.index ? g.toNonIndexed() : g)));

  // Shell: side wall, gasket seam, shoulder, narrow rim, sharp drop to the panel.
  const sect: [number, number][] = [[0.004, ZLO], [0.0012, ZLO + 0.002], [0, ZLO + 0.006], [0, ZLO + 0.0205], [0.0006, ZLO + 0.0212], [0.0026, ZLO + 0.0218], [0.0026, ZLO + 0.0232], [0.0006, ZLO + 0.0238], [0, ZLO + 0.0245], [0, ZTOP - 0.018]];
  sect.push(...fillet(ZTOP - 0.018, ZTOP, 0, 0.018, 8).slice(1));
  sect.push([rim - 0.002, ZTOP], [rim - 0.0008, ZTOP - 0.0003], [rim, ZTOP - 0.0015], [rim + 0.0004, ZTOP - 0.006]);
  const shell = mergeGeometries([
    loft(sect.map(([i, z]) => roundedRing(S - 2 * i, Math.max(R - i, 0.03), z)), false),
    lathe([[0.024, pz], [0.024, pz + 0.002], [0.02, pz + 0.004], [0.011, pz + 0.012], [0.007, pz + 0.024], [0.0052, pz + 0.032], [0.0001, pz + 0.032]]),
  ]);
  const panel = loft([pin, pin + 0.0008, pin + 0.002, pin + 0.006].map((i, k) => roundedRing(S - 2 * i, 0.028, [ZTOP - 0.012, pz - 0.0012, pz, pz][k])));
  const fasteners: THREE.BufferGeometry[] = [];
  for (const [cx, cy] of [[0.118, 0.118], [-0.118, 0.118], [0.118, -0.118], [-0.118, -0.118]]) {
    const g = lathe([[0.0058, pz + 0.0002], [0.0052, pz + 0.0012], [0.0028, pz + 0.0014], [0.0001, pz + 0.0014]], 14);
    g.translate(cx, cy, 0);
    fasteners.push(g);
  }

  const root = new THREE.Group();
  root.matrixAutoUpdate = false;
  const add = (g: THREE.BufferGeometry, m: THREE.Material, inMirror: boolean) => {
    const mesh = new THREE.Mesh(g, m);
    mesh.castShadow = mesh.receiveShadow = true;
    if (inMirror) mesh.layers.enable(1);
    root.add(mesh);
    return mesh;
  };
  add(mergeGeometries(rubber.map(g => (g.index ? g.toNonIndexed() : g))), rubberMat, true);
  add(tracks, trackMat, true);
  add(pad, fibreMat, true);
  add(shell, shellMat, true);
  add(panel, panelMat, false);
  add(mergeGeometries(fasteners), metalMat, false);

  const tether = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 10, 1, true).translate(0, 0.5, 0), tetherMat);
  tether.matrixAutoUpdate = false;
  tether.frustumCulled = false;
  tether.castShadow = true;
  tether.layers.enable(1);

  const dispose = () => {
    root.traverse(o => { if (o instanceof THREE.Mesh) o.geometry.dispose(); });
    tether.geometry.dispose();
    for (const m of [shellMat, panelMat, rubberMat, trackMat, fibreMat, metalMat, tetherMat]) m.dispose();
    wear.dispose(); colorMap.dispose();
  };
  return { root, tether, bootLocal: new THREE.Vector3(0, 0, pz + 0.03), dispose };
}
