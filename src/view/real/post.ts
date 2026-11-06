import * as THREE from 'three';

// The last pass: a lens (depth of field that does not bleed sharp edges), a small grade, ACES, sRGB, a little film grain.
export function compositeMaterial(reversed: boolean, dof: boolean) {
  return new THREE.ShaderMaterial({
    depthTest: false, depthWrite: false, toneMapped: true,
    defines: { TAPS: 22, ...(dof ? { USE_DOF: 1 } : {}), ...(reversed ? { REVERSED: 1 } : {}) },
    uniforms: {
      uColor: { value: null as THREE.Texture | null }, uDepth: { value: null as THREE.Texture | null },
      uFocus: { value: 2 }, uAperture: { value: 18 }, uMaxR: { value: 14 }, uNearFar: { value: new THREE.Vector2(0.05, 30000) },
      uSize: { value: new THREE.Vector2(1, 1) }, uGrain: { value: 0.012 }, uSeed: { value: 0 },
    },
    vertexShader: `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`,
    fragmentShader: /* glsl */`
      varying vec2 vUv;
      uniform sampler2D uColor, uDepth;
      uniform float uFocus, uAperture, uMaxR, uGrain, uSeed;
      uniform vec2 uNearFar, uSize;
      float linearZ(vec2 uv) {
        float d = texture2D(uDepth, uv).r;
        #ifdef REVERSED
          return uNearFar.x * uNearFar.y / (d * (uNearFar.y - uNearFar.x) + uNearFar.x);
        #else
          return uNearFar.x * uNearFar.y / (uNearFar.y - d * (uNearFar.y - uNearFar.x));
        #endif
      }
      // Circle of confusion in pixels. A thin lens: it depends on 1/z - 1/focus.
      float coc(float z) { return min(uMaxR, abs(1.0 / z - 1.0 / uFocus) * uAperture); }
      float ign(vec2 p) { return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715)))); }
      void main() {
        vec3 col;
        #ifdef USE_DOF
          float z0 = linearZ(vUv), c0 = coc(z0);
          if (c0 < 0.6) col = texture2D(uColor, vUv).rgb;
          else {
            float lod = max(0.0, log2(c0 / 6.0));
            vec3 sum = textureLod(uColor, vUv, lod).rgb; float wsum = 1.0;
            float rot = ign(gl_FragCoord.xy) * 6.2831853;
            for (int i = 1; i <= TAPS; i++) {
              float fi = float(i), r = sqrt(fi / float(TAPS)) * c0, a = fi * 2.3999632 + rot;
              vec2 uv = vUv + vec2(cos(a), sin(a)) * r / uSize;
              float zs = linearZ(uv), cs = coc(zs);
              // A nearer, sharper sample must not smear over a blurred background.
              float w = zs < z0 - 0.02 ? smoothstep(r - 1.0, r + 1.0, cs) : 1.0;
              sum += textureLod(uColor, uv, lod).rgb * w; wsum += w;
            }
            col = sum / wsum;
          }
        #else
          col = texture2D(uColor, vUv).rgb;
        #endif
        float l = dot(col, vec3(0.2126, 0.7152, 0.0722));
        col = mix(vec3(l), col, 0.88);
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        float g = fract(sin(dot(gl_FragCoord.xy + uSeed, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
        float gl = dot(gl_FragColor.rgb, vec3(0.33));
        gl_FragColor.rgb += g * uGrain * (0.6 + 1.4 * (1.0 - gl)) ;
      }`,
  });
}
