// One robot on nothing, for public/site/robot-*.png. It draws the same models the lab draws: buildRobot for the window robot, the exported meshes and a recorded pose for ANYmal C.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { buildRobot } from '../../view/real/robot.ts';

const W = 3200, H = 2400, OUT_W = 1200, OUT_H = 900, FADE = 0.06;
interface Pose { labels: string[]; q: number[] }
interface View { robot: 'window' | 'anymal'; pose?: Pose; ground: number; yaw: number; pitch: number; aim: number[]; dist: number; fov: number }

async function anymal(scene: THREE.Scene, pose: Pose) {
  const base = '/robots/anymal_c';
  const [model, bin] = await Promise.all([fetch(`${base}/robot.json`).then(r => r.json()), fetch(`${base}/robot.bin`).then(r => r.arrayBuffer())]);
  const { position, normal, uv, index } = model.layout;
  const positions = new THREE.BufferAttribute(new Float32Array(bin, position, model.vertices * 3), 3);
  const normals = new THREE.BufferAttribute(new Int8Array(bin, normal, model.vertices * 4), 4, true);
  const uvs = new THREE.BufferAttribute(new Float32Array(bin, uv, model.vertices * 2), 2);
  const indices = new THREE.BufferAttribute(new Uint32Array(bin, index, model.indices), 1);
  const bodies = new Map(pose.labels.map((label, i) => {
    const g = new THREE.Group();
    g.position.fromArray(pose.q, i * 7);
    g.quaternion.fromArray(pose.q, i * 7 + 3);
    scene.add(g);
    return [label, g] as const;
  }));
  const loader = new THREE.TextureLoader();
  const waits: Promise<unknown>[] = [];
  for (const part of model.parts) {
    const material = new THREE.MeshStandardMaterial({ color: new THREE.Color().setRGB(part.colour[0], part.colour[1], part.colour[2]), roughness: 0.6 });
    if (part.texture) waits.push(loader.loadAsync(`${base}/textures/${encodeURIComponent(part.texture)}`).then(map => {
      map.colorSpace = THREE.SRGBColorSpace;
      map.anisotropy = 16;
      material.map = map;
      material.needsUpdate = true;
    }));
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', positions);
    g.setAttribute('normal', normals);
    g.setAttribute('uv', uvs);
    g.setIndex(indices);
    g.setDrawRange(part.first_index, part.index_count);
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1.5);
    const mesh = new THREE.Mesh(g, material);
    mesh.castShadow = mesh.receiveShadow = true;
    bodies.get(part.body)?.add(mesh);
  }
  await Promise.all(waits);
}

// A soft dark pool under the robot, so it stands on something without a floor.
function contactPool(ground: number, rx: number, ry: number) {
  const c = document.createElement('canvas');
  c.width = c.height = 512;
  const x = c.getContext('2d')!;
  const g = x.createRadialGradient(256, 256, 0, 256, 256, 256);
  g.addColorStop(0, 'rgba(0,0,0,.26)'); g.addColorStop(0.55, 'rgba(0,0,0,.12)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g;
  x.fillRect(0, 0, 512, 512);
  const m = new THREE.Mesh(new THREE.PlaneGeometry(rx * 2, ry * 2), new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false, toneMapped: false }));
  m.position.z = ground;
  return m;
}

async function draw(v: View): Promise<string> {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H);
  renderer.setClearColor(0, 0);
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.03).texture;
  scene.environmentIntensity = v.robot === 'window' ? 0.5 : 0.62;
  const aim = new THREE.Vector3().fromArray(v.aim);
  const size = v.robot === 'window' ? 0.5 : 1.1;
  const key = new THREE.DirectionalLight(0xfff6ec, v.robot === 'window' ? 1.45 : 2.1);
  key.position.set(aim.x + Math.cos(v.yaw + 0.8) * 1.1, aim.y + Math.sin(v.yaw + 0.8) * 1.1, aim.z + 4);
  key.target.position.copy(aim);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.radius = 9;
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.002;
  Object.assign(key.shadow.camera, { left: -size, right: size, top: size, bottom: -size, near: 0.1, far: 8 });
  const fill = new THREE.DirectionalLight(0xe6efff, v.robot === 'window' ? 0.3 : 0.6);
  fill.position.set(aim.x + Math.cos(v.yaw - 1.2) * 2, aim.y + Math.sin(v.yaw - 1.2) * 2, aim.z + 1);
  fill.target.position.copy(aim);
  scene.add(key, key.target, fill, fill.target);
  if (v.robot === 'window') {
    const robot = buildRobot(renderer);
    robot.root.traverse(o => { if (o instanceof THREE.Mesh) o.castShadow = o.receiveShadow = true; });
    robot.root.children[1].scale.y = 0.97; // Picture only: the tracks poke 2 mm through the body's rounded corners. Up close that reads as a chip.
    scene.add(robot.root);
    scene.add(contactPool(v.ground, 0.29, 0.29));
  } else {
    await anymal(scene, v.pose!);
    scene.add(contactPool(v.ground, 0.72, 0.46));
  }
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(10, 10), new THREE.ShadowMaterial({ opacity: 0.14 }));
  floor.position.z = v.ground;
  floor.receiveShadow = true;
  scene.add(floor);
  const camera = new THREE.PerspectiveCamera(v.fov, W / H, 0.05, 30);
  camera.up.set(0, 0, 1);
  camera.position.set(aim.x + v.dist * Math.cos(v.pitch) * Math.cos(v.yaw), aim.y + v.dist * Math.cos(v.pitch) * Math.sin(v.yaw), aim.z + v.dist * Math.sin(v.pitch));
  camera.lookAt(aim);
  renderer.render(scene, camera);
  // Crop to the opaque robot, then scale down: the scale-down is the final anti-aliasing.
  const big = document.createElement('canvas');
  big.width = W; big.height = H;
  const bx = big.getContext('2d', { willReadFrequently: true })!;
  bx.drawImage(renderer.domElement, 0, 0);
  const a = bx.getImageData(0, 0, W, H).data;
  let x0 = W, x1 = 0, y0 = H, y1 = 0;
  for (let y = 0; y < H; y += 2) for (let x = 0; x < W; x += 2) if (a[(y * W + x) * 4 + 3] > 200) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const MARGIN = v.robot === 'window' ? 0.17 : 0.1;
  const scale = Math.min((OUT_W * (1 - 2 * MARGIN)) / (x1 - x0), (OUT_H * (1 - 2 * MARGIN)) / (y1 - y0));
  const out = document.createElement('canvas');
  out.width = OUT_W; out.height = OUT_H;
  const ox = out.getContext('2d')!;
  ox.imageSmoothingQuality = 'high';
  ox.drawImage(big, OUT_W / 2 - ((x0 + x1) / 2) * scale, OUT_H / 2 - ((y0 + y1) / 2) * scale, W * scale, H * scale);
  // The floor shadow must end before the edge of the picture, or the page shows a straight line.
  ox.globalCompositeOperation = 'destination-in';
  for (const [x, y] of [[OUT_W, 0], [0, OUT_H]]) {
    const g = ox.createLinearGradient(0, 0, x, y);
    g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(FADE, '#000'); g.addColorStop(1 - FADE, '#000'); g.addColorStop(1, 'rgba(0,0,0,0)');
    ox.fillStyle = g;
    ox.fillRect(0, 0, OUT_W, OUT_H);
  }
  renderer.dispose();
  return `${x1 - x0}x${y1 - y0}@${scale.toFixed(3)}|${out.toDataURL('image/png')}`;
}

Object.assign(window, { drawRobot: draw });
document.title = 'ready';
