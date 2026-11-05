// Seed challenge: Acme Robotics, "Cubes at random angles".

export const BASELINE = `// Acme's current controller.
// It always grips with the fingers along the arm's heading,
// so a cube that arrives twisted can slip or tip.
function createController() {
  let phase = 0, since = 0, start = null;
  const close = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]) < 0.015;
  return (obs) => {
    if (!start) start = obs.cube.slice();
    const c = start, s = obs.shelf;
    const plan = [
      { target: [c[0], c[1], c[2] + 0.1],   grip: 1 },
      { target: [c[0], c[1], c[2] + 0.005], grip: 1 },
      { target: [c[0], c[1], c[2] + 0.005], grip: 0, wait: 0.6 },
      { target: [c[0], c[1], 0.6],          grip: 0 },
      { target: [s[0], s[1], s[2] + 0.08],  grip: 0 },
      { target: [s[0], s[1], s[2] + 0.03],  grip: 0 },
      { target: [s[0], s[1], s[2] + 0.03],  grip: 1, wait: 0.5 },
      { target: [s[0], s[1], s[2] + 0.12],  grip: 1 },
    ];
    const step = plan[Math.min(phase, plan.length - 1)];
    if (close(obs.grip, step.target) && obs.t - since >= (step.wait || 0)) { phase++; since = obs.t; }
    else if (!close(obs.grip, step.target)) since = obs.t;
    return step;
  };
}`;

export const FIXED = BASELINE
  .replace("// Acme's current controller.\n// It always grips with the fingers along the arm's heading,\n// so a cube that arrives twisted can slip or tip.",
    "// Fix: turn the wrist so the fingers meet two flat faces of the cube.")
  .replace("if (!start) start = obs.cube.slice();",
    `if (!start) {
      start = obs.cube.slice();
      const heading = Math.atan2(start[1], start[0] - 0.15);
      // Any face works (every 90 degrees); pick the one closest to the arm's heading.
      yaw = obs.cubeYaw + Math.round((heading - obs.cubeYaw) / (Math.PI / 2)) * (Math.PI / 2);
    }`)
  .replace("let phase = 0, since = 0, start = null;", "let phase = 0, since = 0, start = null, yaw = 0;")
  .replace("return step;", "return { ...step, yaw };");

export function compile(src: string) {
  // eslint-disable-next-line no-new-func
  const f = new Function(`"use strict";\n${src}\nreturn createController;`)();
  if (typeof f !== 'function') throw new Error('Define a function named createController');
  return f as () => (obs: any) => any;
}
