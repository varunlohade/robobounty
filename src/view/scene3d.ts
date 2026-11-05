import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

// Draws every MuJoCo geom as a three.js mesh and syncs poses each frame.
export class Scene3D {
  renderer: THREE.WebGLRenderer; scene = new THREE.Scene(); camera: THREE.PerspectiveCamera;
  controls: OrbitControls; meshes: THREE.Mesh[] = []; model: any;

  constructor(el: HTMLElement, model: any) {
    this.model = model;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    el.appendChild(this.renderer.domElement);
    THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 20);
    this.camera.up.set(0, 0, 1);
    this.camera.position.set(1.35, -1.05, 1.15);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0.38, 0.02, 0.48);
    this.scene.background = new THREE.Color(0x1b1a24);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x333344, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 2.2);
    sun.position.set(0.8, -0.6, 2); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -1, right: 1, top: 1, bottom: -1 });
    this.scene.add(sun);
    this.build();
    const resize = () => { const w = el.clientWidth, h = el.clientHeight; this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix(); };
    new ResizeObserver(resize).observe(el); resize();
  }

  build() {
    const m = this.model;
    for (let i = 0; i < m.ngeom; i++) {
      const type = m.geom_type[i], s = [m.geom_size[i * 3], m.geom_size[i * 3 + 1], m.geom_size[i * 3 + 2]];
      let g: THREE.BufferGeometry;
      if (type === 0) g = new THREE.PlaneGeometry(s[0] * 2 || 4, s[1] * 2 || 4);
      else if (type === 2) g = new THREE.SphereGeometry(s[0], 24, 16);
      else if (type === 3) { g = new THREE.CapsuleGeometry(s[0], s[1] * 2, 8, 16); g.rotateX(Math.PI / 2); }
      else if (type === 5) { g = new THREE.CylinderGeometry(s[0], s[0], s[1] * 2, 24); g.rotateX(Math.PI / 2); }
      else if (type === 6) g = new THREE.BoxGeometry(s[0] * 2, s[1] * 2, s[2] * 2);
      else g = new THREE.SphereGeometry(0.01);
      const c = [m.geom_rgba[i * 4], m.geom_rgba[i * 4 + 1], m.geom_rgba[i * 4 + 2]];
      const mat = new THREE.MeshStandardMaterial({ color: new THREE.Color(c[0], c[1], c[2]), roughness: 0.6, metalness: 0.05 });
      const mesh = new THREE.Mesh(g, mat);
      mesh.matrixAutoUpdate = false; mesh.castShadow = type !== 0; mesh.receiveShadow = true;
      this.scene.add(mesh); this.meshes.push(mesh);
    }
  }

  sync(data: any) {
    const p = data.geom_xpos, r = data.geom_xmat, mtx = new THREE.Matrix4();
    for (let i = 0; i < this.meshes.length; i++) {
      const a = i * 9, b = i * 3;
      mtx.set(r[a], r[a + 1], r[a + 2], p[b], r[a + 3], r[a + 4], r[a + 5], p[b + 1], r[a + 6], r[a + 7], r[a + 8], p[b + 2], 0, 0, 0, 1);
      this.meshes[i].matrix.copy(mtx);
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }
}
