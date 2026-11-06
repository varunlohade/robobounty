// Drives the chat's AI picker in lab.html in a real browser, with real AI calls: one each on 0G Fast, Claude and 0G Private.
// set -a; . ./.env; set +a; node src/lab/tools/check_llm_route.mjs [--out DIR]. Needs vite on port 5199. It starts its own run servers on free ports.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { join, resolve } from 'node:path';
import { openChrome, wait } from './browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const OUT = resolve(arg('out', join(ROOT, 'design/shell')));
const SITE = 'http://localhost:5199';
const freePort = () => new Promise(r => { const s = createServer().listen(0, '127.0.0.1', () => { const { port } = s.address(); s.close(() => r(port)); }); });

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${detail}` : ''}`); };

for (const key of ['ZG_API_KEY', 'ZG_MODEL', 'ZG_FAST_MODEL']) if (!process.env[key]) { console.log(`FAIL ${key} is not set. Load .env first.`); process.exit(1); }

const servers = [];
async function server(args) {
  const port = await freePort();
  const child = spawn(join(ROOT, 'policy/.venv/bin/python'), [join(ROOT, 'policy/server/server.py'), '--port', String(port), ...args], { stdio: 'ignore', env: { ...process.env, ZG_FALLBACK_CLAUDE: '0' } });
  servers.push(child);
  for (let i = 0; i < 150; i++) { try { await fetch(`http://127.0.0.1:${port}/api/health`, { headers: { Origin: SITE } }); break; } catch { await wait(200); } }
  return port;
}

const b = await openChrome();
try {
  const label = () => b.js(`[...document.querySelectorAll('footer span, .status span, span')].map(s => s.textContent).find(t => t.startsWith('LLM:')) ?? ''`);
  const choose = route => b.js(`(() => { const s = document.querySelector('.chat-route'); s.value = ${JSON.stringify(route)}; s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  const say = async text => {
    const before = await b.js(`document.querySelectorAll('.chat-details').length`);
    await b.js(`(() => { const i = document.querySelector('.chat-input'); i.value = ${JSON.stringify(text)}; i.closest('form').requestSubmit(); })()`);
    await b.until(`document.querySelector('.chat-route').disabled`, 'the picker shuts while the AI works', 5);
    const seconds = await b.until(`!document.querySelector('.chat-send').disabled && document.querySelectorAll('.chat-details').length > ${before}`, `the reply to: ${text}`, 240);
    console.log(`   ${Math.round(seconds)} s: ${text}`);
    return b.js(`[...document.querySelectorAll('.chat-detail')].map(d => d.textContent).filter(t => /^(0G|Claude)/.test(t)).at(-1) ?? ''`);
  };

  const live = await server([]);
  await b.send('Page.navigate', { url: `${SITE}/lab.html?server=${live}` });
  await b.until(`document.querySelector('.chat-route') && !document.querySelector('.chat-route').hidden`, 'the picker shows', 30);
  const options = await b.js(`[...document.querySelectorAll('.chat-route option')].map(o => o.textContent).join(', ')`);
  check('three choices, by name', options === '0G Fast, 0G Private, Claude', options);
  check('a new chat starts on 0G Private', await b.js(`document.querySelector('.chat-route').value`) === 'private');
  await choose('fast');
  await b.until(`[...document.querySelectorAll('span')].some(s => s.textContent.startsWith('LLM: 0G Fast'))`, 'the fast label', 10);
  const shown = await label();
  check('the status bar says 0G Fast and not private', shown.includes(process.env.ZG_FAST_MODEL) && shown.includes('Not private, not verified'), shown);
  await b.shot(join(OUT, 'llm-route.png'));

  let row = await say('add snow');
  check('Details: 0G Fast answered, not private and not verified', row.startsWith('0G Fast:') && row.includes('Not private and not verified'), row);

  await choose('claude');
  await b.until(`[...document.querySelectorAll('span')].some(s => s.textContent === 'LLM: Claude')`, 'the Claude label', 10);
  check('changing it changes the status bar, with no restart', true);
  row = await say('make the building black');
  check('Details: Claude answered', row.startsWith('Claude: model claude-opus-5-5'), row);

  await choose('private');
  await b.until(`[...document.querySelectorAll('span')].some(s => s.textContent.startsWith('LLM: 0G Private'))`, 'the private label', 10);
  row = await say('add an antenna on the roof');
  check('Details: 0G Private answered, with our own signature check', row.startsWith('0G Private:') && row.includes('We checked the provider'), row);

  await choose('claude');
  await b.until(`[...document.querySelectorAll('span')].some(s => s.textContent === 'LLM: Claude')`, 'the Claude label again', 10);
  await b.send('Page.reload');
  await wait(1000);
  await b.until(`document.querySelector('.chat-route') && !document.querySelector('.chat-route').hidden`, 'the picker after a reload', 30);
  check('a reload keeps the choice', await b.js(`document.querySelector('.chat-route').value`) === 'claude');

  const stored = await server(['--recorded', join(ROOT, 'policy/server/fixtures')]);
  await b.js(`sessionStorage.clear()`);
  await b.send('Page.navigate', { url: `${SITE}/lab.html?server=${stored}` });
  await b.until(`[...document.querySelectorAll('span')].some(s => s.textContent.startsWith('LLM: stored'))`, 'the stored label', 30);
  await wait(500);
  check('a recorded run hides the picker', await b.js(`document.querySelector('.chat-route').hidden`));
  check('no page errors', b.problems.length === 0, b.problems.join(' | ').slice(0, 300));
} catch (err) {
  check('the check finished', false, String(err));
} finally {
  b.close();
  for (const s of servers) s.kill();
}
console.log(failed ? `FAILED ${failed}` : 'ALL PASS');
process.exit(failed ? 1 : 0);
