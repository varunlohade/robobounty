// The "blueprint, then real" build effect. View only: it never touches the world, the physics or a replay.
// A part's blue lines grow in, then its real material reveals from the bottom up behind a bright line. At the end every material is as it was and every line object is gone.
import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';

export const BLUE_LINE = 0x4cc2ff;
export const BLUE_GROUND = new THREE.Color().setRGB(0.012, 0.045, 0.115);
export const OBJECT_DRAW_S = 1.2;
export const OBJECT_REVEAL_S = 1.2;
const BAND_LINE = new THREE.Color(0.8, 0.95, 1);
const LINE_PX = 1.35;
const BAND_PX = 2.2;
const GLOW_WIDTH = 9; // The soft light under the bright line, as a multiple of its width.
const GLOW_ALPHA = 0.3;
const OBJECT_LINE = 0x1a8cff; // Deeper, so a single object's lines hold against a bright real scene.
const OBJECT_LINE_PX = 2.1;
const MAX_PIECES = 26000;
const MAX_EDGES = 5000;
const HIDDEN = 1e9;

type Axis = 'x' | 'y' | 'z';
export interface BuildPart {
  meshes: THREE.Mesh[];
  /** Line ends in world space: x, y, z, x, y, z for each line. */
  lines: number[];
  /** Lines start growing at this time, and take this long. */
  at: number; draw: number;
  /** The material sweeps up over this time. */
  revealAt: number; reveal: number;
  /** The sweep's direction. Something flat sweeps along the ground. */
  axis?: Axis;
  /** Where the sweep runs, for a part much larger than the view. Past it, the whole part shows. */
  span?: [number, number];
  /** For a shader that clips itself: it gets the height, then Infinity at the end. */
  clip?: (height: number) => void;
  noBand?: boolean;
  /** Line brightness, against the view's own. */
  gain?: number;
  /** For a part with no surface to clip the lines against: they fade over its reveal. */
  fadeLines?: boolean;
  /** Line width in pixels, for a small dense part. */
  linePx?: number;
  /** Moves the bright line off a surface whose own shader rounds its depth differently. */
  bandLift?: THREE.Vector3;
}

export function reducedMotion(): boolean {
  try { return matchMedia('(prefers-reduced-motion: reduce)').matches; } catch { return false; }
}

/** The hard edges of some meshes, in world space, as line ends. A heavy mesh keeps an even sample of its edges. */
export function edgeLines(meshes: THREE.Mesh[], degrees = 10, keepEdge?: (a: THREE.Vector3, b: THREE.Vector3) => boolean): number[] {
  const out: number[] = [];
  const v = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3();
  for (const mesh of meshes) {
    const edges = new THREE.EdgesGeometry(mesh.geometry, degrees);
    const pos = edges.getAttribute('position');
    const keep = Math.max(1, Math.ceil(pos.count / 2 / MAX_EDGES));
    for (let i = 0; i + 1 < pos.count; i += 2 * keep) {
      if (keepEdge && !keepEdge(a.fromBufferAttribute(pos, i), b.fromBufferAttribute(pos, i + 1))) continue;
      for (const k of [i, i + 1]) {
        v.fromBufferAttribute(pos, k).applyMatrix4(mesh.matrixWorld);
        out.push(v.x, v.y, v.z);
      }
    }
    edges.dispose();
  }
  return out;
}

/** Cuts lines into short pieces, ordered so each line grows from its low end and all of them grow together. */
function growing(lines: number[]): Float32Array {
  const count = lines.length / 6;
  let size = 0;
  for (let i = 0; i < count; i++) size = Math.max(size, Math.hypot(lines[i * 6] - lines[i * 6 + 3], lines[i * 6 + 1] - lines[i * 6 + 4], lines[i * 6 + 2] - lines[i * 6 + 5]));
  const perLine = Math.max(1, Math.min(32, Math.floor(MAX_PIECES / Math.max(1, count))));
  const pieces: { key: number; p: number[] }[] = [];
  for (let i = 0; i < count; i++) {
    const o = i * 6;
    let a = [lines[o], lines[o + 1], lines[o + 2]], b = [lines[o + 3], lines[o + 4], lines[o + 5]];
    if (a[2] > b[2] || (a[2] === b[2] && a[0] > b[0])) [a, b] = [b, a];
    const length = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const n = Math.max(1, Math.min(perLine, Math.ceil((length / (size || 1)) * perLine)));
    const late = ((i * 0.618034) % 1) * 0.28; // Lines do not all start on the same frame, so they read as drawn.
    for (let k = 0; k < n; k++) {
      const s = k / n, e = (k + 1) / n;
      pieces.push({ key: late + (s * 0.72), p: [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, a[2] + (b[2] - a[2]) * s, a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e, a[2] + (b[2] - a[2]) * e] });
    }
  }
  pieces.sort((x, y) => x.key - y.key);
  const out = new Float32Array(pieces.length * 6);
  pieces.forEach((piece, i) => out.set(piece.p, i * 6));
  return out;
}

const clamp01 = (t: number) => Math.max(0, Math.min(1, t));
export const smooth = (t: number) => { const k = clamp01(t); return k * k * (3 - 2 * k); };
const easeOut = (t: number) => 1 - (1 - clamp01(t)) ** 2;
const axisVector = (axis: Axis) => new THREE.Vector3(axis === 'x' ? 1 : 0, axis === 'y' ? 1 : 0, axis === 'z' ? 1 : 0);

interface LivePart {
  part: BuildPart; axis: Axis; lo: number; hi: number; from: number; to: number; centre: THREE.Vector3;
  keep: THREE.Plane; above: THREE.Plane; low: THREE.Plane; glowLow: THREE.Plane;
  line: LineSegments2 | null; lineCount: number;
  bandMats: THREE.MeshBasicMaterial[]; bands: THREE.Mesh[];
  saved: { material: THREE.Material; planes: THREE.Plane[] | null; shadows: boolean }[];
  closed: boolean;
}

// The line on the surfaces the sweep crosses. A face that lies flat in the sweep's direction would flash whole as the line passes it, so those faces draw no line.
function bandMaterial(colour: THREE.Color, axis: Axis, planes: THREE.Plane[], glow: boolean) {
  const material = new THREE.MeshBasicMaterial({ color: colour, side: THREE.DoubleSide, toneMapped: false, fog: false, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2, clippingPlanes: planes,
    ...(glow ? { transparent: true, opacity: GLOW_ALPHA, blending: THREE.AdditiveBlending } : {}) });
  material.onBeforeCompile = shader => {
    shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vBandAt;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvBandAt = (modelMatrix * vec4(transformed, 1.0)).xyz;');
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vBandAt;')
      .replace('#include <clipping_planes_fragment>', `#include <clipping_planes_fragment>
        if (abs(normalize(cross(dFdx(vBandAt), dFdy(vBandAt))).${axis}) > 0.85) discard;`);
  };
  material.customProgramCacheKey = () => `band-${axis}`;
  return material;
}

const openOn = new WeakMap<THREE.WebGLRenderer, number>();

export class BlueprintBuild {
  /** A check can stop the clock here, to look at one moment. */
  hold: number | null = null;
  private t0 = -1;
  private live: LivePart[] = [];
  private ended = false;
  readonly length: number;
  private tanHalf: number;

  constructor(private scene: THREE.Scene, private renderer: THREE.WebGLRenderer, private camera: THREE.PerspectiveCamera, parts: BuildPart[], private opts: { pixels: number; lineGain?: number; bandGain?: number; target?: THREE.WebGLRenderTarget | null; single?: boolean; onFrame?: (t: number) => void; onEnd?: () => void }) {
    this.length = Math.max(0, ...parts.map(p => p.revealAt + p.reveal));
    this.tanHalf = Math.tan((camera.fov * Math.PI) / 360);
    scene.updateMatrixWorld(true);
    // Draw the plain programs now, so restoring a material at its end costs no compile in the middle of the effect.
    const before = renderer.getRenderTarget();
    renderer.setRenderTarget(opts.target ?? before);
    renderer.compile(scene, camera);
    renderer.setRenderTarget(before);
    renderer.localClippingEnabled = true;
    openOn.set(renderer, (openOn.get(renderer) ?? 0) + 1);
    const box = new THREE.Box3(), taken = new Set<THREE.Material>();
    for (const part of parts) this.live.push(this.open(part, box, taken));
  }

  private open(part: BuildPart, box: THREE.Box3, taken: Set<THREE.Material>): LivePart {
    box.makeEmpty();
    for (const mesh of part.meshes) box.expandByObject(mesh);
    if (box.isEmpty()) { box.min.set(0, 0, 0); box.max.set(0, 0, 0); }
    const axis: Axis = part.axis ?? 'z';
    const lo = box.min[axis], hi = box.max[axis];
    const normal = axisVector(axis);
    const keep = new THREE.Plane(normal.clone().negate(), lo - 1);
    const above = new THREE.Plane(normal.clone(), -(lo - 1));
    const low = new THREE.Plane(normal.clone(), -(lo - 1));
    const glowLow = new THREE.Plane(normal.clone(), -(lo - 1));
    const saved: LivePart['saved'] = [];
    for (const mesh of part.meshes) {
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
        if (taken.has(material)) continue;
        // A plain shader has no clipping chunks. Its part clips it through `clip`.
        if ((material as THREE.ShaderMaterial).isShaderMaterial && !(material as THREE.ShaderMaterial).clipping) continue;
        taken.add(material);
        saved.push({ material, planes: material.clippingPlanes as THREE.Plane[] | null, shadows: material.clipShadows });
        material.clippingPlanes = [keep];
        material.clipShadows = true;
      }
    }
    part.clip?.(-HIDDEN);
    let line: LineSegments2 | null = null, lineCount = 0;
    if (part.lines.length) {
      const pieces = growing(part.lines);
      lineCount = pieces.length / 6;
      const geometry = new LineSegmentsGeometry();
      geometry.setPositions(pieces);
      geometry.instanceCount = 0;
      const material = new LineMaterial({ linewidth: (part.linePx ?? (this.opts.single ? OBJECT_LINE_PX : LINE_PX)) * this.opts.pixels, worldUnits: false, toneMapped: false, clippingPlanes: part.fadeLines ? [] : [above] });
      material.color.setHex(this.opts.single ? OBJECT_LINE : BLUE_LINE).multiplyScalar((this.opts.lineGain ?? 1) * (part.gain ?? 1));
      if (part.fadeLines) material.transparent = true;
      line = new LineSegments2(geometry, material);
      line.frustumCulled = false;
      line.renderOrder = 2;
      this.scene.add(line);
    }
    const bandMats: THREE.MeshBasicMaterial[] = [];
    const bands: THREE.Mesh[] = [];
    if (!part.noBand && part.meshes.length) {
      const colour = BAND_LINE.clone().multiplyScalar(this.opts.bandGain ?? 1);
      bandMats.push(bandMaterial(colour, axis, [keep, low], false), bandMaterial(colour.clone().multiplyScalar(0.6).lerp(new THREE.Color(BLUE_LINE), 0.5), axis, [keep, glowLow], true));
      for (const mesh of part.meshes) {
        for (const material of bandMats) {
          const band = new THREE.Mesh(mesh.geometry, material);
          band.visible = false;
          if (part.bandLift) band.position.copy(part.bandLift);
          band.frustumCulled = mesh.frustumCulled;
          band.renderOrder = mesh.renderOrder + 3;
          mesh.add(band);
          bands.push(band);
        }
      }
    }
    const from = part.span ? part.span[0] : lo, to = part.span ? part.span[1] : hi;
    return { part, axis, lo, hi, from, to, centre: box.getCenter(new THREE.Vector3()), keep, above, low, glowLow, line, lineCount, bandMats, bands, saved, closed: false };
  }

  /** Moves the effect to this moment. False when it has ended. */
  step(now: number): boolean {
    if (this.ended) return false;
    if (this.t0 < 0) this.t0 = now;
    const t = this.hold ?? (now - this.t0) / 1000;
    let open = false;
    for (const l of this.live) {
      if (l.closed) continue;
      const { part } = l;
      if (l.line) l.line.geometry.instanceCount = Math.round(easeOut((t - part.at) / part.draw) * l.lineCount);
      const k = (t - part.revealAt) / part.reveal;
      if (k >= 1) { this.close(l); continue; }
      open = true;
      if (k <= 0) continue;
      const height = l.from + (l.to - l.from) * smooth(k);
      l.keep.constant = height;
      l.above.constant = -height;
      if (l.line && part.fadeLines) (l.line.material as LineMaterial).opacity = 1 - clamp01(k * 1.6);
      part.clip?.(height);
      if (l.bandMats.length) {
        const c = l.centre;
        if (part.span) c.x = this.camera.position.x; // Larger than the view: the width that counts is the width where the eye is.
        const distance = Math.max(0.1, Math.hypot(this.camera.position.x - c.x, this.camera.position.y - c.y, l.axis === 'z' ? this.camera.position.z - height : this.camera.position.z - c.z));
        const metres = (BAND_PX * this.opts.pixels * 2 * distance * this.tanHalf) / Math.max(1, this.renderer.domElement.height);
        l.low.constant = -(height - metres);
        l.glowLow.constant = -(height - metres * GLOW_WIDTH);
        for (const band of l.bands) band.visible = true;
      }
    }
    this.opts.onFrame?.(t);
    if (!open && this.hold === null) { this.finish(); return false; }
    return true;
  }

  private close(l: LivePart) {
    if (l.closed) return;
    l.closed = true;
    for (const { material, planes, shadows } of l.saved) { material.clippingPlanes = planes; material.clipShadows = shadows; }
    l.part.clip?.(HIDDEN);
    if (l.line) {
      this.scene.remove(l.line);
      l.line.geometry.dispose();
      (l.line.material as LineMaterial).dispose();
      l.line = null;
    }
    for (const band of l.bands) band.removeFromParent();
    for (const material of l.bandMats) material.dispose();
    l.bands = [];
    l.bandMats = [];
  }

  /** Ends the effect at once and restores everything. Safe to call twice. */
  finish() {
    if (this.ended) return;
    this.ended = true;
    for (const l of this.live) this.close(l);
    const left = (openOn.get(this.renderer) ?? 1) - 1;
    openOn.set(this.renderer, left);
    if (left <= 0) this.renderer.localClippingEnabled = false;
    this.opts.onFrame?.(Infinity);
    this.opts.onEnd?.();
  }
}

/** A square ground grid as line ends, at a height, around a centre. */
export function groundGrid(cx: number, cy: number, half: number, step: number, z: number): number[] {
  const out: number[] = [];
  const x0 = Math.round((cx - half) / step) * step, y0 = Math.round((cy - half) / step) * step;
  const n = Math.round((half * 2) / step);
  for (let i = 0; i <= n; i++) {
    out.push(x0 + i * step, y0, z, x0 + i * step, y0 + n * step, z);
    out.push(x0, y0 + i * step, z, x0 + n * step, y0 + i * step, z);
  }
  return out;
}

/** Spaces parts out, largest first: each one's lines, then its reveal, inside the fixed window of the first build. */
export function staggered<T extends { meshes: THREE.Mesh[]; lines: number[]; axis?: Axis; span?: [number, number]; clip?: (height: number) => void; noBand?: boolean; gain?: number; fadeLines?: boolean; linePx?: number }>(parts: T[], lineWindow: [number, number], revealWindow: [number, number], draw: number, reveal: number): BuildPart[] {
  const n = Math.max(1, parts.length - 1);
  return parts.map((p, i) => ({ ...p,
    at: lineWindow[0] + ((lineWindow[1] - lineWindow[0] - draw) * i) / n, draw,
    revealAt: revealWindow[0] + ((revealWindow[1] - revealWindow[0] - reveal) * i) / n, reveal,
  }));
}
