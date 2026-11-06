import * as THREE from 'three';
import { AIR_GLSL, HASH_GLSL, HAZE } from './air.ts';

// The curtain wall. Its pane lines come from the MJCF's mullion and transom geoms. The film on it comes from the recorded dirt grid.
export interface FacadeGrid { spacingX: number; offsetX: number; spacingZ: number; offsetZ: number; x0: number; x1: number; z1: number }

export function glassMaterial(noise: { value: THREE.Texture | null }, drops: { value: THREE.Texture | null }, grid: FacadeGrid) {
  return new THREE.ShaderMaterial({
    toneMapped: true,
    uniforms: {
      uHaze: { value: HAZE }, uNoise: noise, uDrops: drops,
      uReflect: { value: null as THREE.Texture | null }, uTexMat: { value: new THREE.Matrix4() }, uHasReflect: { value: 0 },
      uEnvFlat: { value: new THREE.Color(0.5, 0.54, 0.55) },
      uDirtA: { value: null as THREE.Texture | null }, uDirtB: { value: null as THREE.Texture | null }, uDirtMix: { value: 0 },
      uDirtRect: { value: new THREE.Vector4(0, 0, 1, 1) }, uDirtSize: { value: new THREE.Vector2(1, 1) },
      uClean: { value: new THREE.Vector2(0.1, 0.34) }, uFilm: { value: 0.8 }, uWet: { value: 0.2 },
      uGrid: { value: new THREE.Vector4(grid.offsetX, grid.spacingX, grid.offsetZ, grid.spacingZ) },
      uRobot: { value: new THREE.Vector4(0, 0, 1, 0) }, uRobotNear: { value: 1 }, uFilmTop: { value: 1 }, uFogK: { value: 1 },
      // The look. As built, these change nothing.
      uBody: { value: new THREE.Color(0, 0, 0) }, uBodyLight: { value: new THREE.Color(1, 1, 1) }, uBodyAmt: { value: 0 }, uReflKeep: { value: 1 }, uFilmKeep: { value: 1 },
      uSnow: { value: 0 }, uRain: { value: 0 }, uTime: { value: 0 }, uDropBack: { value: 0 }, uDustFilm: { value: 0 },
      uTint: { value: new THREE.Color(1, 1, 1) }, uTintGlow: { value: new THREE.Color(0, 0, 0) }, uFrit: { value: new THREE.Color(0.01, 0.011, 0.012) }, uRooms: { value: 0 },
    },
    vertexShader: `varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`,
    fragmentShader: /* glsl */`
      varying vec3 vW;
      uniform sampler2D uReflect, uDirtA, uDirtB, uDrops;
      uniform mat4 uTexMat;
      uniform float uHasReflect, uDirtMix, uFilm, uWet, uRobotNear, uBodyAmt, uReflKeep, uFilmKeep, uRooms, uSnow, uRain, uTime, uDropBack, uDustFilm;
      uniform vec3 uEnvFlat, uBody, uBodyLight, uTint, uTintGlow, uFrit;
      uniform vec4 uDirtRect, uGrid, uRobot;
      uniform vec2 uDirtSize, uClean;
      ${AIR_GLSL}
      ${HASH_GLSL}
      // Smooth (B-spline) lookup of the 5 cm grid. It rounds the cell corners without moving a clean edge.
      float bicubic(sampler2D t, vec2 uv) {
        vec2 p = uv * uDirtSize - 0.5, i = floor(p), f = p - i, f2 = f * f, f3 = f2 * f;
        vec2 w0 = (1.0 - 3.0 * f + 3.0 * f2 - f3) / 6.0, w1 = (4.0 - 6.0 * f2 + 3.0 * f3) / 6.0, w2 = (1.0 + 3.0 * f + 3.0 * f2 - 3.0 * f3) / 6.0, w3 = f3 / 6.0;
        vec2 g0 = w0 + w1, g1 = w2 + w3;
        vec2 h0 = (i - 0.5 + w1 / g0 + 0.5) / uDirtSize, h1 = (i + 1.5 + w3 / g1 + 0.5) / uDirtSize;
        return (texture2D(t, vec2(h0.x, h0.y)).r * g0.x + texture2D(t, vec2(h1.x, h0.y)).r * g1.x) * g0.y + (texture2D(t, vec2(h0.x, h1.y)).r * g0.x + texture2D(t, vec2(h1.x, h1.y)).r * g1.x) * g1.y;
      }
      float roundBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
      void main() {
        vec2 p = vW.xz;
        vec2 gr = (p - uGrid.xz) / uGrid.yw;
        vec2 id = floor(gr);
        vec2 bar = abs(fract(gr + 0.5) - 0.5) * uGrid.yw;
        float rnd = hash12(id + 17.0), rnd2 = hash12(id + 41.0), rnd3 = hash12(id + 83.0);
        vec3 V = normalize(cameraPosition - vW);
        float ndv = max(abs(V.y), 0.02);

        // Each pane sits at its own tiny angle and the float glass rolls a little, so reflections break at every joint.
        vec2 tileUv = p / 4.0 + vec2(rnd, rnd2);
        vec4 tile = texture2D(uNoise, tileUv);
        vec4 wide = texture2D(uNoise, p * vec2(0.13, 0.05) + rnd3);
        vec2 tilt = (vec2(rnd2, rnd3) - 0.5) * 0.008 + (vec2(wide.a, texture2D(uNoise, p * vec2(0.09, 0.04) + rnd2).a) - 0.5) * 0.012;

        // Recorded dirt: relative to the run's mean start level. Outside the padded grid there is no record, so the wall keeps the start film.
        vec2 du = (p - uDirtRect.xy) / uDirtRect.zw;
        float level = 1.0;
        if (du.x > 0.0 && du.x < 1.0 && du.y > 0.0 && du.y < 1.0) level = mix(bicubic(uDirtA, du), bicubic(uDirtB, du), uDirtMix) * 3.0;
        float mask = smoothstep(uClean.x, uClean.y, level);

        // Water on the glass, as much as this world's wetness says. Each drop bends the reflection through itself.
        // Picture only: drops go where the recording shows the robot cleaned. The sim's wetness stays constant, so grip does not change after a pass. In rain a few come back.
        vec4 dropT = texture2D(uDrops, p / 2.0 + vec2(rnd3 * 0.4, rnd * 0.4));
        float dropKept = step(dropT.a, uWet * 0.55 * mix(uDropBack, 1.0, mask));
        float dropOn = dropT.b * dropKept * smoothstep(0.03, 0.006, length(fwidth(p / 2.0)));
        vec2 dropN = (dropT.rg - 0.5) * 2.0 * dropOn;
        // Rain also runs down the glass in thin lines. Scenery.
        if (uRain > 0.5) {
          float rx = p.x * 19.0, lane = floor(rx), rr = hash12(vec2(lane, 3.0));
          float ry = fract(p.y * 0.3 + uTime * (0.22 + 0.5 * rr) + rr * 7.0);
          float run = step(0.62, rr) * (1.0 - abs(fract(rx) * 2.0 - 1.0)) * smoothstep(0.0, 0.03, ry) * smoothstep(0.55, 0.1, ry) * mix(uDropBack, 1.0, mask);
          dropOn = max(dropOn, run);
          dropN += vec2((fract(rx) - 0.5) * 2.0, 0.2) * run;
        }
        float grimeAmt = 0.3 + 0.34 * smoothstep(0.34, 0.68, tile.r) + 0.42 * tile.g + 0.12 * smoothstep(0.48, 0.66, tile.b);
        // Run-off below each transom, in streaks.
        float below = fract(gr.y);
        float stain = exp(-(1.0 - below) * uGrid.w * 1.5) * smoothstep(0.4, 0.62, tile.b);
        grimeAmt += 0.4 * stain;
        float film = clamp(mask * pow(max(level, 0.0), 0.7) * grimeAmt * uFilm * uFilmKeep, 0.0, 1.0);
        // A film scatters more at a grazing view: the light crosses more of it.
        film = clamp(film * (0.8 + 0.2 / sqrt(ndv + 0.2)), 0.0, 0.9);

        // Reflection, from the mirrored pass when it exists.
        vec3 refl;
        if (uHasReflect > 0.5) {
          vec4 q = uTexMat * vec4(vW, 1.0);
          vec2 uv = q.xy / q.w + tilt * 0.62 - dropN * 0.09;
          refl = textureLod(uReflect, uv, 0.35 + 2.8 * film).rgb;
        } else {
          float up = reflect(-V, vec3(0.0, -1.0, 0.0)).z;
          refl = mix(uEnvFlat * 0.42, uEnvFlat * 1.5, smoothstep(-0.25, 0.3, up + tilt.y * 3.0));
        }
        float coat = 0.3;
        float fres = coat + (1.0 - coat) * pow(1.0 - ndv, 5.0);
        fres = mix(fres, min(1.0, fres + 0.2), dropOn);
        // Behind the glass: dark rooms, and darker spandrels at the slab line.
        float fz = fract(gr.y);
        float span = 1.0 - smoothstep(0.16, 0.19, min(fz, 1.0 - fz));
        vec3 inner = mix(vec3(0.012, 0.024, 0.024), vec3(0.004, 0.008, 0.008), span) * (0.75 + 0.5 * rnd);
        // Lit rooms at dusk and night, pane by pane.
        inner += (1.0 - span) * vec3(1.0, 0.72, 0.42) * uRooms * 0.75 * step(0.62, rnd2) * (0.5 + 0.5 * rnd3);
        // The look's building colour shows as a painted panel behind the pane, with a thin glaze of reflection over it.
        inner = mix(inner, uBody * uBodyLight * (0.92 + 0.16 * rnd3) * (1.0 - 0.18 * span), uBodyAmt) + uTintGlow * (1.0 - span);
        vec3 glass = mix(inner, refl * vec3(0.86, 0.96, 0.94) * uTint, fres * uReflKeep);

        // A dark ceramic frit band around each pane, flush with the glass.
        float aa = fwidth(min(bar.x, bar.y));
        float frit = 1.0 - smoothstep(0.066 - aa, 0.066 + aa, min(bar.x, bar.y));
        glass = mix(glass, mix(uFrit, refl * uTint, (0.09 + 0.6 * pow(1.0 - ndv, 4.0)) * uReflKeep), frit);

        // The robot's soft contact shadow on the film and in the glass. It comes from the recorded pose.
        vec2 rel = p - uRobot.xy;
        vec2 rp = vec2(dot(rel, uRobot.zw), dot(rel, vec2(-uRobot.w, uRobot.z)));
        float sd = roundBox(rp, vec2(0.18), 0.052);
        vec2 rel2 = rel + vec2(-0.012, 0.035);
        vec2 rp2 = vec2(dot(rel2, uRobot.zw), dot(rel2, vec2(-uRobot.w, uRobot.z)));
        float sd2 = roundBox(rp2, vec2(0.18), 0.052);
        float contact = uRobotNear * max(exp(-max(sd, 0.0) / 0.018) * 0.78, exp(-max(sd2, 0.0) / 0.075) * 0.62);
        float occl = 1.0 - clamp(contact, 0.0, 0.92);

        // The film: a thin warm-grey mineral layer lit by the overcast.
        vec3 tint = mix(vec3(0.24, 0.235, 0.22), vec3(0.17, 0.17, 0.165), smoothstep(0.3, 0.7, tile.r));
        vec3 filmCol = tint * uEnvFlat * 1.55 * (0.92 + 0.18 * tile.g);
        filmCol = mix(filmCol, vec3(0.62, 0.44, 0.25) * uEnvFlat * 1.55, uDustFilm);
        // Water cuts through the film where it sits, and a drop's lower lip catches the sky.
        vec3 col = mix(glass * mix(1.0, occl, 0.75), filmCol * occl, film * (1.0 - 0.8 * dropOn));
        col += dropOn * uEnvFlat * 0.5 * smoothstep(0.1, 0.9, dropN.y) * occl;
        // Snow settled on each joint's top edge and creeping in from the pane edges. Scenery. A cleaned lane stays bare.
        if (uSnow > 0.0) {
          float above = fract(gr.y) * uGrid.w;
          float bank = 1.0 - smoothstep(0.75, 1.0, above / (uSnow * (0.1 + 0.4 * tile.r * tile.r + 0.2 * wide.a)));
          float frost = smoothstep(0.16, 0.03, bar.x + 0.14 * tile.g) * smoothstep(0.42, 0.62, tile.r) * uSnow;
          col = mix(col, uEnvFlat * vec3(2.2, 2.25, 2.35) * occl, clamp(max(bank, frost * 0.7), 0.0, 1.0) * mix(0.1, 1.0, mask));
        }
        col = mix(col, uHaze, clamp(airAmount(vW, cameraPosition), 0.0, 1.0));
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

export function brushedTextures(renderer: THREE.WebGLRenderer) {
  // Brushed metal: fine streaks along the bar. U is across, in metres. V is along. R and G set colour and roughness.
  const w = 256, h = 512, data = new Uint8Array(w * h * 4), rough = new Uint8Array(w * h * 4);
  let s = 777; const rnd = () => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const line = new Float32Array(w).map(() => rnd());
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      if (rnd() < 0.0003) line[x] = rnd();
      const v = 0.6 * line[x] + 0.4 * line[(x * 3 + 7) % w], i = (y * w + x) * 4, c = 150 + 105 * v * v, r = 255 * (0.2 + 0.4 * (1.0 - v));
      data.set([c, c, c, 255], i); rough.set([r, r, r, 255], i);
    }
  }
  const make = (bytes: Uint8Array) => {
    const t = new THREE.DataTexture(bytes, w, h, THREE.RGBAFormat);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.magFilter = THREE.LinearFilter; t.minFilter = THREE.LinearMipmapLinearFilter; t.generateMipmaps = true;
    t.anisotropy = Math.min(16, renderer.capabilities.getMaxAnisotropy());
    t.repeat.set(1 / 0.06, 1 / 1.1);
    t.needsUpdate = true;
    return t;
  };
  return { color: make(data), rough: make(rough) };
}

// One bar profile, swept. The crown keeps the sim's height: a robot crosses what it crossed in the recording.
export function barGeometry(bars: { axis: 'x' | 'z'; at: number; from: number; to: number; crownY: number }[]) {
  const metal: number[] = [], normal: number[] = [], uv: number[] = [], index: number[] = [];
  const seal: number[] = [], sealIndex: number[] = [];
  const HALF = 0.04, CH = 0.0032;
  for (const b of bars) {
    const d = Math.max(0.0015, -b.crownY);
    // Offset across the bar, height off the glass, outward normal of the section.
    const prof: [number, number, number, number][] = [
      [-HALF, 0.0002, -0.97, 0.2], [-HALF + CH, d - 0.0007, -0.8, 0.6], [-HALF + 2 * CH, d, -0.1, 1],
      [HALF - 2 * CH, d, 0.1, 1], [HALF - CH, d - 0.0007, 0.8, 0.6], [HALF, 0.0002, 0.97, 0.2],
    ];
    const base = metal.length / 3;
    for (const [o, h, nx, ny] of prof) {
      for (const along of [b.from, b.to]) {
        if (b.axis === 'z') { metal.push(b.at + o, -h, along); normal.push(nx, -ny, 0); }
        else { metal.push(along, -h, b.at + o); normal.push(0, -ny, nx); }
        uv.push(o + b.at * 0.13, along);
      }
    }
    for (let i = 0; i < prof.length - 1; i++) {
      const p = base + 2 * i;
      if (b.axis === 'z') index.push(p, p + 3, p + 1, p, p + 2, p + 3);
      else index.push(p, p + 3, p + 2, p, p + 1, p + 3);
    }
    // Dark gasket either side of the cap.
    for (const sign of [-1, 1]) {
      const s0 = sign * HALF, s1 = sign * (HALF + 0.0065), sb = seal.length / 3;
      for (const [o, h] of [[s0, 0.0028], [s1, 0.0006]] as const) {
        for (const along of [b.from, b.to]) {
          if (b.axis === 'z') seal.push(b.at + o, -h, along); else seal.push(along, -h, b.at + o);
        }
      }
      if ((b.axis === 'z') === (sign > 0)) sealIndex.push(sb, sb + 1, sb + 3, sb, sb + 3, sb + 2);
      else sealIndex.push(sb, sb + 3, sb + 1, sb, sb + 2, sb + 3);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(metal, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(normal, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(index);
  const gs = new THREE.BufferGeometry();
  gs.setAttribute('position', new THREE.Float32BufferAttribute(seal, 3));
  gs.setIndex(sealIndex);
  gs.computeVertexNormals();
  return { metal: g, seal: gs };
}
