// Renders every screen at 1440x900 with real hover, focus and typing through the Chrome DevTools protocol.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PORT = 9400 + Math.floor(Math.random() * 400);
const profile = mkdtempSync(join(tmpdir(), "crashlab-render-"));
const chrome = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run", "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1440,900", "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));

let target;
for (let i = 0; i < 60 && !target; i++) {
  await sleep(250);
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()).find(t => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise(r => (ws.onopen = r));
let id = 0; const wait = new Map(); const onEvent = {};
ws.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.id) { wait.get(d.id)?.(d.result ?? d); wait.delete(d.id); }
  else onEvent[d.method]?.(d.params);
};
const cdp = (method, params = {}) => new Promise(r => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
await cdp("Page.enable"); await cdp("Runtime.enable");
await cdp("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

const go = async (file, hash = "") => {
  await cdp("Page.navigate", { url: "about:blank" });
  await sleep(60);
  const loaded = new Promise(r => { onEvent["Page.loadEventFired"] = r; setTimeout(r, 4000); });
  await cdp("Page.navigate", { url: `file://${ROOT}/${file}${hash ? "#" + hash : ""}` });
  await loaded;
  await cdp("Runtime.evaluate", { expression: "document.fonts.ready", awaitPromise: true });
  await sleep(250);
};
const js = async e => (await cdp("Runtime.evaluate", { expression: e, returnByValue: true })).result?.value;
const center = s => js(`(()=>{const r=document.querySelector(${JSON.stringify(s)}).getBoundingClientRect();return [r.left+r.width/2,r.top+r.height/2]})()`);
const hover = async s => { const [x, y] = await center(s); await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }); await sleep(260); };
const away = () => cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x: 1, y: 899 });
const click = async s => { const [x, y] = await center(s); await cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x, y }); await cdp("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 }); await cdp("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 }); };
const type = async (s, text) => { await js(`document.querySelector(${JSON.stringify(s)}).focus()`); for (const c of text) { await cdp("Input.insertText", { text: c }); await sleep(30); } await sleep(200); };
const shot = async name => { const r = await cdp("Page.captureScreenshot", { format: "png" }); writeFileSync(join(ROOT, name), Buffer.from(r.data, "base64")); };
const overflow = async name => { const o = await js(`(()=>{const out=[];for(const e of document.querySelectorAll('main *,.side *')){if(e.closest('svg'))continue;const r=e.getBoundingClientRect();if(r.width&&(r.right>1441||(r.bottom>901&&!e.closest('.scroll,tbody'))))out.push(e.tagName+'.'+e.className+' '+Math.round(r.right)+','+Math.round(r.bottom));}return out.slice(0,8)})()`); if (o?.length) console.log(name, "OVERFLOW", o); };

const only = process.argv[2];
const job = async (name, fn) => { if (only && only !== name && only !== "video") return; if (only === "video") return; await fn(); await overflow(name); console.log("ok", name); };

await job("login", async () => {
  await go("login.html", "verifying"); await hover("#wid-c"); await away(); await click("#wid"); await sleep(400); await away(); await sleep(200);
  await shot("login.png");
  await go("login.html"); await hover("#wid"); await shot("renders/login-idle-hover.png");
  await go("login.html", "verified"); await away(); await sleep(350); await shot("renders/login-verified.png");
});
await job("home", async () => {
  await go("home.html"); await away(); await hover("table tbody tr:nth-child(2)"); await shot("home.png");
});
await job("crashlab", async () => {
  await go("crashlab.html"); await away(); await hover(".robot[data-robot=plant]"); await shot("crashlab.png");
  await go("crashlab.html", "plant"); await away(); await sleep(200); await shot("renders/crashlab-plant.png");
});
await job("bounties", async () => {
  await go("bounties.html"); await away(); await hover("#bt tbody tr:nth-child(3)"); await shot("bounties.png");
  await click("#st button[data-k=open]"); await sleep(200); await click("#bt tbody tr:nth-child(2)"); await sleep(350); await away(); await sleep(200); await shot("renders/bounties-open-selected.png");
});
await job("data", async () => {
  await go("data.html"); await away(); await type("#libq", "detach"); await hover('#map i[data-w="t0037"]'); await sleep(200); await shot("data.png");
  await click("[data-camp=window]"); await js("document.querySelector('#libq').blur()"); await away(); await sleep(250); await shot("renders/data-window-empty.png");
});
await job("providers", async () => {
  await go("providers.html"); await away(); await hover("[data-p=claude]"); await shot("providers.png");
});

if (only === "video") {
  const dir = mkdtempSync(join(tmpdir(), "crashlab-frames-"));
  let n = 0;
  const rec = async ms => { const end = Date.now() + ms; while (Date.now() < end) { const r = await cdp("Page.captureScreenshot", { format: "jpeg", quality: 88 }); writeFileSync(join(dir, `f${String(n++).padStart(5, "0")}.jpg`), Buffer.from(r.data, "base64")); } };
  const t0 = Date.now();
  await go("crashlab.html", "hold"); await away(); await rec(500);
  await hover(".robot[data-robot=plant]"); await rec(250); await click(".robot[data-robot=plant]"); await rec(800);
  await click(".robot[data-robot=window]"); await rec(700);
  await hover("#open"); await rec(300); await click("#open"); await rec(900);
  await go("bounties.html"); await away(); await rec(300);
  await click("#st button[data-k=open]"); await rec(500); await click("#bt tbody tr:nth-child(2)"); await rec(700);
  await click("#st button[data-k=all]"); await rec(500);
  await go("data.html"); await away(); await type("#libq", "detach"); await rec(400); await hover('#map i[data-w="t0037"]'); await rec(800);
  const secs = (Date.now() - t0) / 1000;
  execSync(`ffmpeg -y -loglevel error -framerate ${(n / secs).toFixed(2)} -i ${dir}/f%05d.jpg -c:v libx264 -pix_fmt yuv420p -r 30 ${join(ROOT, "renders/motion.mp4")}`);
  console.log("video", n, "frames in", secs.toFixed(1), "s");
  rmSync(dir, { recursive: true });
}
chrome.kill();
await sleep(200);
try { rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(0);
