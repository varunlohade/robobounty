// Renders the caption bands and the two plain cards in headless Chrome. Fails if any caption does not fit.
import { readFileSync, writeFileSync } from 'node:fs';
import { openChrome, wait } from './cdp.mjs';
const spec = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const c = await openChrome(9380);
const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');
const page = body => `<!doctype html><meta charset=utf-8><style>*{box-sizing:border-box;margin:0}html,body{background:#000;color:#fff;font-family:"Helvetica Neue",Helvetica,Arial,sans-serif;overflow:hidden}
#band{width:1920px;height:120px;display:flex;align-items:center;gap:32px;padding:0 32px;border-top:1px solid #333}
#cap{flex:1;font-size:29px;line-height:37px;max-height:80px;overflow:hidden}
#tags{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;width:520px;flex:none}
#tags span{border:1px solid #bbb;padding:3px 10px;font-size:20px;line-height:26px;white-space:nowrap}
#card{width:1920px;height:960px;display:flex;flex-direction:column;justify-content:center;padding:0 180px}
h1{font:400 92px Georgia,serif;margin-bottom:28px}p{font-size:40px;line-height:54px;color:#ddd}</style>${body}`;
const set = async html => {
  await c.send('Page.navigate', { url: 'about:blank' });
  await c.js(`document.open(); document.write(${JSON.stringify(html)}); document.close();`);
  await wait(60);
};
const shoot = async (w, h, out, format) => {
  await c.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
  const res = await c.send('Page.captureScreenshot', { format, clip: { x: 0, y: 0, width: w, height: h, scale: 1 }, ...(format === 'jpeg' ? { quality: 95 } : {}) });
  writeFileSync(out, Buffer.from(res.result.data, 'base64'));
};
let bad = 0;
for (const b of spec.bands) {
  await set(page(`<div id=band><div id=cap>${esc(b.caption)}</div><div id=tags>${b.labels.map(l => `<span>${esc(l)}</span>`).join('')}</div></div>`));
  const fit = await c.js(`(() => { const e = document.getElementById('cap'), t = document.getElementById('tags'); return e.scrollHeight <= e.clientHeight + 1 && t.offsetHeight <= 110; })()`);
  if (!fit) { bad++; console.log('DOES NOT FIT:', b.caption); }
  await shoot(1920, 120, b.out, 'png');
}
for (const k of Object.values(spec.cards)) {
  await set(page(`<div id=card>${k.html}</div>`));
  await shoot(1920, 960, k.out, 'jpeg');
}
c.close();
process.exit(bad ? 1 : 0);
