// A three.js player for a robot pack's replay JSON (format robot-pack-replay/1). It draws what the file holds: solids, scenery and the route. The robot is the asset's own meshes, one group per body at its recorded pose.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { mergeGeometries } from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import { el, icon } from '../app/dom.ts';
import { fmtTime } from '../app/world_page.ts';

export interface Primitive {
  name?: string; object?: string; type: 'box' | 'cylinder' | 'capsule';
  pos: number[]; quat: number[]; size: number[];
  material?: string; colour: number[]; friction?: number; picture_only?: boolean;
}
export interface PoseResult {
  verdict: string; passed: boolean; reason: string;
  time_s?: number | null; fell_t_s?: number | null; stuck_t_s?: number | null;
  waypoint_t_s?: number[]; waypoints_reached?: number; waypoints?: number;
  [key: string]: unknown;
}
export interface PoseReplay {
  format: string; pack: string; robot: string; label: string; note: string; simulated: boolean; fps: number;
  body_labels: string[]; body_parents: number[]; pose_layout: string[];
  route: { x: number; y: number }[]; floor_friction: number;
  solids: Primitive[]; scenery: Primitive[]; result: PoseResult;
  frames: { t: number; q: number[] }[];
}

const GZIP_0 = 0x1f, GZIP_1 = 0x8b;
export async function loadPoses(url: string): Promise<PoseReplay> {
  const res = await fetch(url, { signal: AbortSignal.timeout(20_000) });
  if (!res.ok) throw new Error(`replay: HTTP ${res.status}`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  const text = bytes[0] === GZIP_0 && bytes[1] === GZIP_1
    ? await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text()
    : new TextDecoder().decode(bytes);
  const replay = JSON.parse(text) as PoseReplay;
  if (!replay.format?.startsWith('robot-pack-replay/')) throw new Error(`replay: unknown format ${replay.format}`);
  return replay;
}

/** A scene with no run yet: the plant and the route, and no robot. */
export function previewReplay(scene: Pick<PoseReplay, 'solids' | 'scenery' | 'route' | 'floor_friction' | 'note'>): PoseReplay {
  return { format: 'robot-pack-replay/1', pack: '', robot: '', label: '', simulated: true, fps: 1, body_labels: [], body_parents: [], pose_layout: [], frames: [], result: { verdict: '', passed: true, reason: '' }, ...scene };
}

interface RobotModel {
  parts: { body: string; colour: number[]; texture: string | null; first_index: number; index_count: number }[];
  vertices: number; indices: number; layout: { position: number; normal: number; uv: number; index: number };
  bin: ArrayBuffer; base: string;
}
const robotModels = new Map<string, Promise<RobotModel>>();
// The meshes export_robot.py wrote from the same asset the physics loaded. One fetch per robot, however many views open.
function loadRobotModel(robot: string): Promise<RobotModel> {
  let got = robotModels.get(robot);
  if (!got) {
    const base = `/robots/${encodeURIComponent(robot)}`;
    got = (async () => {
      const [head, bin] = await Promise.all([fetch(`${base}/robot.json`), fetch(`${base}/robot.bin`)]);
      if (!head.ok || !bin.ok) throw new Error(`robot meshes: HTTP ${head.status}, ${bin.status}`);
      return { ...(await head.json()), bin: await bin.arrayBuffer(), base } as RobotModel;
    })();
    got.catch(() => robotModels.delete(robot));
    robotModels.set(robot, got);
  }
  return got;
}

const POSE_SIZE = 7;
const VIEW_OFFSET = new THREE.Vector3(-2.2, -4.0, 2.7); // The same chase as the pack's own render.
const VIEW_AIM = new THREE.Vector3(0.2, 0.5, 0.55);
const CHASE_SECONDS = 1.5;
const ROBOT_ROUGH = 0.6;
const ROBOT_REACH_M = 1.5; // Past any part's distance from its own body.
const NORMAL_STRIDE = 4;
const ROUTE_COLOUR = 0x3e7bfa;
const ROUTE_Z = 0.012;
const ROUTE_ORDER = 1;
const ROBOT_ORDER = 2;
const BACKGROUND = 0x23211f;
const FLOOR_TILE_M = 12;
const GRIME_TILE_M = 2.5;
const SHEET_TILE_M = 1.2;
const FLOOR_HALF_M = 60;

const ROUGH: Record<string, number> = { steel: 0.5, galvanised: 0.6, dark_steel: 0.55, flange: 0.5, tank: 0.5, clad_pipe: 0.5, wet: 0.08, rubber: 0.95 };
const TEXTURE_OF: Record<string, 'grime' | 'sheet'> = { concrete: 'grime', cladding: 'sheet', tank: 'grime', plate: 'grime', cabinet: 'grime', column: 'grime', clad_pipe: 'grime' };

// A small seeded generator, so a texture looks the same on every load.
function seeded(start: number) {
  let s = start;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
}

function canvasTexture(size: number, tile: number, draw: (c: CanvasRenderingContext2D, r: () => number) => void, seed: number, renderer: THREE.WebGLRenderer) {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  draw(canvas.getContext('2d')!, seeded(seed));
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  texture.repeat.set(1 / tile, 1 / tile);
  return texture;
}

function blotches(c: CanvasRenderingContext2D, r: () => number, size: number, count: number, radius: number, alpha: number) {
  for (let i = 0; i < count; i++) {
    const x = r() * size, y = r() * size, rad = radius * (0.4 + r());
    const shade = r() < 0.5 ? '0,0,0' : '255,255,255';
    for (const [dx, dy] of [[0, 0], [size, 0], [-size, 0], [0, size], [0, -size]]) {
      const g = c.createRadialGradient(x + dx, y + dy, 0, x + dx, y + dy, rad);
      g.addColorStop(0, `rgba(${shade},${alpha})`);
      g.addColorStop(1, `rgba(${shade},0)`);
      c.fillStyle = g;
      c.fillRect(x + dx - rad, y + dy - rad, rad * 2, rad * 2);
    }
  }
}

// Power-floated concrete with slab joints every 3 m, as the pack's render draws it.
function drawConcrete(c: CanvasRenderingContext2D, r: () => number) {
  const size = c.canvas.width;
  c.fillStyle = '#ffffff';
  c.fillRect(0, 0, size, size);
  c.fillStyle = 'rgba(0,0,0,.09)';
  c.fillRect(0, 0, size, size);
  for (let k = 0; k < 4; k++) {
    c.fillStyle = r() < 0.5 ? `rgba(0,0,0,${r() * 0.05})` : `rgba(255,255,255,${r() * 0.05})`;
    c.fillRect(0, (size * k) / 4, size, size / 4);
  }
  blotches(c, r, size, 26, size / 5, 0.05);
  blotches(c, r, size, 200, size / 28, 0.05);
  const grit = c.getImageData(0, 0, size, size);
  for (let i = 0; i < grit.data.length; i += 4) {
    const d = (r() - 0.5) * 11;
    grit.data[i] += d; grit.data[i + 1] += d; grit.data[i + 2] += d;
  }
  c.putImageData(grit, 0, 0);
  c.fillStyle = 'rgba(20,18,16,.7)';
  const w = size / 700;
  for (let k = 0; k < 4; k++) {
    const at = (size * k) / 4;
    c.fillRect(at - w, 0, w * 2, size);
    c.fillRect(0, at - w, size, w * 2);
  }
}

function drawGrime(c: CanvasRenderingContext2D, r: () => number) {
  const size = c.canvas.width;
  c.fillStyle = '#ececec';
  c.fillRect(0, 0, size, size);
  blotches(c, r, size, 40, size / 5, 0.05);
  for (let i = 0; i < 130; i++) {
    c.fillStyle = `rgba(0,0,0,${r() * 0.06})`;
    c.fillRect(r() * size, 0, 2 + r() * 8, size);
  }
}

function drawSheet(c: CanvasRenderingContext2D, r: () => number) {
  const size = c.canvas.width;
  for (let x = 0; x < size; x++) {
    const rib = 0.93 + 0.07 * Math.max(-1, Math.min(1, Math.cos((2 * Math.PI * x * 4) / size) * 2.5));
    const v = Math.round(rib * 255);
    c.fillStyle = `rgb(${v},${v},${v})`;
    c.fillRect(x, 0, 1, size);
  }
  for (let i = 0; i < 40; i++) {
    c.fillStyle = `rgba(0,0,0,${r() * 0.05})`;
    c.fillRect(r() * size, 0, 2 + r() * 10, size);
  }
}

function primitiveGeometry(p: Primitive): THREE.BufferGeometry {
  let g: THREE.BufferGeometry;
  if (p.type === 'box') g = new THREE.BoxGeometry(p.size[0] * 2, p.size[1] * 2, p.size[2] * 2);
  else {
    const big = p.size[0] > 0.3;
    if (p.type === 'capsule') g = new THREE.CapsuleGeometry(p.size[0], p.size[1] * 2, big ? 16 : 6, big ? 40 : 12);
    else g = new THREE.CylinderGeometry(p.size[0], p.size[0], p.size[1] * 2, big ? 40 : 14);
    g.rotateX(Math.PI / 2); // three builds these along y. The pack's shapes run along z.
  }
  const m = new THREE.Matrix4().compose(new THREE.Vector3(p.pos[0], p.pos[1], p.pos[2]), new THREE.Quaternion(p.quat[0], p.quat[1], p.quat[2], p.quat[3]), new THREE.Vector3(1, 1, 1));
  g.applyMatrix4(m);
  return worldUv(g);
}

// Metric texture coordinates from the world position, by the facing axis, so a rib or a streak has one size on every part.
function worldUv(g: THREE.BufferGeometry) {
  const pos = g.getAttribute('position'), normal = g.getAttribute('normal'), uv = g.getAttribute('uv');
  for (let i = 0; i < pos.count; i++) {
    const nx = Math.abs(normal.getX(i)), ny = Math.abs(normal.getY(i)), nz = Math.abs(normal.getZ(i));
    if (nz >= nx && nz >= ny) uv.setXY(i, pos.getX(i), pos.getY(i));
    else if (ny >= nx) uv.setXY(i, pos.getX(i), pos.getZ(i));
    else uv.setXY(i, pos.getY(i), pos.getZ(i));
  }
  return g;
}

export class PosesView {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private bodies: THREE.Group[] = [];
  /** Settles when the robot is drawn, or when its meshes failed and the page says so. */
  robotReady: Promise<void> = Promise.resolve();
  private chase: THREE.Vector2[] = [];
  private disposers: (() => void)[] = [];
  private observer: ResizeObserver;
  private dirty = true;
  private stopped = false;
  private lastChase = new THREE.Vector2();
  private userFramed = false;
  private loop = 0;
  private base = new THREE.Vector3();
  frame = 0;
  onLost: (() => void) | null = null;

  constructor(private host: HTMLElement, readonly replay: PoseReplay) {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setClearColor(BACKGROUND);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.prepend(this.renderer.domElement); // Under the tags.
    this.renderer.domElement.addEventListener('webglcontextlost', e => {
      e.preventDefault();
      if (!this.stopped) this.onLost?.();
    });

    this.camera = new THREE.PerspectiveCamera(45, 1, 0.05, 300);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    this.controls.minDistance = 0.6;
    this.controls.maxDistance = 40;
    this.controls.addEventListener('change', () => { this.dirty = true; });

    this.buildLights();
    this.buildPlant();
    this.buildRoute();
    this.buildRobot();
    this.buildChase();
    this.seek(0);
    const c = this.chase[0];
    this.lastChase.copy(c);
    this.camera.position.set(c.x, c.y, 0).add(VIEW_OFFSET);
    this.controls.target.set(c.x, c.y, 0).add(VIEW_AIM);
    this.controls.update();

    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.resize();
    this.startLoop();
  }

  private buildLights() {
    this.scene.add(new THREE.HemisphereLight(0xdfe4e8, 0x4c4a46, 1.5));
    const fill = new THREE.DirectionalLight(0xffffff, 0.55);
    fill.position.set(-5, -7, 5);
    this.scene.add(fill);
    // Roof glazing casts the shadows, straight down, as in the pack's render.
    const roof = new THREE.DirectionalLight(0xfff8ec, 1.7);
    roof.position.set(5.5, 3, 18);
    roof.target.position.set(5.5, 3, 0);
    roof.castShadow = true;
    roof.shadow.mapSize.set(2048, 2048);
    const reach = 15;
    Object.assign(roof.shadow.camera, { left: -reach, right: reach, top: reach, bottom: -reach, near: 1, far: 30 });
    roof.shadow.bias = -0.0006;
    roof.shadow.normalBias = 0.02;
    this.scene.add(roof, roof.target);
  }

  private buildPlant() {
    const { renderer } = this;
    const concrete = canvasTexture(1024, FLOOR_TILE_M, drawConcrete, 7, renderer);
    const grime = canvasTexture(512, GRIME_TILE_M, drawGrime, 11, renderer);
    const sheet = canvasTexture(512, SHEET_TILE_M, drawSheet, 13, renderer);
    this.disposers.push(() => { concrete.dispose(); grime.dispose(); sheet.dispose(); });

    const floorGeometry = new THREE.PlaneGeometry(FLOOR_HALF_M * 2, FLOOR_HALF_M * 2);
    worldUv(floorGeometry);
    const floorMaterial = new THREE.MeshStandardMaterial({ map: concrete, roughness: 0.85, color: new THREE.Color().setRGB(0.4, 0.39, 0.365) });
    const floor = new THREE.Mesh(floorGeometry, floorMaterial);
    floor.receiveShadow = true;
    this.scene.add(floor);
    this.disposers.push(() => { floorGeometry.dispose(); floorMaterial.dispose(); });

    const groups = new Map<string, Primitive[]>();
    for (const p of [...this.replay.scenery, ...this.replay.solids]) {
      const key = `${p.material ?? 'plain'}|${p.colour.join(',')}`;
      const list = groups.get(key);
      if (list) list.push(p); else groups.set(key, [p]);
    }
    for (const list of groups.values()) {
      const { material: name = 'plain', colour } = list[0];
      const parts = list.map(primitiveGeometry);
      const geometry = mergeGeometries(parts.map(g => (g.index ? g.toNonIndexed() : g)));
      for (const g of parts) g.dispose();
      const textured = TEXTURE_OF[name];
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color().setRGB(colour[0], colour[1], colour[2]),
        map: textured === 'sheet' ? sheet : textured === 'grime' ? grime : null,
        roughness: ROUGH[name] ?? 0.75,
        metalness: 0,
      });
      if (name === 'lamp') { material.emissive = new THREE.Color(0xfff2d8); material.emissiveIntensity = 1.4; }
      const mesh = new THREE.Mesh(geometry, material);
      // A thin floor mark throws no shadow. Everything else does.
      mesh.castShadow = name !== 'line' && name !== 'lamp' && name !== 'wet';
      mesh.receiveShadow = true;
      mesh.name = name;
      this.scene.add(mesh);
      this.disposers.push(() => { geometry.dispose(); material.dispose(); });
    }
  }

  private buildRoute() {
    const { route } = this.replay;
    // Drawn over the plant, under the robot, so a walkway never hides the route.
    const material = new THREE.MeshBasicMaterial({ color: ROUTE_COLOUR, toneMapped: false, depthTest: false, depthWrite: false, transparent: false });
    const group = new THREE.Group();
    this.disposers.push(() => material.dispose());
    for (let i = 0; i + 1 < route.length; i++) {
      const a = route[i], b = route[i + 1];
      const length = Math.hypot(b.x - a.x, b.y - a.y);
      const g = new THREE.PlaneGeometry(length, 0.05);
      const m = new THREE.Mesh(g, material);
      m.position.set((a.x + b.x) / 2, (a.y + b.y) / 2, ROUTE_Z);
      m.rotation.z = Math.atan2(b.y - a.y, b.x - a.x);
      m.renderOrder = ROUTE_ORDER;
      group.add(m);
      this.disposers.push(() => g.dispose());
    }
    route.forEach(p => {
      const g = new THREE.RingGeometry(0.12, 0.17, 28);
      const m = new THREE.Mesh(g, material);
      m.position.set(p.x, p.y, ROUTE_Z);
      m.renderOrder = ROUTE_ORDER;
      group.add(m);
      this.disposers.push(() => g.dispose());
    });
    this.scene.add(group);
  }

  private poseAt(frame: number, body: number, out = new THREE.Vector3()) {
    const q = this.replay.frames[frame].q, at = body * POSE_SIZE;
    return out.set(q[at], q[at + 1], q[at + 2]);
  }

  private buildRobot() {
    const { body_labels: labels, robot } = this.replay;
    if (!labels.length) return;
    for (const label of labels) {
      const group = new THREE.Group();
      group.name = label;
      this.scene.add(group);
      this.bodies.push(group);
    }
    this.robotReady = loadRobotModel(robot).then(model => {
      if (!this.stopped) return this.dressRobot(model);
    }).catch(err => {
      if (!this.stopped) this.host.append(el('div', 'sim-tag sim-key sim-bad', `The robot's meshes did not load, so the robot is not drawn. ${String(err)}`));
    });
  }

  private dressRobot(model: RobotModel) {
    const { position, normal, uv, index } = model.layout;
    const positions = new THREE.BufferAttribute(new Float32Array(model.bin, position, model.vertices * 3), 3);
    const normals = new THREE.BufferAttribute(new Int8Array(model.bin, normal, model.vertices * NORMAL_STRIDE), NORMAL_STRIDE, true);
    const uvs = new THREE.BufferAttribute(new Float32Array(model.bin, uv, model.vertices * 2), 2);
    const indices = new THREE.BufferAttribute(new Uint32Array(model.bin, index, model.indices), 1);
    const paints = new Map<string, THREE.MeshStandardMaterial>();
    const painted: Promise<void>[] = [];
    const loader = new THREE.TextureLoader();
    const anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    const paint = (colour: number[], texture: string | null) => {
      const key = `${colour.join(',')}|${texture}`;
      let material = paints.get(key);
      if (!material) {
        material = new THREE.MeshStandardMaterial({ color: new THREE.Color().setRGB(colour[0], colour[1], colour[2]), roughness: ROBOT_ROUGH });
        if (texture) {
          let settled = () => {};
          painted.push(new Promise(done => { settled = done; }));
          const map = loader.load(`${model.base}/textures/${encodeURIComponent(texture)}`, () => { this.dirty = true; settled(); }, undefined, () => settled());
          map.colorSpace = THREE.SRGBColorSpace;
          map.anisotropy = anisotropy;
          material.map = map;
          this.disposers.push(() => map.dispose());
        }
        const made = material;
        this.disposers.push(() => made.dispose());
        paints.set(key, material);
      }
      return material;
    };
    const byLabel = new Map(this.bodies.map(g => [g.name, g]));
    for (const part of model.parts) {
      const body = byLabel.get(part.body);
      if (!body) continue;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', positions);
      geometry.setAttribute('normal', normals);
      geometry.setAttribute('uv', uvs);
      geometry.setIndex(indices);
      geometry.setDrawRange(part.first_index, part.index_count);
      // Each part reads one slice of the shared buffers, so its bounds come from the body, not from its own vertices.
      geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), ROBOT_REACH_M);
      const mesh = new THREE.Mesh(geometry, paint(part.colour, part.texture));
      mesh.castShadow = true;
      mesh.renderOrder = ROBOT_ORDER;
      body.add(mesh);
      this.disposers.push(() => geometry.dispose());
    }
    this.host.dataset.robotParts = String(model.parts.length);
    this.dirty = true;
    return Promise.all(painted).then(() => {});
  }

  private buildChase() {
    const { frames, fps, route } = this.replay;
    if (!frames.length) {
      this.chase = [new THREE.Vector2(route[0]?.x ?? 0, route[0]?.y ?? 0)];
      return;
    }
    const half = Math.round((CHASE_SECONDS * fps) / 2);
    const a = new THREE.Vector3();
    const xy = frames.map((_, i) => { this.poseAt(i, 0, a); return [a.x, a.y]; });
    this.chase = frames.map((_, i) => {
      let x = 0, y = 0, n = 0;
      for (let k = i - half; k <= i + half; k++) {
        const p = xy[Math.max(0, Math.min(frames.length - 1, k))];
        x += p[0]; y += p[1]; n++;
      }
      return new THREE.Vector2(x / n, y / n);
    });
  }

  private resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  private startLoop() {
    const run = ++this.loop;
    const tick = () => {
      if (this.stopped || run !== this.loop) return;
      if (this.dirty) {
        this.dirty = false;
        this.renderer.render(this.scene, this.camera);
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /** Puts every body at its recorded pose, and moves the camera with the robot. */
  seek(frame: number) {
    this.frame = Math.max(0, Math.min(this.replay.frames.length - 1, frame));
    if (!this.replay.frames.length) { this.frame = 0; this.dirty = true; return; }
    const q = this.replay.frames[this.frame].q;
    this.bodies.forEach((group, i) => {
      const at = i * POSE_SIZE;
      group.position.set(q[at], q[at + 1], q[at + 2]);
      group.quaternion.set(q[at + 3], q[at + 4], q[at + 5], q[at + 6]);
    });
    if (this.bodies.length) this.base.copy(this.bodies[0].position);
    if (this.chase.length) {
      const c = this.chase[this.frame];
      const dx = c.x - this.lastChase.x, dy = c.y - this.lastChase.y;
      if (!this.userFramed && (dx || dy)) {
        this.camera.position.x += dx; this.camera.position.y += dy;
        this.controls.target.x += dx; this.controls.target.y += dy;
        this.controls.update();
      }
      this.lastChase.copy(c);
    }
    this.dirty = true;
  }

  /** The base of the robot, from the mesh itself. */
  robot(): [number, number, number] {
    return [this.base.x, this.base.y, this.base.z];
  }

  /** A body's pose as drawn, and how many meshes it holds: the check reads these. */
  drawnBody(body: number) {
    const group = this.bodies[body];
    if (!group) return null;
    group.updateWorldMatrix(true, false);
    const position = new THREE.Vector3(), quaternion = new THREE.Quaternion();
    group.matrixWorld.decompose(position, quaternion, new THREE.Vector3());
    return { position: position.toArray(), quaternion: quaternion.toArray(), meshes: group.children.length };
  }

  robotOnScreen() {
    const seen = this.base.clone().project(this.camera);
    return { x: seen.x, y: seen.y, inFrame: Math.abs(seen.x) < 1 && Math.abs(seen.y) < 1 && seen.z < 1 };
  }

  // The same two names as SimView, so the chat's camera event can drive either view.
  frameOn(box: number[]) {
    const [x0, y0, z0, x1, y1, z1] = box;
    const c = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);
    const size = Math.max(x1 - x0, y1 - y0, z1 - z0, 1);
    this.userFramed = true;
    this.controls.target.copy(c);
    this.camera.position.copy(c).add(VIEW_OFFSET.clone().normalize().multiplyScalar(size * 2.2 + 1.5));
    this.controls.update();
    this.dirty = true;
  }

  backToRobot() {
    this.userFramed = false;
    const c = this.chase[this.frame];
    this.lastChase.copy(c);
    this.camera.position.set(c.x, c.y, 0).add(VIEW_OFFSET);
    this.controls.target.set(c.x, c.y, 0).add(VIEW_AIM);
    this.controls.update();
    this.dirty = true;
  }

  kick() {
    this.startLoop();
    this.dirty = true;
  }

  setLook() { /* A pack's plant has no look. */ }

  dispose() {
    this.stopped = true;
    this.observer.disconnect();
    this.controls.dispose();
    this.renderer.shadowMap.enabled = false;
    for (const d of this.disposers) d();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}

/** The page for one replay: the same viewport, transport bar and status line as a window robot's run. */
export function posesPage(replay: PoseReplay, statusRight: HTMLElement, onFix?: (code: string, words: string) => void) {
  const page = el('div', 'page');
  const body = el('div', 'world-body');
  const viewport = el('div', 'viewport');
  viewport.style.setProperty('--sim-sky', `#${BACKGROUND.toString(16)}`);
  const maxFrame = replay.frames.length - 1;
  const total = replay.frames[maxFrame].t;
  const seconds = (s: number) => fmtTime(s);

  viewport.append(el('div', 'sim-tag sim-label', replay.note));
  const verdict = el('div', `sim-tag sim-key${replay.result.passed ? '' : ' sim-bad'}`, replay.result.reason);
  viewport.append(verdict);
  body.append(viewport);

  const player = el('div', 'player');
  const button = (label: string, name?: 'start' | 'end') => {
    const b = el('button', 'icon-btn');
    b.type = 'button';
    b.setAttribute('aria-label', label);
    b.title = label;
    if (name) b.append(icon(name));
    return b;
  };
  const startBtn = button('Go to start', 'start');
  const playBtn = button('Play or pause (Space)');
  const endBtn = button('Go to end', 'end');
  const scrub = el('div', 'scrub');
  const slider = el('input');
  slider.type = 'range';
  slider.min = '0';
  slider.max = String(maxFrame);
  slider.step = '1';
  slider.value = '0';
  slider.setAttribute('aria-label', 'Timeline');
  scrub.append(slider);
  const marks: [string, number][] = [];
  if (replay.result.fell_t_s != null) marks.push(['Fell', replay.result.fell_t_s]);
  if (replay.result.stuck_t_s != null) marks.push(['Stuck', replay.result.stuck_t_s]);
  for (const [name, t] of marks) {
    const mark = el('div', 'mark');
    mark.style.left = `${Math.min(100, (t / total) * 100)}%`;
    mark.title = `${name} at ${t} s`;
    scrub.append(mark);
  }
  const time = el('span', 'time');
  const speed = el('select', 'select');
  speed.setAttribute('aria-label', 'Playback speed');
  for (const s of [1, 2, 4, 8]) {
    const opt = el('option', '', `${s}x`);
    opt.value = String(s);
    opt.selected = s === 1;
    speed.append(opt);
  }
  player.append(startBtn, playBtn, endBtn, scrub, time, speed);
  page.append(body, player);

  const statusTime = el('span');
  statusRight.prepend(statusTime);

  let view: PosesView | null = null;
  let playing = false;
  let stopped = false;
  let at = 0;
  let last = performance.now();
  let tickRun = 0;

  const show = (frame: number) => {
    if (!view) return;
    view.seek(frame);
    const f = view.frame, t = replay.frames[f].t;
    viewport.dataset.frame = String(f);
    viewport.dataset.robot = JSON.stringify(view.robot());
    time.textContent = `${seconds(t)} / ${seconds(total)}`;
    statusTime.textContent = `Frame ${f} of ${maxFrame}`;
    slider.value = String(f);
    slider.style.setProperty('--done', `${maxFrame ? (f / maxFrame) * 100 : 0}%`);
  };
  const setPlaying = (on: boolean) => {
    playing = on;
    playBtn.replaceChildren(icon(on ? 'pause' : 'play'));
    viewport.dataset.playing = String(on);
    last = performance.now();
  };
  const toggle = () => {
    if (!playing && at >= maxFrame) at = 0;
    setPlaying(!playing);
    if (playing) view?.backToRobot();
  };
  const jump = (frame: number) => {
    setPlaying(false);
    at = frame;
    show(at);
  };
  playBtn.addEventListener('click', toggle);
  startBtn.addEventListener('click', () => jump(0));
  endBtn.addEventListener('click', () => jump(maxFrame));
  slider.addEventListener('input', () => jump(Number(slider.value)));
  const onKey = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (e.code !== 'Space' || !page.isConnected || t.closest('textarea, input, select, button, summary')) return;
    e.preventDefault();
    toggle();
  };
  addEventListener('keydown', onKey);

  const build = () => {
    view = new PosesView(viewport, replay);
    let rebuilds = 0;
    const arm = (v: PosesView) => {
      v.onLost = () => {
        if (++rebuilds > 3) { onFix?.('webgl_gave_up', 'The 3D view keeps losing its graphics, so I stopped rebuilding it. Reload the page.'); return; }
        v.dispose();
        view = new PosesView(viewport, replay);
        arm(view);
        show(Math.floor(at));
        onFix?.('webgl_lost', 'The 3D view lost its graphics, so I rebuilt it at the same frame.');
      };
    };
    arm(view);
  };

  const runTick = () => {
    const run = ++tickRun;
    const tick = (now: number) => {
      if (stopped || run !== tickRun) return;
      if (playing) {
        at += ((now - last) / 1000) * replay.fps * Number(speed.value);
        if (at >= maxFrame) { at = maxFrame; setPlaying(false); }
        show(Math.floor(at));
      }
      last = now;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  return {
    page, viewport,
    start() {
      build();
      setPlaying(false);
      show(0);
      // The clock starts with the robot on screen, so a first replay does not walk an empty scene.
      const loading = el('div', 'sim-tag sim-key', 'Loading the robot');
      viewport.append(loading);
      void view!.robotReady.then(() => {
        loading.remove();
        if (stopped) return;
        setPlaying(true);
        viewport.dataset.ready = 'true';
        runTick();
      });
    },
    stop() {
      stopped = true;
      removeEventListener('keydown', onKey);
      statusTime.remove();
      view?.dispose();
      view = null;
    },
    get view() { return view; },
    jump,
  };
}
