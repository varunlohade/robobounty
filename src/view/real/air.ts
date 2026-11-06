import * as THREE from 'three';

// Shared GLSL and values for the sky, the haze and the procedural detail. Art only. Nothing here feeds the physics.
export const HAZE = new THREE.Color(0.47, 0.5, 0.51);
export const SKY_LMAX = 3.5311; // White in the stored sky picture, in the HDRI's linear units.
export const SKY_URL = '/assets/sky/overcast_soil_top.jpg';

export const AIR_GLSL = /* glsl */`
uniform vec3 uHaze;
uniform sampler2D uNoise;
uniform float uFogK;
// Aerial perspective. The air gets thicker near the ground, with slow patches of mist over the streets.
float airAmount(vec3 w, vec3 cam) {
  float d = length(w - cam);
  float mist = texture2D(uNoise, w.xy / 1400.0 + vec2(0.13, 0.41)).r;
  float dens = 0.9 + (0.5 + 3.0 * smoothstep(0.34, 0.74, mist)) * exp(-max(w.z, 0.0) / 62.0);
  return 1.0 - exp(-d * dens * uFogK / 2300.0);
}
`;

export const HASH_GLSL = /* glsl */`
float hash12(vec2 p) { vec3 q = fract(vec3(p.xyx) * 0.1031); q += dot(q, q.yzx + 33.33); return fract((q.x + q.y) * q.z); }
`;

// Bakes one tile of grime on the GPU, once. Four metres on the wall. Tiles without a seam.
// R: cloudy blots. G: fine mottle and mineral specks. B: vertical run-off streaks. A: float-glass wave.
export function bakeGrime(renderer: THREE.WebGLRenderer, size: number): THREE.WebGLRenderTarget {
  const target = new THREE.WebGLRenderTarget(size, size, {
    type: THREE.UnsignedByteType, format: THREE.RGBAFormat, wrapS: THREE.RepeatWrapping, wrapT: THREE.RepeatWrapping,
    minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter, generateMipmaps: true, depthBuffer: false,
  });
  target.texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const mat = new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false, toneMapped: false,
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: /* glsl */`
      varying vec2 vUv;
      ${HASH_GLSL}
      float vnoise(vec2 p, vec2 period) {
        vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        float a = hash12(mod(i, period)), b = hash12(mod(i + vec2(1, 0), period));
        float c = hash12(mod(i + vec2(0, 1), period)), d = hash12(mod(i + vec2(1, 1), period));
        return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
      }
      float fbm(vec2 uv, vec2 scale, int octaves, float gain) {
        float sum = 0.0, amp = 0.5, norm = 0.0;
        vec2 s = scale;
        for (int i = 0; i < octaves; i++) { sum += amp * vnoise(uv * s + float(i) * 7.3, s); norm += amp; amp *= gain; s *= 2.0; }
        return sum / norm;
      }
      float specks(vec2 uv, float cells, float seed, float density) {
        vec2 p = uv * cells, id = floor(p), f = fract(p);
        float best = 0.0;
        for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
          vec2 c = id + vec2(x, y), w = mod(c, vec2(cells));
          float h = hash12(w + seed);
          if (h > density) continue;
          vec2 o = vec2(hash12(w + seed + 3.1), hash12(w + seed + 5.7));
          float r = 0.08 + 0.32 * hash12(w + seed + 9.3);
          best = max(best, 1.0 - smoothstep(r * 0.35, r, length(vec2(x, y) + o - f)));
        }
        return best;
      }
      void main() {
        float blots = fbm(vUv, vec2(5.0), 6, 0.58);
        float mottle = fbm(vUv, vec2(96.0), 4, 0.6);
        float fine = specks(vUv, 340.0, 1.0, 0.5) * 0.55 + specks(vUv, 120.0, 11.0, 0.32);
        float streakA = fbm(vUv, vec2(90.0, 3.0), 5, 0.62);
        float streakB = fbm(vUv + 0.37, vec2(260.0, 7.0), 3, 0.6);
        float wave = fbm(vUv, vec2(6.0, 2.0), 3, 0.45);
        gl_FragColor = vec4(blots, clamp(mottle * 0.62 + fine * 0.5, 0.0, 1.0), streakA * 0.7 + streakB * 0.3, wave);
      }`,
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(quad);
  const old = renderer.getRenderTarget();
  renderer.setRenderTarget(target);
  renderer.render(scene, new THREE.PerspectiveCamera());
  renderer.setRenderTarget(old);
  mat.dispose();
  quad.geometry.dispose();
  return target;
}

// The sky: the top half of the CC0 HDRI. Below the horizon it melts into the haze, as in the film render.
export function skyDome(texture: { value: THREE.Texture | null }): THREE.Mesh {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthTest: false, depthWrite: false, toneMapped: true,
    uniforms: { uSky: texture, uHaze: { value: HAZE }, uBlue: { value: 0 }, uBlueColor: { value: new THREE.Color() }, uHas: { value: 0 }, uSkyMix: { value: 0 }, uSkyLow: { value: new THREE.Color(1, 1, 1) }, uSkyHigh: { value: new THREE.Color(1, 1, 1) }, uSkyFog: { value: 0 } },
    vertexShader: `varying vec3 vDir; void main() { vDir = position; vec4 p = projectionMatrix * vec4(mat3(viewMatrix) * position, 1.0); gl_Position = p; }`,
    fragmentShader: /* glsl */`
      varying vec3 vDir;
      uniform sampler2D uSky; uniform vec3 uHaze, uSkyLow, uSkyHigh, uBlueColor; uniform float uHas, uSkyMix, uSkyFog, uBlue;
      const float PI = 3.14159265;
      void main() {
        vec3 d = normalize(vDir);
        float el = asin(clamp(d.z, -1.0, 1.0));
        float az = atan(d.y, d.x) + 0.7;
        vec2 uv = vec2(fract(az / (2.0 * PI)), clamp(el / (PI / 2.0), 0.0, 1.0));
        vec3 sky = uHas > 0.5 ? pow(texture2D(uSky, uv).rgb, vec3(2.2)) * ${SKY_LMAX.toFixed(4)} * 0.62 : uHaze * (1.2 + 0.8 * d.z);
        // Dusk and night: the same clouds, relit by a gradient from the horizon up.
        float cloud = clamp(dot(sky, vec3(0.33)) / 1.2, 0.0, 1.0);
        sky = mix(sky, mix(uSkyLow, uSkyHigh, pow(clamp(d.z, 0.0, 1.0), 0.45)) * (0.55 + 0.75 * cloud), uSkyMix);
        sky = mix(sky, uHaze, uSkyFog);
        float lift = smoothstep(-0.015, 0.11, d.z);
        gl_FragColor = vec4(mix(mix(uHaze, sky, lift), uBlueColor, uBlue), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const dome = new THREE.Mesh(new THREE.SphereGeometry(10, 48, 32), mat);
  dome.frustumCulled = false;
  dome.renderOrder = -10;
  return dome;
}

// Bakes one tile of water drops, once. Two metres on the wall. RG: the drop's slope. B: its coverage. A: a number that decides which drops a world's wetness shows.
export function bakeDrops(renderer: THREE.WebGLRenderer, size: number): THREE.WebGLRenderTarget {
  const target = new THREE.WebGLRenderTarget(size, size, {
    type: THREE.UnsignedByteType, format: THREE.RGBAFormat, wrapS: THREE.RepeatWrapping, wrapT: THREE.RepeatWrapping,
    minFilter: THREE.LinearMipmapLinearFilter, magFilter: THREE.LinearFilter, generateMipmaps: true, depthBuffer: false,
  });
  target.texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
  const mat = new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false, toneMapped: false,
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: /* glsl */`
      varying vec2 vUv;
      ${HASH_GLSL}
      void layer(vec2 uv, float cells, float seed, float maxR, inout vec4 out_) {
        vec2 p = uv * cells, id = floor(p), f = fract(p);
        for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++) {
          vec2 c = id + vec2(x, y), w = mod(c, vec2(cells));
          vec2 o = vec2(hash12(w + seed), hash12(w + seed + 3.7));
          float r = maxR * (0.35 + 0.65 * hash12(w + seed + 7.1));
          vec2 d = vec2(x, y) + o - f;
          d.y *= 0.85 + 0.25 * step(0.0, d.y);
          float l = length(d) / r;
          if (l < 1.0 && out_.b < 0.5) {
            vec2 n = d / r * pow(l, 1.2);
            out_ = vec4(n * 0.5 + 0.5, 1.0, hash12(w + seed + 13.0));
          }
        }
      }
      void main() {
        vec4 c = vec4(0.5, 0.5, 0.0, 1.0);
        layer(vUv, 34.0, 1.0, 0.3, c);
        layer(vUv, 70.0, 21.0, 0.3, c);
        layer(vUv, 150.0, 41.0, 0.28, c);
        gl_FragColor = c;
      }`,
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  quad.frustumCulled = false;
  const scene = new THREE.Scene();
  scene.add(quad);
  const old = renderer.getRenderTarget();
  renderer.setRenderTarget(target);
  renderer.render(scene, new THREE.PerspectiveCamera());
  renderer.setRenderTarget(old);
  mat.dispose();
  quad.geometry.dispose();
  return target;
}
