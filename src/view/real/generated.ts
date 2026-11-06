// Draws a generated object from its GLB in public/generated/, named by sha. The GLB is y up and any size. The returned group is z up, centred, with its longest side real_size_m, which is the frame the physics hulls use.
import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

const loader = new GLTFLoader();

export async function generatedModel(sha: string, realSizeM: number): Promise<THREE.Group> {
  if (!/^[0-9a-f]{64}$/.test(sha)) throw new Error('generated model: bad sha');
  const gltf = await loader.loadAsync(`/generated/${sha}.glb`);
  const box = new THREE.Box3().setFromObject(gltf.scene);
  const size = box.getSize(new THREE.Vector3());
  const scale = realSizeM / Math.max(size.x, size.y, size.z);
  gltf.scene.position.copy(box.getCenter(new THREE.Vector3()).multiplyScalar(-scale));
  gltf.scene.scale.setScalar(scale);
  gltf.scene.traverse(o => { if ((o as THREE.Mesh).isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  const upright = new THREE.Group();
  upright.rotation.x = Math.PI / 2;
  upright.add(gltf.scene);
  const placed = new THREE.Group();
  placed.add(upright);
  return placed;
}
