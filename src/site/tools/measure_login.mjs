// Measures the login film in headless Chrome: dropped frames and main-thread long tasks, at 1440x900, for 20 s. node measure_login.mjs [--base URL] [--seconds 20] [--shot file.png]
import { openChrome, wait } from '../../lab/tools/browser.mjs';
const arg = (n, d) => { const i = process.argv.indexOf(`--${n}`); return i < 0 ? d : process.argv[i + 1]; };
const BASE = arg('base', 'http://localhost:5210'), SECONDS = Number(arg('seconds', 20)), shot = arg('shot', null), width = Number(arg('w', 1440)), height = Number(arg('h', 900));
const c = await openChrome({ width, height });
await c.send('Page.enable');
await c.send('Page.addScriptToEvaluateOnNewDocument', { source: `window.__long = []; new PerformanceObserver(l => { for (const e of l.getEntries()) window.__long.push({ at: Math.round(e.startTime), ms: Math.round(e.duration) }); }).observe({ type: 'longtask', buffered: true });` });
await c.send('Page.navigate', { url: `${BASE}/login.html` });
await c.until(`document.querySelector('video')?.readyState >= 3 && !document.querySelector('video').paused`, 'film playing', 60);
await wait(1000);
const r = JSON.parse(await c.js(`new Promise(done => { const v = document.querySelector('video'); const q0 = v.getVideoPlaybackQuality(); const start = window.__long.length; let raf = 0, worst = 0, last = performance.now(); const t0 = last; let loops = 0, lastT = v.currentTime;
  const tick = now => { raf++; worst = Math.max(worst, now - last); last = now; if (v.currentTime < lastT) loops++; lastT = v.currentTime;
    if (now - t0 < ${SECONDS * 1000}) requestAnimationFrame(tick); else { const q = v.getVideoPlaybackQuality(); const long = window.__long.slice(start);
      done(JSON.stringify({ src: v.currentSrc, seconds: ${SECONDS}, videoFrames: q.totalVideoFrames - q0.totalVideoFrames, dropped: q.droppedVideoFrames - q0.droppedVideoFrames, corrupted: q.corruptedVideoFrames, rafFps: Math.round(raf / ${SECONDS}), worstFrameMs: Math.round(worst), loops, longTasks: long.length, longestTaskMs: long.reduce((m, e) => Math.max(m, e.ms), 0), longBeforeStart: window.__long.length - long.length, size: [v.videoWidth, v.videoHeight], elements: document.querySelectorAll('.lg *').length, canvases: document.querySelectorAll('canvas').length })); } };
  requestAnimationFrame(tick); })`));
console.log(JSON.stringify(r, null, 1));
if (shot) await c.shot(shot);
console.log('problems', c.problems.slice(0, 5));
c.close(); process.exit(0);
