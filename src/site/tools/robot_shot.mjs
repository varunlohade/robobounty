// Writes public/site/robot-window.png and robot-anymal.png. Usage: node src/site/tools/robot_shot.mjs http://localhost:PORT
// The ANYmal pose is frame 0 of a recorded run: the policy's standing stance before its first step.
import { readFileSync, writeFileSync } from 'node:fs';
import { gunzipSync } from 'node:zlib';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const base = process.argv[2];
const replay = JSON.parse(gunzipSync(readFileSync('policy/runs/demo/inspection/w000/replay.json.gz')));
const pose = { labels: replay.body_labels, q: replay.frames[0].q };
const VIEWS = {
  window: { robot: 'window', ground: 0, yaw: 0.6, pitch: 0.72, aim: [0, 0, 0.05], dist: 1.25, fov: 26 },
  anymal: { robot: 'anymal', pose, ground: 0.03, yaw: 0.68, pitch: 0.3, aim: [0, 0, 0.36], dist: 3.2, fov: 26 },
};
const c = await openChrome({ width: 1400, height: 900, guestForLab: false });
await c.send('Page.navigate', { url: `${base}/src/site/tools/robot_shot.html` });
for (let i = 0; i < 100 && (await c.js('document.title')) !== 'ready'; i++) await wait(200);
for (const [name, view] of Object.entries(VIEWS)) {
  const got = await c.js(`drawRobot(${JSON.stringify(view)})`);
  const [info, url] = got.split('|');
  console.log(name, info);
  writeFileSync(`public/site/robot-${name}.png`, Buffer.from(url.split(',')[1], 'base64'));
}
if (c.problems.length) console.log(c.problems);
await c.close();
