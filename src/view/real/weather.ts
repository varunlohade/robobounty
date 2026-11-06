import * as THREE from 'three';
import { HASH_GLSL } from './air.ts';

// Moving air on screen. Wind speed comes from the run's record and its direction from the world. Rain, snow and dust are scenery on that wind. Nothing here feeds the physics.
// Everything moves at real speed in metres per wall-clock second, whatever the replay speed is, so a streak's speed reads as the recorded wind.
const STREAK_SECONDS = 0.07; // A streak's length is the distance its air moves in this time.
const RAIN_FALL_MS = 9;
const SNOW_FALL_MS = 1.1;
export const CALM_MS = 1; // Below this no streak shows.
const FULL_MS = 10; // At this wind all streaks show.

export function streakShare(speed: number): number {
  return speed < CALM_MS ? 0 : Math.min(1, (speed - CALM_MS) / (FULL_MS - CALM_MS));
}

const VERT = /* glsl */`
attribute vec4 aSeed;
uniform vec3 uCenter, uBox, uOffset, uTail, uSway;
uniform float uWidth, uShow, uTime, uBlob, uPixel;
varying vec2 vQ;
varying float vFade, vRnd;
void main() {
  vec3 rel = mod(aSeed.xyz * uBox + uOffset - uCenter + uBox * 0.5, uBox) - uBox * 0.5;
  vec3 w = uCenter + rel + uSway * vec3(sin(uTime * (0.7 + aSeed.w) + aSeed.w * 41.0), cos(uTime * (0.9 + aSeed.w) + aSeed.w * 17.0), sin(uTime * (0.5 + aSeed.w) + aSeed.w * 29.0));
  vec3 head = (viewMatrix * vec4(w, 1.0)).xyz;
  vec3 at;
  if (uBlob > 0.5) {
    float big = fract(aSeed.w * 13.7);
    at = head + vec3(position.xy * 2.0, 0.0) * max(uWidth * (0.5 + 1.6 * big * big * big), uPixel * -head.z * 0.9);
  } else {
    vec3 axis = (viewMatrix * vec4(-uTail, 0.0)).xyz;
    vec3 side = normalize(cross(axis, head) + vec3(1e-5, 0.0, 0.0));
    at = head + axis * (position.y + 0.5) + side * position.x * 2.0 * max(uWidth, uPixel * -head.z * 0.8);
  }
  vQ = position.xy * 2.0;
  vRnd = aSeed.w;
  vFade = (1.0 - smoothstep(0.7, 1.0, length(rel / (uBox * 0.5)))) * smoothstep(0.5, 2.2, -head.z);
  gl_Position = aSeed.w < uShow ? projectionMatrix * vec4(at, 1.0) : vec4(2.0, 2.0, 2.0, 1.0);
}`;

const FRAG = /* glsl */`
uniform vec3 uColor;
uniform float uAlpha, uBlob, uPuff;
uniform sampler2D uNoise;
varying vec2 vQ;
varying float vFade, vRnd;
${HASH_GLSL}
void main() {
  float a;
  if (uBlob > 0.5) {
    a = 1.0 - smoothstep(0.2, 1.0, length(vQ));
    if (uPuff > 0.5) a *= smoothstep(0.25, 0.75, texture2D(uNoise, vQ * 0.09 + vRnd).r);
  } else {
    a = (1.0 - abs(vQ.x)) * smoothstep(1.0, 0.5, vQ.y) * smoothstep(-1.0, 0.1, vQ.y);
  }
  gl_FragColor = vec4(uColor, a * uAlpha * vFade);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

interface Spec { count: number; box: [number, number, number]; blob?: boolean; puff?: boolean; width: number; color: [number, number, number]; alpha: number; sway?: number }
const SPECS = {
  wind: { count: 1500, box: [24, 14, 12], width: 0.005, color: [2.8, 2.9, 3], alpha: 0.6 },
  rain: { count: 3400, box: [20, 12, 14], width: 0.0045, color: [1.5, 1.7, 1.9], alpha: 0.6 },
  snow: { count: 7000, box: [14, 10, 10], blob: true, width: 0.011, color: [3.2, 3.3, 3.4], alpha: 0.9, sway: 0.22 },
  grit: { count: 4500, box: [18, 12, 10], width: 0.004, color: [2.2, 1.55, 0.9], alpha: 0.5 },
  puff: { count: 110, box: [70, 44, 34], blob: true, puff: true, width: 7, color: [1.15, 0.8, 0.46], alpha: 0.5 },
} satisfies Record<string, Spec>;
type Name = keyof typeof SPECS;

class Layer {
  mesh: THREE.Mesh; mat: THREE.ShaderMaterial; offset = new THREE.Vector3();
  constructor(private spec: Spec, noise: { value: THREE.Texture | null }, seedStart: number) {
    const geo = new THREE.InstancedBufferGeometry();
    const quad = new THREE.PlaneGeometry(1, 1);
    geo.index = quad.index;
    geo.setAttribute('position', quad.getAttribute('position'));
    const seeds = new Float32Array(spec.count * 4);
    // A fixed sequence, so a view looks the same each time.
    let s = seedStart;
    for (let i = 0; i < seeds.length; i++) { s = (s * 16807) % 2147483647; seeds[i] = (s - 1) / 2147483646; }
    geo.setAttribute('aSeed', new THREE.InstancedBufferAttribute(seeds, 4));
    geo.instanceCount = spec.count;
    this.mat = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, toneMapped: true, side: THREE.DoubleSide,
      uniforms: {
        uCenter: { value: new THREE.Vector3() }, uBox: { value: new THREE.Vector3(...spec.box) }, uOffset: { value: new THREE.Vector3() }, uTail: { value: new THREE.Vector3() }, uSway: { value: new THREE.Vector3().setScalar(spec.sway ?? 0) },
        uWidth: { value: spec.width }, uShow: { value: 0 }, uTime: { value: 0 }, uPixel: { value: 0 }, uBlob: { value: spec.blob ? 1 : 0 }, uPuff: { value: spec.puff ? 1 : 0 },
        uColor: { value: new THREE.Color(...spec.color) }, uAlpha: { value: spec.alpha }, uNoise: noise,
      },
    });
    this.mesh = new THREE.Mesh(geo, this.mat);
    this.mesh.frustumCulled = false;
    this.mesh.visible = false;
  }
  // Moves the layer's air by velocity x dt. show is the share of particles drawn.
  step(dt: number, velocity: THREE.Vector3, center: THREE.Vector3, show: number, time: number, tailSeconds: number, light: number, pixel: number) {
    this.mesh.visible = show > 0;
    if (!this.mesh.visible) return;
    const u = this.mat.uniforms, box = u.uBox.value as THREE.Vector3;
    this.offset.addScaledVector(velocity, dt);
    this.offset.set(this.offset.x % box.x, this.offset.y % box.y, this.offset.z % box.z);
    u.uOffset.value.copy(this.offset);
    u.uTail.value.copy(velocity).multiplyScalar(tailSeconds);
    u.uCenter.value.copy(center);
    u.uShow.value = show;
    u.uTime.value = time;
    u.uPixel.value = pixel;
    u.uColor.value.setRGB(...this.spec.color).multiplyScalar(light);
  }
  dispose() { this.mesh.geometry.dispose(); this.mat.dispose(); }
}

export class Weather {
  group = new THREE.Group();
  private layers: Record<Name, Layer>;
  private forward = new THREE.Vector3(); private center = new THREE.Vector3(); private velocity = new THREE.Vector3();
  private on = { rain: false, snow: false, dust: false };
  private light = 1;
  // Total metres the wind layer has moved. A check reads this against the record.
  travel = 0;
  speed = 0; dirDeg = 0; streaks = 0;

  constructor(noise: { value: THREE.Texture | null }) {
    let seed = 7;
    this.layers = {} as Record<Name, Layer>;
    for (const name of Object.keys(SPECS) as Name[]) {
      seed += 1009;
      this.layers[name] = new Layer(SPECS[name], noise, seed);
      this.group.add(this.layers[name].mesh);
    }
    this.layers.puff.mesh.renderOrder = 1; this.layers.wind.mesh.renderOrder = 2; this.layers.grit.mesh.renderOrder = 2; this.layers.rain.mesh.renderOrder = 3; this.layers.snow.mesh.renderOrder = 3;
  }

  setAir(on: { rain: boolean; snow: boolean; dust: boolean }, light: number) { this.on = on; this.light = light; }

  /** True when something on screen moves, so the view keeps drawing. pixel is one screen pixel's width at one metre: the thinnest line stays that wide. */
  step(dt: number, speed: number, dirDeg: number, camera: THREE.Camera, time: number, pixel: number): boolean {
    const { on, layers, velocity: v, light } = this;
    const a = (dirDeg * Math.PI) / 180;
    // The sim's axes: x along the wall, +y into the wall.
    const wx = speed * Math.cos(a), wy = speed * Math.sin(a);
    this.speed = speed; this.dirDeg = dirDeg;
    this.travel += speed * dt;
    camera.getWorldDirection(this.forward);
    const ahead = (name: Name) => this.center.copy(camera.position).addScaledVector(this.forward, SPECS[name].box[0] * 0.3);
    const share = streakShare(speed);
    this.streaks = Math.round(share * SPECS.wind.count);
    layers.wind.step(dt, v.set(wx, wy, 0), ahead('wind'), share, time, STREAK_SECONDS, light, pixel);
    layers.rain.step(dt, v.set(wx, wy, -RAIN_FALL_MS), ahead('rain'), on.rain ? 1 : 0, time, 0.05, light, pixel);
    layers.snow.step(dt, v.set(wx, wy, -SNOW_FALL_MS), ahead('snow'), on.snow ? 1 : 0, time, 0, light, pixel);
    layers.grit.step(dt, v.set(wx + 0.6, wy, -0.05), ahead('grit'), on.dust ? 1 : 0, time, STREAK_SECONDS, light, pixel);
    layers.puff.step(dt, v.set(wx + 0.6, wy, 0), ahead('puff'), on.dust ? 1 : 0, time, 0, light, pixel);
    return share > 0 || on.rain || on.snow || on.dust;
  }

  dispose() { for (const l of Object.values(this.layers)) l.dispose(); }
}
