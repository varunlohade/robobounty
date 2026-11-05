import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import type { Replay } from './replay.ts';
import type { Trial } from './trial.ts';

const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const PATH_OFF_GLASS_M = 0.004;
const DUST_OFF_GLASS_M = 0.002;

// Draws every MuJoCo geom with three.js and copies poses from MjData. It draws what MuJoCo computes.
export class SimView {
  renderer: THREE.WebGLRenderer; scene = new THREE.Scene(); camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  private meshes: THREE.Mesh[] = [];
  private tether: THREE.Line;
  private path: THREE.Line | null = null;
  private pathStart = 0;
  private dust: THREE.DataTexture;
  private dustIndex = -1;
  private dustColor: THREE.Color;
  private anchorSite: number; private robotSite: number;
  private dirty = true;

  constructor(private host: HTMLElement, private replay: Replay, private trial: Trial) {
    const area = trial.manifest.area;
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setClearColor(new THREE.Color(token('--sim-sky')));
    host.prepend(this.renderer.domElement);

    const cx = (area.x0 + area.x1) / 2, cz = (area.z0 + area.z1) / 2;
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 3000);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(cx - 0.9, -6.8, cz + 0.6);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(cx, 0, cz);
    this.controls.addEventListener('change', () => { this.dirty = true; });

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, Number(token('--sim-hemi'))));
    const { model } = replay;
    const sun = new THREE.DirectionalLight(new THREE.Color(token('--sim-light')), Number(token('--sim-sun')));
    sun.position.set(cx - model.light_dir[0] * 20, -model.light_dir[1] * 20, cz - model.light_dir[2] * 20);
    sun.target.position.set(cx, 0, cz);
    this.scene.add(sun, sun.target);

    this.buildGeoms();
    const mj = replay.mj;
    this.anchorSite = mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE.value, 'anchor');
    this.robotSite = mj.mj_name2id(model, mj.mjtObj.mjOBJ_SITE.value, 'tether_point');

    const tetherId = mj.mj_name2id(model, mj.mjtObj.mjOBJ_TENDON.value, 'tether');
    const tetherMat = model.tendon_matid[tetherId];
    this.tether = new THREE.Line(
      new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]),
      new THREE.LineBasicMaterial({ color: this.materialColor(tetherMat) }),
    );
    this.tether.frustumCulled = false;
    this.scene.add(this.tether);

    const { nx, nz } = trial.manifest.dirt;
    this.dustColor = new THREE.Color(token('--sim-dust'));
    this.dust = new THREE.DataTexture(new Uint8Array(nx * nz * 4), nx, nz, THREE.RGBAFormat);
    this.dust.magFilter = this.dust.minFilter = THREE.NearestFilter;
    this.dust.colorSpace = THREE.SRGBColorSpace;
    const dustGeom = new THREE.PlaneGeometry(area.x1 - area.x0, area.z1 - area.z0);
    dustGeom.rotateX(Math.PI / 2);
    const dustMesh = new THREE.Mesh(dustGeom, new THREE.MeshBasicMaterial({ map: this.dust, transparent: true, depthWrite: false }));
    dustMesh.position.set(cx, -DUST_OFF_GLASS_M, cz);
    this.scene.add(dustMesh);

    const firedTimes = Object.values(trial.result.fired).map(f => f.t);
    if (firedTimes.length) {
      this.pathStart = Math.round(Math.min(...firedTimes) * trial.manifest.hz);
      const points = replay.path();
      for (let i = 1; i < points.length; i += 3) points[i] -= PATH_OFF_GLASS_M;
      const pathGeom = new THREE.BufferGeometry();
      pathGeom.setAttribute('position', new THREE.BufferAttribute(points, 3));
      this.path = new THREE.Line(pathGeom, new THREE.LineBasicMaterial({ color: new THREE.Color(token('--fail')) }));
      this.path.frustumCulled = false;
      this.scene.add(this.path);
    }

    new ResizeObserver(() => this.resize()).observe(host);
    this.resize();
    const loop = () => {
      this.controls.update();
      if (this.dirty && host.clientWidth > 0) { this.dirty = false; this.renderer.render(this.scene, this.camera); }
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  private materialColor(mat: number): THREE.Color {
    const c = this.replay.model.mat_rgba;
    return new THREE.Color(c[mat * 4], c[mat * 4 + 1], c[mat * 4 + 2]);
  }

  private buildGeoms() {
    const m = this.replay.model;
    for (let i = 0; i < m.ngeom; i++) {
      const type = m.geom_type[i], s = [m.geom_size[i * 3], m.geom_size[i * 3 + 1], m.geom_size[i * 3 + 2]];
      let g: THREE.BufferGeometry;
      if (type === 0) g = new THREE.PlaneGeometry(s[0] * 2, s[1] * 2);
      else if (type === 2) g = new THREE.SphereGeometry(s[0], 24, 16);
      else if (type === 3) { g = new THREE.CapsuleGeometry(s[0], s[1] * 2, 8, 16); g.rotateX(Math.PI / 2); }
      else if (type === 5) { g = new THREE.CylinderGeometry(s[0], s[0], s[1] * 2, 32); g.rotateX(Math.PI / 2); }
      else if (type === 6) g = new THREE.BoxGeometry(s[0] * 2, s[1] * 2, s[2] * 2);
      else throw new Error(`geom ${i}: type ${type} has no drawing code`);
      const mat = m.geom_matid[i];
      const color = mat >= 0 ? this.materialColor(mat) : new THREE.Color(m.geom_rgba[i * 4], m.geom_rgba[i * 4 + 1], m.geom_rgba[i * 4 + 2]);
      const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0.05 }));
      mesh.matrixAutoUpdate = false;
      this.scene.add(mesh);
      this.meshes.push(mesh);
    }
  }

  private resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.dirty = true;
  }

  sync() {
    const { data } = this.replay;
    const p = data.geom_xpos, r = data.geom_xmat;
    for (let i = 0; i < this.meshes.length; i++) {
      const a = i * 9, b = i * 3;
      this.meshes[i].matrix.set(r[a], r[a + 1], r[a + 2], p[b], r[a + 3], r[a + 4], r[a + 5], p[b + 1], r[a + 6], r[a + 7], r[a + 8], p[b + 2], 0, 0, 0, 1);
    }
    const s = data.site_xpos, pos = this.tether.geometry.attributes.position as THREE.BufferAttribute;
    pos.setXYZ(0, s[this.anchorSite * 3], s[this.anchorSite * 3 + 1], s[this.anchorSite * 3 + 2]);
    pos.setXYZ(1, s[this.robotSite * 3], s[this.robotSite * 3 + 1], s[this.robotSite * 3 + 2]);
    pos.needsUpdate = true;
    this.path?.geometry.setDrawRange(this.pathStart, Math.max(0, this.replay.frame + 1 - this.pathStart));
    this.syncDust();
    this.dirty = true;
  }

  // The dirt grid is stored once per simulated second, from a replay that matched the recorded run.
  private syncDust() {
    const { dirt, manifest } = this.trial;
    const d = manifest.dirt;
    const index = Math.min(d.count - 1, Math.floor(this.replay.frame / d.every_steps));
    if (index === this.dustIndex) return;
    this.dustIndex = index;
    const size = d.nx * d.nz;
    const pixels = this.dust.image.data as Uint8Array;
    const color = this.dustColor.clone().convertLinearToSRGB();
    const rgb = [color.r * 255, color.g * 255, color.b * 255];
    for (let i = 0; i < size; i++) {
      const level = dirt[index * size + i] / d.scale;
      const clean = level <= d.clean_below;
      pixels[i * 4] = rgb[0]; pixels[i * 4 + 1] = rgb[1]; pixels[i * 4 + 2] = rgb[2];
      pixels[i * 4 + 3] = clean ? 0 : Math.min(235, 110 + 110 * level);
    }
    this.dust.needsUpdate = true;
  }
}
