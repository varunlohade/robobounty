import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { Line2 } from 'three/examples/jsm/lines/Line2.js';
import { LineGeometry } from 'three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { HAZE, SKY_URL, bakeDrops, bakeGrime, skyDome } from '../view/real/air.ts';
import { cityGeometry, cityMaterial } from '../view/real/city.ts';
import { barGeometry, brushedTextures, glassMaterial, type FacadeGrid } from '../view/real/facade.ts';
import { CITIES, FOG_THICKNESS, TIMES, luminance, parseLook, tintOf, type Look } from '../view/real/look.ts';
import { compositeMaterial } from '../view/real/post.ts';
import { buildRobot } from '../view/real/robot.ts';
import type { Replay } from './replay.ts';
import type { Trial } from './trial.ts';

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const PATH_OFF_GLASS_M = 0.004;
const PAD = 6; // Cells around the recorded grid. The record stops there, so the film returns to its start level.
const MIRROR_LAYER = 1;
// The default view, from the robot: close, along the wall, with the street below past the tower's corner. Same framing as the film render's "side" shot.
const VIEW_FROM_ROBOT = new THREE.Vector3(1.7, -1.08, 0.52);
const LOOK_FROM_ROBOT = new THREE.Vector3(-0.92, -0.43, -0.23);
const MAX_PIXELS = 3.2e6; // A big window keeps its frame rate: past this, the picture scales up.
const FOLLOW_RATE = 2.6; // Per second.
const FOLLOW_MARGIN_M = 1.5; // A falling robot leaves the frame: the camera stays with the assigned area.

export type Quality = 'high' | 'medium' | 'low';
const TIERS: Record<Quality, { dpr: number; hdr: boolean; samples: number; mirror: number; dof: boolean; grain: number; radius: number; grime: number; shadow: number }> = {
  high: { dpr: 2, hdr: true, samples: 4, mirror: 0.5, dof: true, grain: 0.014, radius: 5200, grime: 2048, shadow: 2048 },
  medium: { dpr: 1, hdr: true, samples: 4, mirror: 0.5, dof: false, grain: 0.01, radius: 5200, grime: 2048, shadow: 1024 },
  low: { dpr: 1, hdr: false, samples: 0, mirror: 0, dof: false, grain: 0, radius: 1800, grime: 512, shadow: 512 },
};

// The sky picture starts loading with the module, so a first snapshot usually has it. The scene works without it.
let skyImage: HTMLImageElement | null = null;
const skyLoad: Promise<HTMLImageElement | null> = new Promise(resolve => {
  const img = new Image();
  img.onload = () => { skyImage = img; resolve(img); };
  img.onerror = () => resolve(null);
  img.src = SKY_URL;
});

function pickQuality(gl: WebGL2RenderingContext): Quality {
  const asked = new URLSearchParams(location.search).get('quality');
  if (asked === 'high' || asked === 'medium' || asked === 'low') return asked;
  const info = gl.getExtension('WEBGL_debug_renderer_info');
  const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : '';
  return /swiftshader|llvmpipe|software|microsoft basic/i.test(name) ? 'low' : 'high';
}

// Draws the MuJoCo state with physically based materials. Poses, the tether and the dirt come from the recording.
// Static scenery (glass, joints, city) is drawn richer than the MJCF's boxes. See policy/render/README.md for what is art. It feeds nothing back.
export class SimView {
  renderer: THREE.WebGLRenderer; scene = new THREE.Scene(); camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  private drawn: { mesh: THREE.Mesh; geom: number }[] = [];
  private robot: ReturnType<typeof buildRobot>;
  private robotBody: number;
  private path: Line2 | null = null;
  private pathStart = 0;
  private dirtA: THREE.DataTexture; private dirtB: THREE.DataTexture;
  private dirtIndex = -1;
  private anchorSite: number; private robotSite: number;
  private glass: THREE.ShaderMaterial; private city: THREE.ShaderMaterial; private composite: THREE.ShaderMaterial;
  private quality: Quality; private reversed: boolean;
  private hdr: THREE.WebGLRenderTarget | null = null; private mirror: THREE.WebGLRenderTarget | null = null;
  private mirrorCam = new THREE.PerspectiveCamera();
  private postScene = new THREE.Scene(); private postCam = new THREE.PerspectiveCamera();
  private grime: THREE.WebGLRenderTarget; private brushed: ReturnType<typeof brushedTextures>;
  private skyTexture: THREE.Texture | null = null; private skyUniform: { value: THREE.Texture | null } = { value: null };
  private dome: THREE.Mesh; private env: THREE.WebGLRenderTarget | null = null;
  private sun: THREE.DirectionalLight;
  private haze = HAZE.clone(); private metalMat!: THREE.MeshPhysicalMaterial; private towerMat: THREE.MeshStandardMaterial | null = null;
  private envStrength = 0.85; private envKey = 'noon|0|default';
  private disposers: (() => void)[] = [];
  private level: Float32Array; private levelRef = 1; private dirtMask: Uint8Array;
  private follow = new THREE.Vector3(); private followTo = new THREE.Vector3(); private followed = false;
  private robotPos = new THREE.Vector3();
  private dirty = true; private stopped = false; private shadowsDirty = true;
  private observer: ResizeObserver;
  private seed = 0; private lastTick = 0; private slow = 0; private frames = 0;

  constructor(private host: HTMLElement, private replay: Replay, private trial: Trial) {
    const built = performance.now();
    const area = trial.manifest.area;
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    this.renderer = new THREE.WebGLRenderer({ antialias: false, reversedDepthBuffer: true, powerPreference: 'high-performance' });
    this.reversed = this.renderer.capabilities.reversedDepthBuffer === true;
    this.quality = pickQuality(this.renderer.getContext() as WebGL2RenderingContext);
    host.dataset.quality = this.quality;
    const tier = TIERS[this.quality];
    this.renderer.setClearColor(HAZE);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.62;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.shadowMap.autoUpdate = false;
    host.prepend(this.renderer.domElement);

    const cx = (area.x0 + area.x1) / 2, cz = (area.z0 + area.z1) / 2;
    this.camera = new THREE.PerspectiveCamera(46, 1, 0.05, 30000);
    this.camera.up.set(0, 0, 1);
    this.camera.layers.enable(MIRROR_LAYER);
    this.mirrorCam.layers.set(MIRROR_LAYER);
    this.mirrorCam.near = this.camera.near; this.mirrorCam.far = this.camera.far;
    this.camera.position.set(cx, 0, cz).add(VIEW_FROM_ROBOT);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(cx, 0, cz).add(LOOK_FROM_ROBOT);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.07;
    this.controls.rotateSpeed = 0.35;
    this.controls.zoomSpeed = 0.6;
    this.controls.panSpeed = 0.5;
    this.controls.minDistance = 0.35;
    this.controls.maxDistance = 70;
    this.controls.addEventListener('change', () => { this.dirty = true; });

    this.grime = bakeGrime(this.renderer, tier.grime);
    const dropsRt = bakeDrops(this.renderer, tier.grime);
    this.disposers.push(() => { this.grime.dispose(); dropsRt.dispose(); });
    const noise = { value: this.grime.texture as THREE.Texture };
    this.brushed = brushedTextures(this.renderer);
    this.disposers.push(() => { this.brushed.color.dispose(); this.brushed.rough.dispose(); });

    const { model } = replay;
    const mj = replay.mj;
    const geomId = (name: string) => mj.mj_name2id(model, mj.mjtObj.mjOBJ_GEOM.value, name);
    const towerId = geomId('tower');
    const tower = {
      x: model.geom_pos[towerId * 3], y: model.geom_pos[towerId * 3 + 1], z: model.geom_pos[towerId * 3 + 2],
      hx: model.geom_size[towerId * 3], hy: model.geom_size[towerId * 3 + 1], hz: model.geom_size[towerId * 3 + 2],
    };
    const grid = this.buildFrame(geomId, tower);

    // Sky and city go in both the main pass and the mirror pass.
    this.dome = skyDome(this.skyUniform);
    this.dome.layers.enable(MIRROR_LAYER);
    (this.dome.material as THREE.ShaderMaterial).uniforms.uHaze.value = this.haze;
    this.scene.add(this.dome);
    this.city = cityMaterial(noise);
    this.city.uniforms.uHaze.value = this.haze;
    const cityMesh = new THREE.Mesh(cityGeometry(tower.x, tower.y, tier.radius), this.city);
    cityMesh.frustumCulled = false;
    cityMesh.layers.enable(MIRROR_LAYER);
    this.scene.add(cityMesh);
    this.disposers.push(() => this.city.dispose());

    // The glass wall: one plane, with its panes in the shader.
    this.glass = glassMaterial(noise, { value: dropsRt.texture }, grid);
    this.glass.uniforms.uWet.value = Number(trial.world?.wetness ?? 0);
    this.glass.uniforms.uHaze.value = this.haze;
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(tower.hx * 2, tower.z + tower.hz).rotateX(Math.PI / 2), this.glass);
    wall.position.set(tower.x, 0, (tower.z + tower.hz) / 2);
    wall.receiveShadow = false;
    this.scene.add(wall);
    this.disposers.push(() => { wall.geometry.dispose(); this.glass.dispose(); });

    // Soft directional light under the overcast: it shapes the robot and throws its soft shadow. The sky map does the rest.
    this.sun = new THREE.DirectionalLight(0xfff6ea, 0.95);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(tier.shadow, tier.shadow);
    this.sun.shadow.radius = 5;
    this.sun.shadow.bias = -0.0002;
    this.sun.shadow.normalBias = 0.002;
    Object.assign(this.sun.shadow.camera, { left: -0.7, right: 0.7, top: 0.7, bottom: -0.7, near: 0.5, far: 7 });
    this.sun.layers.enable(MIRROR_LAYER);
    this.scene.add(this.sun, this.sun.target);

    this.buildGeoms(geomId);

    this.robot = buildRobot(this.renderer);
    this.scene.add(this.robot.root, this.robot.tether);
    this.disposers.push(() => this.robot.dispose());
    this.robotBody = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY.value, 'robot');
    this.anchorSite = mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE.value, 'anchor');
    this.robotSite = mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE.value, 'tether_point');

    // Dirt: the recorded grid, one texture per second, with the cells at joints filled from their neighbours.
    const d = trial.manifest.dirt;
    const hasGrid = d.nx > 1 && d.nz > 1;
    const w = hasGrid ? d.nx + 2 * PAD : 1, h = hasGrid ? d.nz + 2 * PAD : 1;
    const dirtTexture = () => {
      const t = new THREE.DataTexture(new Uint8Array(w * h).fill(85), w, h, THREE.RedFormat, THREE.UnsignedByteType);
      t.magFilter = t.minFilter = THREE.LinearFilter;
      t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
      t.needsUpdate = true;
      return t;
    };
    this.dirtA = dirtTexture(); this.dirtB = dirtTexture();
    this.disposers.push(() => { this.dirtA.dispose(); this.dirtB.dispose(); });
    this.level = new Float32Array(hasGrid ? d.nx * d.nz : 1);
    this.dirtMask = new Uint8Array(this.level.length);
    let sum = 0, count = 0;
    if (hasGrid) {
      for (let i = 0; i < this.level.length; i++) {
        const v = trial.dirt[i];
        if (v === 0) this.dirtMask[i] = 1; else { sum += v / d.scale; count++; }
      }
    }
    this.levelRef = count ? Math.max(sum / count, 1e-3) : 1;
    const cellX = hasGrid ? (area.x1 - area.x0) / d.nx : 1, cellZ = hasGrid ? (area.z1 - area.z0) / d.nz : 1;
    const gu = this.glass.uniforms;
    gu.uDirtA.value = this.dirtA; gu.uDirtB.value = this.dirtB;
    gu.uDirtSize.value.set(w, h);
    gu.uDirtRect.value.set(hasGrid ? area.x0 - PAD * cellX : -1e6, hasGrid ? area.z0 - PAD * cellZ : -1e6, hasGrid ? w * cellX : 1, hasGrid ? h * cellZ : 1);
    const c = d.clean_below / this.levelRef;
    gu.uClean.value.set(hasGrid ? c * 0.55 : -1, hasGrid ? c * 1.6 : 0);
    const level = Number(trial.world?.dirt_level ?? 0.6);
    gu.uFilm.value = Math.min(1.4, 0.55 + 0.75 * level) * 0.8;

    const firedTimes = Object.values(trial.result.fired).map(f => f.t);
    if (firedTimes.length) {
      this.pathStart = Math.round(Math.min(...firedTimes) * trial.manifest.hz);
      const points = replay.path();
      const kept: number[] = [];
      for (let f = this.pathStart; f < points.length / 3; f += 1) kept.push(points[f * 3], points[f * 3 + 1] - PATH_OFF_GLASS_M, points[f * 3 + 2]);
      if (kept.length >= 6) {
        const geo = new LineGeometry();
        geo.setPositions(kept);
        const color = new THREE.Color(token('--fail')).multiplyScalar(1.9);
        const mat = new LineMaterial({ color: color.getHex(), linewidth: 1.6, worldUnits: false, toneMapped: false });
        mat.color.copy(color);
        this.path = new Line2(geo, mat);
        this.path.frustumCulled = false;
        geo.instanceCount = 0;
        this.scene.add(this.path);
        this.disposers.push(() => { geo.dispose(); mat.dispose(); });
      }
    }

    this.composite = compositeMaterial(this.reversed, tier.dof);
    this.composite.uniforms.uNearFar.value.set(this.camera.near, this.camera.far);
    this.composite.uniforms.uGrain.value = tier.grain;
    const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.composite);
    quad.frustumCulled = false;
    this.postScene.add(quad);
    this.disposers.push(() => { quad.geometry.dispose(); this.composite.dispose(); });

    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(host);
    this.resize();

    if (skyImage) this.useSky(skyImage);
    else {
      host.dataset.loading = 'sky';
      void skyLoad.then(img => { if (!this.stopped) { delete host.dataset.loading; if (img) this.useSky(img); else this.buildEnv(); } });
      this.buildEnv();
    }

    host.dataset.sceneMs = String(Math.round(performance.now() - built));
    const loop = (now: number) => {
      if (this.stopped) return;
      this.controls.update();
      this.stepCamera(now);
      if (this.dirty && host.clientWidth > 0) { this.dirty = false; this.renderFrame(); this.watchSpeed(now); }
      this.lastTick = now;
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  dispose() {
    this.stopped = true;
    this.observer.disconnect();
    this.controls.dispose();
    for (const d of this.disposers) d();
    this.env?.dispose(); this.hdr?.dispose(); this.mirror?.dispose(); this.skyTexture?.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }

  /** One picture from a given camera position, then the old camera comes back. */
  snapshot(position: [number, number, number], target: [number, number, number]): string {
    const oldPos = this.camera.position.clone(), oldTarget = this.controls.target.clone();
    this.camera.position.set(...position);
    this.camera.lookAt(...target);
    this.camera.updateMatrixWorld();
    const maxR = this.composite.uniforms.uMaxR.value;
    this.composite.uniforms.uMaxR.value = 0;
    this.renderFrame();
    this.composite.uniforms.uMaxR.value = maxR;
    const url = this.renderer.domElement.toDataURL('image/png');
    this.camera.position.copy(oldPos);
    this.controls.target.copy(oldTarget);
    this.camera.lookAt(oldTarget);
    this.dirty = true;
    return url;
  }

  /** Changes the scenery in place: uniforms and material colours, then a new light probe when the sky changes. It feeds nothing to physics, so a run is the same under any look. */
  setLook(raw: unknown) {
    const look: Look = parseLook(raw);
    const time = TIMES[look.time ?? 'noon'], city = CITIES[look.city ?? 'default'], fog = look.fog ?? 0;
    const glass = this.glass.uniforms, sky = (this.dome.material as THREE.ShaderMaterial).uniforms, c = this.city.uniforms;

    this.haze.copy(time.haze).multiply(city.haze);
    this.renderer.setClearColor(this.haze);
    glass.uEnvFlat.value.copy(time.flat);
    glass.uFogK.value = c.uFogK.value = FOG_THICKNESS[fog];
    sky.uSkyMix.value = time.skyMix; sky.uSkyLow.value.copy(time.skyLow); sky.uSkyHigh.value.copy(time.skyHigh); sky.uSkyFog.value = fog * 0.3;
    c.uDay.value = time.day; c.uLights.value = time.lights; c.uCityTint.value.copy(city.tint); c.uGround.value.copy(city.ground); c.uLift.value = city.lift; c.uShore.value = city.shore;
    this.sun.color.copy(time.sun); this.sun.intensity = time.sunLevel;
    this.envStrength = time.env;
    glass.uRooms.value = time.rooms;

    // The building: a painted panel behind each pane, the frit band, and the tower's other sides.
    const body = look.building ? new THREE.Color(look.building) : null;
    glass.uBodyAmt.value = body ? 1 : 0;
    glass.uBodyLight.value.copy(time.body);
    if (body) {
      const lum = luminance(body);
      glass.uBody.value.copy(body);
      // A dark colour keeps almost no reflection, or a bright sky would turn black into grey.
      glass.uReflKeep.value = 0.06 + 0.24 * Math.sqrt(lum);
      glass.uFilmKeep.value = 0.16 + 0.3 * Math.sqrt(lum);
      glass.uFrit.value.copy(body).multiply(time.body).multiplyScalar(0.55);
    } else {
      glass.uReflKeep.value = 1; glass.uFilmKeep.value = 1;
      glass.uFrit.value.setRGB(0.01, 0.011, 0.012);
    }
    this.towerMat?.color.copy(body ?? new THREE.Color(0.03, 0.035, 0.038));
    if (this.towerMat) { this.towerMat.roughness = body ? 0.6 : 0.12; this.towerMat.metalness = body ? 0.1 : 0.8; }

    // The glass tint colours the reflection and the view into the rooms, and glows a little so a dark pane still shows it.
    if (look.glass_tint) {
      const tint = tintOf(look.glass_tint);
      glass.uTint.value.copy(tint);
      glass.uTintGlow.value.copy(tint).multiply(time.body).multiplyScalar(0.11);
      // Over a painted building the tint is a stain on the paint.
      if (body) glass.uBody.value.copy(body).lerp(body.clone().multiply(tint), 0.75).lerp(tint, 0.15);
    } else {
      glass.uTint.value.setRGB(1, 1, 1);
      glass.uTintGlow.value.setRGB(0, 0, 0);
    }

    // The frames follow the building until someone names their own colour. Painted metal shows its colour better than bare metal.
    const frames = look.frames ?? look.building;
    if (frames) {
      this.metalMat.color.set(frames).multiplyScalar(1.3);
      this.metalMat.metalness = 0.2; this.metalMat.roughness = 0.6;
    } else {
      this.metalMat.color.setRGB(0.72, 0.735, 0.75);
      this.metalMat.metalness = 1; this.metalMat.roughness = 0.75;
    }

    const envKey = `${look.time ?? 'noon'}|${fog}|${look.city ?? 'default'}`;
    if (envKey !== this.envKey) { this.envKey = envKey; this.buildEnv(); }
    else this.scene.environmentIntensity = this.envStrength;
    this.host.dataset.look = JSON.stringify(look);
    this.dirty = true;
  }

  private useSky(img: HTMLImageElement) {
    const t = new THREE.Texture(img);
    t.colorSpace = THREE.NoColorSpace;
    t.wrapS = THREE.RepeatWrapping;
    t.wrapT = THREE.ClampToEdgeWrapping;
    t.minFilter = t.magFilter = THREE.LinearFilter;
    t.generateMipmaps = false;
    t.needsUpdate = true;
    this.skyTexture = t;
    this.skyUniform.value = t;
    (this.dome.material as THREE.ShaderMaterial).uniforms.uHas.value = 1;
    this.buildEnv();
    this.dirty = true;
  }

  // Bakes the sky and the city into the light probe, once: reflections and fill light on the robot and the metal.
  private buildEnv() {
    const envScene = new THREE.Scene();
    envScene.add(this.dome.clone());
    const city = this.scene.children.find(o => (o as THREE.Mesh).material === this.city) as THREE.Mesh;
    envScene.add(city.clone());
    const wallBack = new THREE.Mesh(new THREE.BoxGeometry(60, 40, 400), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.09, 0.1, 0.105) }));
    wallBack.position.set(this.robotPos.x, 20.05, 130);
    envScene.add(wallBack);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const at = new THREE.Vector3(this.robotPos.x || 1.2, -0.6, this.robotPos.z || 136);
    const old = this.renderer.toneMapping;
    const next = pmrem.fromScene(envScene, 0, 1, 25000, { size: 256, position: at });
    this.renderer.toneMapping = old;
    this.env?.dispose();
    this.env = next;
    this.scene.environment = next.texture;
    this.scene.environmentIntensity = this.envStrength;
    pmrem.dispose();
    wallBack.geometry.dispose();
    (wallBack.material as THREE.Material).dispose();
    this.dirty = true;
  }

  // Joints, from the MJCF's capsules. Past the sim's glass, the same grid repeats to the tower's edges.
  private buildFrame(geomId: (n: string) => number, tower: { x: number; y: number; z: number; hx: number; hy: number; hz: number }): FacadeGrid {
    const m = this.replay.model;
    const read = (prefix: string, axis: number) => {
      const out: { at: number; crownY: number }[] = [];
      for (let k = 0; ; k++) {
        const id = geomId(`${prefix}${k}`);
        if (id < 0) break;
        out.push({ at: m.geom_pos[id * 3 + axis], crownY: m.geom_pos[id * 3 + 1] - m.geom_size[id * 3] });
      }
      return out.sort((a, b) => a.at - b.at);
    };
    const mullions = read('mullion', 0), transoms = read('transom', 2);
    const x0 = tower.x - tower.hx, x1 = tower.x + tower.hx, top = tower.z + tower.hz;
    const spacingX = mullions.length > 1 ? mullions[1].at - mullions[0].at : 1.5;
    const spacingZ = transoms.length > 1 ? transoms[1].at - transoms[0].at : 3.6;
    const offsetX = mullions.length ? mullions[0].at : 0;
    const offsetZ = transoms.length ? transoms[0].at : 0;
    const crown = mullions[0]?.crownY ?? -0.005, crownT = (transoms[0]?.crownY ?? crown) + 0.0004;
    const bars: Parameters<typeof barGeometry>[0] = [];
    for (let k = Math.ceil((x0 - offsetX) / spacingX); offsetX + k * spacingX < x1; k++) bars.push({ axis: 'z', at: offsetX + k * spacingX, from: 0, to: top, crownY: crown });
    for (let k = Math.ceil(-offsetZ / spacingZ); offsetZ + k * spacingZ < top; k++) bars.push({ axis: 'x', at: offsetZ + k * spacingZ, from: x0, to: x1, crownY: crownT });
    const { metal, seal } = barGeometry(bars);
    const metalMat = new THREE.MeshPhysicalMaterial({ color: new THREE.Color(0.72, 0.735, 0.75), metalness: 1, roughness: 0.75, map: this.brushed.color, roughnessMap: this.brushed.rough, anisotropy: 0.55, anisotropyRotation: Math.PI / 2 });
    this.metalMat = metalMat;
    const metalMesh = new THREE.Mesh(metal, metalMat);
    metalMesh.receiveShadow = true;
    metalMesh.layers.enable(MIRROR_LAYER);
    const sealMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.012, 0.012, 0.013), roughness: 0.6 });
    const sealMesh = new THREE.Mesh(seal, sealMat);
    // The wall has to end in something.
    const corners = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.23, top), metalMat);
    corners.position.set(x0, 0.085, top / 2);
    const corners2 = corners.clone();
    corners2.position.x = x1;
    this.scene.add(metalMesh, sealMesh, corners, corners2);
    this.disposers.push(() => { metal.dispose(); seal.dispose(); metalMat.dispose(); sealMat.dispose(); corners.geometry.dispose(); });
    return { spacingX, offsetX, spacingZ, offsetZ, x0, x1, z1: top };
  }

  // Everything the recording says exists and this file has no richer drawing for: tower body, parapet, ledge, scene elements.
  private buildGeoms(geomId: (n: string) => number) {
    const { model: m, mj } = this.replay;
    const robot = mj.mj_name2id(m, mj.mjtObj.mjOBJ_BODY.value, 'robot');
    const rootOf = (b: number) => m.body_rootid[b];
    const cityMats = new Set(['city0', 'city1'].map(n => mj.mj_name2id(m, mj.mjtObj.mjOBJ_MATERIAL.value, n)));
    const skip = new Set<number>([geomId('glass'), geomId('ground')]);
    for (const p of ['mullion', 'transom']) for (let k = 0; ; k++) { const id = geomId(`${p}${k}`); if (id < 0) break; skip.add(id); }
    for (let i = 0; i < m.ngeom; i++) {
      if (skip.has(i) || cityMats.has(m.geom_matid[i]) || rootOf(m.geom_bodyid[i]) === robot) continue;
      const type = m.geom_type[i], s = [m.geom_size[i * 3], m.geom_size[i * 3 + 1], m.geom_size[i * 3 + 2]];
      let g: THREE.BufferGeometry;
      if (type === 0) g = new THREE.PlaneGeometry(s[0] * 2, s[1] * 2);
      else if (type === 2) g = new THREE.SphereGeometry(s[0], 24, 16);
      else if (type === 3) { g = new THREE.CapsuleGeometry(s[0], s[1] * 2, 8, 16); g.rotateX(Math.PI / 2); }
      else if (type === 5) { g = new THREE.CylinderGeometry(s[0], s[0], s[1] * 2, 32); g.rotateX(Math.PI / 2); }
      else if (type === 6) g = new THREE.BoxGeometry(s[0] * 2, s[1] * 2, s[2] * 2);
      else throw new Error(`geom ${i}: type ${type} has no drawing code`);
      const mat = m.geom_matid[i];
      const c = mat >= 0 ? m.mat_rgba : m.geom_rgba, o = (mat >= 0 ? mat : i) * 4;
      const color = new THREE.Color(c[o], c[o + 1], c[o + 2]);
      const isTower = i === geomId('tower');
      const material = new THREE.MeshStandardMaterial({ color: isTower ? new THREE.Color(0.03, 0.035, 0.038) : color, roughness: isTower ? 0.12 : 0.7, metalness: isTower ? 0.8 : 0.05 });
      if (isTower) this.towerMat = material;
      const mesh = new THREE.Mesh(g, material);
      mesh.matrixAutoUpdate = false;
      mesh.castShadow = !isTower;
      mesh.receiveShadow = !isTower;
      this.scene.add(mesh);
      this.drawn.push({ mesh, geom: i });
      this.disposers.push(() => { g.dispose(); material.dispose(); });
    }
  }

  private resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, TIERS[this.quality].dpr, Math.sqrt(MAX_PIXELS / (w * h))));
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    // The pane is often narrower than the film frame. Widen a little so the wall and the street both stay in shot.
    this.camera.fov = w / h < 1.15 ? 50 : 44;
    this.camera.updateProjectionMatrix();
    this.setupTargets();
    this.dirty = true;
  }

  private setupTargets() {
    const tier = TIERS[this.quality];
    const size = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    this.hdr?.dispose(); this.mirror?.dispose();
    this.hdr = null; this.mirror = null;
    if (tier.hdr) {
      this.hdr = new THREE.WebGLRenderTarget(size.x, size.y, {
        type: THREE.HalfFloatType, samples: tier.samples, generateMipmaps: tier.dof,
        minFilter: tier.dof ? THREE.LinearMipmapLinearFilter : THREE.LinearFilter, magFilter: THREE.LinearFilter,
        depthBuffer: true,
        ...(tier.dof ? { depthTexture: new THREE.DepthTexture(size.x, size.y, THREE.FloatType) } : {}),
      });
      this.composite.uniforms.uColor.value = this.hdr.texture;
      this.composite.uniforms.uDepth.value = this.hdr.depthTexture;
      this.composite.uniforms.uSize.value.copy(size);
      this.composite.uniforms.uMaxR.value = (tier.dof ? 5 : 0) * this.renderer.getPixelRatio();
      this.composite.uniforms.uAperture.value = 9 * this.renderer.getPixelRatio();
    }
    if (tier.mirror > 0) {
      this.mirror = new THREE.WebGLRenderTarget(Math.ceil(size.x * tier.mirror), Math.ceil(size.y * tier.mirror), {
        type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter, depthBuffer: true, samples: 0,
      });
      this.glass.uniforms.uReflect.value = this.mirror.texture;
    }
    this.glass.uniforms.uHasReflect.value = tier.mirror > 0 ? 1 : 0;
  }

  // The virtual camera behind the glass plane, y = 0. The result is looked up by projecting world points through it.
  private renderMirror() {
    const cam = this.camera, mc = this.mirrorCam;
    mc.fov = cam.fov; mc.aspect = cam.aspect; mc.near = cam.near; mc.far = cam.far;
    cam.updateMatrixWorld();
    const pos = new THREE.Vector3().setFromMatrixPosition(cam.matrixWorld);
    const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.getWorldQuaternion(new THREE.Quaternion()));
    const up = new THREE.Vector3(0, 1, 0).applyQuaternion(cam.getWorldQuaternion(new THREE.Quaternion()));
    mc.position.set(pos.x, -pos.y, pos.z);
    mc.up.set(up.x, -up.y, up.z);
    mc.lookAt(pos.x + dir.x, -(pos.y + dir.y), pos.z + dir.z);
    mc.updateProjectionMatrix();
    mc.updateMatrixWorld();
    const bias = new THREE.Matrix4().set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1);
    this.glass.uniforms.uTexMat.value.copy(bias).multiply(mc.projectionMatrix).multiply(mc.matrixWorldInverse);
    this.city.uniforms.uClipY.value = 0;
    this.renderer.setRenderTarget(this.mirror);
    this.renderer.clear();
    this.renderer.render(this.scene, mc);
    this.city.uniforms.uClipY.value = 1e9;
  }

  private renderFrame() {
    this.seed = (this.seed + 1) % 1024;
    const r = this.renderer;
    if (this.shadowsDirty) { r.shadowMap.needsUpdate = true; this.shadowsDirty = false; }
    if (this.mirror) this.renderMirror();
    if (this.hdr) {
      r.setRenderTarget(this.hdr);
      r.clear();
      r.render(this.scene, this.camera);
      r.setRenderTarget(null);
      const u = this.composite.uniforms;
      u.uFocus.value = Math.max(0.2, this.camera.position.distanceTo(this.robotPos));
      u.uSeed.value = this.seed;
      r.render(this.postScene, this.postCam);
    } else {
      r.setRenderTarget(null);
      r.render(this.scene, this.camera);
    }
  }

  // The camera glides after the robot so it stays in frame while the wall moves past. A viewer's orbit stays as an offset.
  private stepCamera(now: number) {
    if (!this.followed) return;
    const dt = Math.min(0.1, (now - this.lastTick) / 1000);
    const k = 1 - Math.exp(-dt * FOLLOW_RATE);
    const step = this.followTo.clone().sub(this.follow).multiplyScalar(k);
    if (step.lengthSq() > 1e-10) {
      this.follow.add(step);
      this.camera.position.add(step);
      this.controls.target.add(step);
      this.dirty = true;
    }
    // Stay in front of the glass.
    if (this.camera.position.y > -0.08) { this.camera.position.y = -0.08; this.dirty = true; }
  }

  // Drops one quality step when 90 frames average under about 30 fps. It never rises again in this view.
  private watchSpeed(now: number) {
    const dt = now - this.lastTick;
    if (dt > 800 || dt <= 0) return;
    this.frames++;
    this.slow += dt;
    if (this.frames < 90) return;
    const mean = this.slow / this.frames;
    this.frames = 0; this.slow = 0;
    if (mean > 34 && this.quality !== 'low') {
      this.quality = this.quality === 'high' ? 'medium' : 'low';
      this.host.dataset.quality = this.quality;
      const tier = TIERS[this.quality];
      this.composite.dispose();
      const old = this.composite;
      this.composite = compositeMaterial(this.reversed, tier.dof);
      this.composite.uniforms.uNearFar.value.copy(old.uniforms.uNearFar.value);
      this.composite.uniforms.uGrain.value = tier.grain;
      (this.postScene.children[0] as THREE.Mesh).material = this.composite;
      this.resize();
    }
  }

  sync() {
    const { data } = this.replay;
    const p = data.geom_xpos, r = data.geom_xmat;
    for (const { mesh, geom: i } of this.drawn) {
      const a = i * 9, b = i * 3;
      mesh.matrix.set(r[a], r[a + 1], r[a + 2], p[b], r[a + 3], r[a + 4], r[a + 5], p[b + 1], r[a + 6], r[a + 7], r[a + 8], p[b + 2], 0, 0, 0, 1);
    }
    // The robot takes its body pose straight from MuJoCo.
    const bp = data.xpos, bm = data.xmat, bi = this.robotBody * 3, ba = this.robotBody * 9;
    const root = this.robot.root;
    root.matrix.set(bm[ba], bm[ba + 1], bm[ba + 2], bp[bi], bm[ba + 3], bm[ba + 4], bm[ba + 5], bp[bi + 1], bm[ba + 6], bm[ba + 7], bm[ba + 8], bp[bi + 2], 0, 0, 0, 1);
    root.matrixWorld.copy(root.matrix);
    root.matrixWorldNeedsUpdate = true;
    this.robotPos.set(bp[bi], bp[bi + 1], bp[bi + 2]);
    this.host.dataset.drawnRobot = JSON.stringify([root.matrix.elements[12], root.matrix.elements[13], root.matrix.elements[14]].map(v => Number(v.toFixed(5))));

    // The contact shadow reads the same pose.
    const axX = bm[ba], axZ = bm[ba + 6], axLen = Math.hypot(axX, axZ) || 1;
    this.glass.uniforms.uRobot.value.set(this.robotPos.x, this.robotPos.z, axX / axLen, axZ / axLen);
    this.glass.uniforms.uRobotNear.value = 1 - Math.min(1, Math.max(0, (-this.robotPos.y - 0.04) / 0.4));

    this.sun.target.position.copy(this.robotPos);
    this.sun.position.copy(this.robotPos).add(new THREE.Vector3(-1.5, -2.2, 2.4));
    this.sun.target.updateMatrixWorld();
    this.shadowsDirty = true;

    // The tether: recorded end points. It leaves the robot at the tip of the boot, as in the film render.
    const s = data.site_xpos, a = new THREE.Vector3(s[this.anchorSite * 3], s[this.anchorSite * 3 + 1], s[this.anchorSite * 3 + 2]);
    const tip = this.robot.bootLocal.clone().applyMatrix4(root.matrix);
    const dir = a.clone().sub(tip), len = dir.length();
    const quat = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());
    const radius = 0.003;
    this.robot.tether.matrix.compose(tip, quat, new THREE.Vector3(radius, len, radius));
    this.robot.tether.matrixWorld.copy(this.robot.tether.matrix);

    // Follow target: the recorded position, kept inside the assigned area plus a margin.
    const area = this.trial.manifest.area;
    this.followTo.set(
      Math.min(area.x1 + FOLLOW_MARGIN_M, Math.max(area.x0 - FOLLOW_MARGIN_M, this.robotPos.x)), 0,
      Math.min(area.z1 + FOLLOW_MARGIN_M, Math.max(area.z0 - FOLLOW_MARGIN_M, this.robotPos.z)),
    );
    if (!this.followed) {
      this.followed = true;
      this.follow.copy(this.followTo);
      this.camera.position.copy(this.followTo).add(VIEW_FROM_ROBOT);
      this.controls.target.copy(this.followTo).add(LOOK_FROM_ROBOT);
      this.controls.update();
      this.camera.updateMatrixWorld();
    }

    if (this.path) (this.path.geometry as LineGeometry).instanceCount = Math.max(0, this.replay.frame - this.pathStart);
    this.syncDirt();
    this.dirty = true;
  }

  // One grid for each simulated second, from a replay that matched the recorded run. Blended between seconds.
  private fillDirt(index: number, tex: THREE.DataTexture) {
    const d = this.trial.manifest.dirt, nx = d.nx, nz = d.nz, w = nx + 2 * PAD, h = nz + 2 * PAD;
    const raw = this.trial.dirt, base = index * nx * nz, g = this.level, mask = this.dirtMask;
    let kept = 0, clean = 0;
    for (let i = 0; i < g.length; i++) {
      g[i] = raw[base + i] / d.scale / this.levelRef;
      if (!mask[i]) { kept++; if (raw[base + i] / d.scale <= d.clean_below) clean++; }
    }
    if (tex === this.dirtA) this.host.dataset.drawnClean = (clean / Math.max(1, kept)).toFixed(4);
    // Masked cells hold zero in the export. Fill each one from its neighbours along the row, then along the column.
    for (let z = 0; z < nz; z++) {
      for (let x = 0; x < nx; x++) {
        if (!mask[z * nx + x]) continue;
        let lo = x - 1, hi = x + 1;
        while (lo >= 0 && mask[z * nx + lo]) lo--;
        while (hi < nx && mask[z * nx + hi]) hi++;
        const a = lo >= 0 ? g[z * nx + lo] : -1, b = hi < nx ? g[z * nx + hi] : -1;
        if (a >= 0 && b >= 0) g[z * nx + x] = a + (b - a) * ((x - lo) / (hi - lo));
        else if (a >= 0 || b >= 0) g[z * nx + x] = Math.max(a, b);
        else {
          let dn = z - 1, up = z + 1;
          while (dn >= 0 && mask[dn * nx + x]) dn--;
          while (up < nz && mask[up * nx + x]) up++;
          const p = dn >= 0 ? g[dn * nx + x] : -1, q = up < nz ? g[up * nx + x] : -1;
          g[z * nx + x] = p >= 0 && q >= 0 ? (p + q) / 2 : Math.max(p, q, 0);
        }
      }
    }
    const out = tex.image.data as Uint8Array;
    const put = (x: number, z: number, v: number) => { out[z * w + x] = Math.min(255, Math.max(0, (v / 3) * 255)); };
    out.fill(85);
    for (let z = 0; z < nz; z++) for (let x = 0; x < nx; x++) put(x + PAD, z + PAD, g[z * nx + x]);
    // The ring outside the assigned area returns to a full film. A wiped edge cell stays a wiped edge.
    const edge = (v: number, layer: number) => { const fade = (layer + 1) / PAD; return v < 0.5 ? 1 : v * (1 - fade) + fade; };
    for (let layer = 0; layer < PAD; layer++) {
      for (let x = 0; x < nx; x++) { put(x + PAD, PAD - 1 - layer, edge(g[x], layer)); put(x + PAD, h - PAD + layer, edge(g[(nz - 1) * nx + x], layer)); }
      for (let z = 0; z < nz; z++) { put(PAD - 1 - layer, z + PAD, edge(g[z * nx], layer)); put(w - PAD + layer, z + PAD, edge(g[z * nx + nx - 1], layer)); }
    }
    tex.needsUpdate = true;
  }

  private syncDirt() {
    const { manifest: { dirt: d } } = this.trial;
    if (d.nx < 2 || d.nz < 2) return;
    const f = this.replay.frame / d.every_steps;
    const index = Math.min(d.count - 1, Math.floor(f));
    this.glass.uniforms.uDirtMix.value = index + 1 < d.count ? f - index : 0;
    if (index === this.dirtIndex) return;
    this.dirtIndex = index;
    this.fillDirt(index, this.dirtA);
    this.fillDirt(Math.min(d.count - 1, index + 1), this.dirtB);
  }
}
