// The film path on the real Arc testnet, with test USDC. Headless Chrome, its own profile, and an injected wallet whose reads and sends cross to this Node process, so no key enters the page.
// set -a; . ./.env; set +a; node src/board/tools/check_wallet_arc.mjs [--fork] [--ports WEB,RUN,SITE,BOARD]. Saves design/arc-real/*.png.
// Spends 1 test USDC plus gas, once. The board folder remembers each step, so a rerun resumes and does not fund again. Delete nothing there unless the money has moved.
// --fork rehearses on a local anvil fork of Arc, in a throwaway board folder. It spends nothing.
// It proves the chain, the server and the page. It does not prove real wallet popups. See docs/ARC-DEMO.md.
import { execFileSync, spawn } from 'node:child_process';
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const FORK = process.argv.includes('--fork');
const ROOT = resolve(import.meta.dirname, '../../..');
const [webPort, runPort, sitePort, boardPort] = arg('ports', '7199,7198,7297,7298').split(',').map(Number);
const WEB = `http://localhost:${webPort}`;
const CHAIN = '0x4cef52';
const USDC = '0x3600000000000000000000000000000000000000';
const CONTRACT = '0xc3cc7807884049c97e024242d72be65b8811cfd8';
const COMPANY = '0xb922daba41174a3d06791673dd3deb055a491485', ENGINEER = '0x4e5892bb657e06ca29a08e33fc5e0dc9753cd3d4';
const RESOLVER = '0x040bf606eb0422fa3a403e270cc18daa70ea8e00', ARBITER = '0xf7a4cd0b0d23dd25ed08f7d45431e655f6df59f1';
const PAY = 1_000_000n;
const PROOF_S = 1500, POST_S = 300, PAID_S = 240;
const KEYS = process.env.ARC_WALLET_DIR;
const UPSTREAM = process.env.ARC_RPC_URL;
const PASSWORD_FILE = join(KEYS ?? '', 'password');
if (!KEYS || !UPSTREAM || new URL(UPSTREAM).hostname !== 'rpc.testnet.arc.io') throw new Error('Load .env first: this check runs on the Arc testnet RPC only.');

const ANVIL = 7546;
const SLOW = 7547; // The fork answers in a millisecond and Arc's public RPC in about 400, and that gap hides timing bugs. So the fork sits behind a delay, in its own process, since this one blocks on cast.
const RPC = FORK ? `http://127.0.0.1:${SLOW}` : UPSTREAM;
const OUT = FORK ? mkdtempSync(join(tmpdir(), 'arc-fork-png-')) : join(ROOT, 'design/arc-real');
const boardRoot = FORK ? mkdtempSync(join(tmpdir(), 'arc-fork-board-')) : join(ROOT, 'policy/runs/arc-test');
mkdirSync(OUT, { recursive: true });

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${String(detail).slice(0, 300)}` : ''}`); };
const cleanEnv = { PATH: process.env.PATH, HOME: process.env.HOME };
const tool = (...a) => execFileSync('cast', a, { encoding: 'utf8', env: cleanEnv, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const scrub = text => String(text).split(KEYS).join('<wallet dir>').split(UPSTREAM).join('<rpc>').split('\n')[0].slice(0, 240);
// The public RPC can drop a read. A retry of a read costs nothing.
const cast = async (...a) => { for (let i = 0; ; i++) { try { return tool(...a, '--rpc-url', RPC); } catch (e) { if (i >= 4) throw new Error(scrub(e.stderr || e.message)); await wait(1000); } } };
const num = text => BigInt(text.split(/\s/)[0]);
const read = async (to, sig, ...a) => cast('call', to, sig, ...a);
const usdc = async who => num(await read(USDC, 'balanceOf(address)(uint256)', who));
const usdcNow = async () => ({ company: await usdc(COMPANY), engineer: await usdc(ENGINEER), contract: await usdc(CONTRACT), resolver: await usdc(RESOLVER), arbiter: await usdc(ARBITER) });
const receipt = async tx => JSON.parse(await cast('rpc', 'eth_getTransactionReceipt', tx));
const link = tx => `https://explorer.testnet.arc.io/tx/${tx}`;
const usd = base => (Number(base) / 1e6).toFixed(6);

let anvil = null, delay = null;
if (FORK) {
  anvil = spawn('anvil', ['--host', '127.0.0.1', '--port', String(ANVIL), '--fork-url', UPSTREAM, '--chain-id', '5042002', '--block-time', '1', '--silent'], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) { try { tool('chain-id', '--rpc-url', `http://127.0.0.1:${ANVIL}`); break; } catch { await wait(300); } }
  delay = spawn('node', ['-e', `require('http').createServer((q, s) => { let b = ''; q.on('data', d => b += d); q.on('end', () => setTimeout(async () => { const r = await fetch('http://127.0.0.1:${ANVIL}', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: b }); s.setHeader('Content-Type', 'application/json'); s.end(await r.text()); }, 400)); }).listen(${SLOW}, '127.0.0.1');`], { stdio: 'ignore' });
  for (let i = 0; i < 100; i++) { try { tool('chain-id', '--rpc-url', RPC); break; } catch { await wait(300); } }
  // Arc's USDC calls a native precompile that anvil does not have, so a fork reverts on transferFrom. The rehearsal puts the local mock at its address.
  const code = JSON.parse(readFileSync(join(ROOT, 'contracts/out/Mocks.sol/MockUSDC.json'), 'utf8')).deployedBytecode.object;
  tool('rpc', '--rpc-url', RPC, 'anvil_setCode', USDC, code);
  tool('rpc', '--rpc-url', RPC, 'anvil_setStorageAt', USDC, '0x0', `0x${'6'.padStart(64, '0')}`);
  tool('send', '--rpc-url', RPC, '--unlocked', '--from', '0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266', USDC, 'mint(address,uint256)', COMPANY, '2000000');
  const saved = JSON.parse(readFileSync(join(ROOT, 'policy/runs/film/arc.json'), 'utf8'));
  writeFileSync(join(boardRoot, 'arc.json'), JSON.stringify({ ...saved, label: 'Local stand-in chain. Not Arc. Not real money.' }));
} else {
  if (!existsSync(join(boardRoot, 'arc.json'))) { mkdirSync(boardRoot, { recursive: true }); copyFileSync(join(ROOT, 'policy/runs/film/arc.json'), join(boardRoot, 'arc.json')); }
  if (JSON.parse(readFileSync(join(boardRoot, 'arc.json'), 'utf8')).contract !== CONTRACT) throw new Error('This board names another contract.');
}

// What this run has already done lives in the board folder, so a rerun cannot fund twice.
const sendsPath = join(boardRoot, '.check_sends.json');
const basePath = join(boardRoot, '.check_baseline.json');
const sends = existsSync(sendsPath) ? JSON.parse(readFileSync(sendsPath, 'utf8')) : [];
const saveSends = () => writeFileSync(sendsPath, JSON.stringify(sends, null, 1));
const APPROVE = tool('sig', 'approve(address,uint256)'), CREATE = tool('sig', 'createBounty(address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64)');
const refusal = (code, message) => Object.assign(new Error(message), { code });

// The wallet, on this side of the bridge. It holds the state a real wallet holds, opens keystores only through cast, and sends only the two calls this flow needs.
const wallet = { role: 'company', chain: '0x1', connected: false, added: false, popups: [] };
const accountOf = () => (wallet.role === 'company' ? COMPANY : ENGINEER);
const signerOf = () => ['--keystore', join(KEYS, wallet.role === 'company' ? 'company' : 'tester'), '--password-file', PASSWORD_FILE];
for (const [role, address] of [['company', COMPANY], ['engineer', ENGINEER]]) {
  wallet.role = role;
  if (tool('wallet', 'address', ...signerOf()).toLowerCase() !== address) throw new Error(`The ${role} keystore is not the expected wallet.`);
}
wallet.role = 'company';
const READS = new Set(['eth_getTransactionReceipt', 'eth_call', 'eth_getBalance', 'eth_blockNumber', 'eth_gasPrice', 'eth_estimateGas', 'eth_getTransactionCount', 'eth_getCode', 'eth_getBlockByNumber', 'eth_maxPriorityFeePerGas', 'eth_feeHistory', 'eth_getTransactionByHash']);
const seenReceipts = new Map();

async function walletSend(tx) {
  const data = String(tx.data ?? ''), selector = data.slice(0, 10), to = String(tx.to ?? '').toLowerCase();
  wallet.popups.push(`tx:${wallet.role}:${selector}`);
  if (wallet.chain !== CHAIN || tx.chainId !== CHAIN) throw refusal(-32000, 'The page sent a transaction off Arc, or with no Arc chain id.');
  if (String(tx.from).toLowerCase() !== accountOf()) throw refusal(-32000, 'The page sent from another account.');
  if (tx.value && BigInt(tx.value) !== 0n) throw refusal(-32000, 'This flow sends no native value.');
  if (wallet.role !== 'company') throw refusal(-32000, 'The engineer sends no transaction on the film path.');
  if (selector === APPROVE) {
    if (to !== USDC) throw refusal(-32000, 'An approval to another token.');
    if (`0x${data.slice(34, 74)}` !== CONTRACT || BigInt(`0x${data.slice(74)}`) > PAY) throw refusal(-32000, 'An approval above the pay, or to another spender.');
    if (sends.filter(s => s.kind === 'approve').length >= 2) throw refusal(-32000, 'This board has made two approvals already. Stopped.');
  } else if (selector === CREATE) {
    if (to !== CONTRACT) throw refusal(-32000, 'A create on another contract.');
    if (sends.some(s => s.kind === 'create')) throw refusal(-32000, 'This board has sent a create already. Stopped, so a second cannot spend more.');
  } else throw refusal(-32000, 'This wallet sends only approve and createBounty.');
  const kind = selector === APPROVE ? 'approve' : 'create';
  const row = { kind, at: Date.now(), hash: null, fork: FORK };
  sends.push(row);
  saveSends();
  const fees = ['--gas-price', BigInt(tx.maxFeePerGas).toString(), '--priority-gas-price', BigInt(tx.maxPriorityFeePerGas).toString()];
  let out;
  try { out = tool('send', '--async', '--rpc-url', RPC, '--chain', '5042002', ...signerOf(), ...fees, to, data); } catch (e) {
    sends.splice(sends.indexOf(row), 1);
    saveSends();
    throw refusal(-32000, scrub(e.stderr || e.message));
  }
  const hash = out.match(/0x[0-9a-fA-F]{64}/)?.[0];
  if (!hash) throw refusal(-32000, 'The wallet got no transaction hash.');
  row.hash = hash;
  saveSends();
  console.log(`  ${kind} sent: ${link(hash)}`);
  return hash;
}

async function walletCall(method, params) {
  if (method === 'eth_chainId') return wallet.chain;
  if (method === 'eth_accounts') return wallet.connected ? [accountOf()] : [];
  if (method === 'eth_requestAccounts') { wallet.popups.push('connect'); wallet.connected = true; return [accountOf()]; }
  if (method === 'wallet_switchEthereumChain') {
    wallet.popups.push('switch');
    if (params[0]?.chainId !== CHAIN) throw refusal(-32000, 'This wallet stays on Arc testnet.');
    if (!wallet.added) throw refusal(4902, 'Unrecognized chain');
    wallet.chain = CHAIN;
    return null;
  }
  if (method === 'wallet_addEthereumChain') {
    const n = params[0];
    wallet.popups.push(`add:${n.chainName}:${n.nativeCurrency.symbol}:${n.nativeCurrency.decimals}`);
    wallet.addParams = n;
    wallet.added = true;
    return null;
  }
  if (method === 'personal_sign') {
    wallet.popups.push(`sign:${wallet.role}`);
    if (String(params[1]).toLowerCase() !== accountOf()) throw refusal(-32000, 'The page asked another account to sign.');
    return tool('wallet', 'sign', ...signerOf(), String(params[0]));
  }
  if (method === 'eth_sendTransaction') return walletSend(params[0]);
  if (!READS.has(method)) throw refusal(-32601, `This wallet does not forward ${method}.`);
  const reply = await fetch(RPC, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
  const j = await reply.json();
  if (j.error) throw refusal(j.error.code, j.error.message);
  if (method === 'eth_getTransactionReceipt') {
    const row = seenReceipts.get(params[0]) ?? { asks: 0, first: Date.now(), got: null };
    row.asks++;
    if (j.result && !row.got) row.got = Date.now();
    seenReceipts.set(params[0], row);
  }
  return j.result;
}

const TOKEN = randomBytes(24).toString('hex');
const bridge = createServer((req, res) => {
  const origin = req.headers.origin;
  res.setHeader('Access-Control-Allow-Origin', WEB);
  let body = '';
  req.on('data', d => { body += d; });
  req.on('end', async () => {
    let answer;
    try {
      const { token, method, params } = JSON.parse(body);
      if (origin !== WEB || token !== TOKEN) throw refusal(4100, 'This bridge answers its own page only.');
      answer = { result: await walletCall(method, params ?? []) };
    } catch (e) { answer = { error: { code: e.code ?? -32000, message: scrub(e.message) } }; }
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(answer));
  });
});
await new Promise(r => bridge.listen(0, '127.0.0.1', r));
const BRIDGE = `http://127.0.0.1:${bridge.address().port}/`;

// The page side: no key and no signing. Each request crosses to Node.
const INJECTED = `(() => {
  // Every request's time, for the report when a step stalls.
  const realFetch = window.fetch.bind(window);
  window.__net = { open: new Map(), done: [] };
  window.fetch = async (url, init) => { const key = (init?.method ?? 'GET') + ' ' + String(url).replace(/^https?:..[^/]+/, '') + ' #' + Math.random().toString(36).slice(2, 6); const t = performance.now(); window.__net.open.set(key, t); try { return await realFetch(url, init); } finally { window.__net.open.delete(key); window.__net.done.push([key, Math.round(performance.now() - t)]); } };
  const listeners = {};
  window.__wallet = { emit(name, value) { (listeners[name] || []).forEach(f => f(value)); } };
  window.ethereum = {
    on(name, f) { (listeners[name] ||= []).push(f); },
    removeListener() {},
    async request({ method, params = [] }) {
      const r = await realFetch(${JSON.stringify(BRIDGE)}, { method: 'POST', headers: { 'Content-Type': 'text/plain' }, body: JSON.stringify({ token: ${JSON.stringify(TOKEN)}, method, params }) });
      const j = await r.json();
      if (j.error) throw Object.assign(new Error(j.error.message), { code: j.error.code });
      return j.result;
    },
  };
})();`;

const log = [];
const childEnv = { ...process.env, ARC_RPC_URL: RPC };
const demo = spawn('npm', ['run', 'demo', '--', '--recorded', '--arc', '--ports', `${webPort},${runPort},${sitePort},${boardPort}`, '--board-root', boardRoot], { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'], env: childEnv, detached: true });
demo.stdout.on('data', d => log.push(String(d)));
demo.stderr.on('data', d => log.push(String(d)));
const stopDemo = async () => {
  if (demo.exitCode !== null) return;
  try { process.kill(-demo.pid, 'SIGINT'); } catch { return; }
  for (let i = 0; i < 100 && demo.exitCode === null; i++) await wait(100);
  if (demo.exitCode === null) try { process.kill(-demo.pid, 'SIGTERM'); } catch { /* already gone */ }
};
console.log(`demo pid ${demo.pid}`);
const t0 = Date.now();
while (!log.join('').includes('Press Ctrl+C')) {
  if (demo.exitCode !== null || Date.now() - t0 > 180_000) throw new Error(`demo did not start: ${scrub(log.join('').slice(-400))}`);
  await wait(200);
}

const c = await openChrome({ width: 1440, height: 900 });
await c.send('Page.addScriptToEvaluateOnNewDocument', { source: INJECTED });
const go = path => c.send('Page.navigate', { url: `${WEB}/${path}` });
const text = sel => c.js(`document.querySelector(${JSON.stringify(sel)})?.innerText ?? ''`);
const hasButton = label => `[...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(label)})`;
const press = async (label, seconds = 60) => { await c.until(`!!${hasButton(label)} && !${hasButton(label)}.disabled`, `the button "${label}"`, seconds); await c.js(`${hasButton(label)}.click()`); };
const stepState = name => c.js(`document.querySelector('[data-step="${name}"]')?.dataset.state ?? null`);
const barHas = words => `(document.querySelector('.walletbar')?.innerText ?? '').includes(${JSON.stringify(words)})`;
const shot = async name => { await wait(400); await c.shot(join(OUT, `${name}.png`)); };
const showChain = () => c.js(`document.querySelector('.detail').scrollTop = 0`);
const stepWords = () => c.js(`[...document.querySelectorAll('[data-step]')].map(n => n.dataset.step + '=' + n.dataset.state).join(' ')`);

async function signIn(role) {
  const label = role === 'company' ? 'Demo company' : 'Demo engineer';
  await go('login.html?seed=1');
  const find = `[...document.querySelectorAll('button')].find(n => n.textContent.trim() === ${JSON.stringify(label)})`;
  await c.until(`!!${find}`, label, 30);
  await wait(500);
  if (role === 'company') await shot('01-login-seeded');
  await c.js(`${find}.click()`);
  await c.until(`document.querySelector('.sh-who')?.dataset.who === ${JSON.stringify(role)}`, `the ${role} session`, 30);
  await c.until(`!!document.querySelector('a[href="bounties.html"]')`, 'the Bounties link', 30);
  await c.js(`document.querySelector('a[href="bounties.html"]').click()`);
  await c.until(`location.pathname === '/bounties.html' && !!document.querySelector('.walletbar') && !document.querySelector('.walletbar').hidden`, 'the wallet line', 30);
}

const folder = join(boardRoot, '1');
const fundingPath = join(folder, 'arc_funding.json'), stepsPath = join(folder, 'fixes/1/arc_steps.json'), fixPath = join(folder, 'fixes/1/fix.json');
const json = path => JSON.parse(readFileSync(path, 'utf8'));
let run = 'unknown';

try {
  // Refuse before anything moves, and fix the numbers the end compares against.
  check('the RPC reports Arc testnet', (await cast('chain-id')) === '5042002');
  check('the contract is deployed here', (await cast('code', CONTRACT)).length > 100);
  const startBalances = await usdcNow();
  console.log('  USDC now', Object.entries(startBalances).map(([k, v]) => `${k} ${usd(v)}`).join(', '));
  if (!existsSync(basePath)) {
    if (existsSync(fundingPath)) throw new Error('This board is funded but has no baseline.');
    if (startBalances.company < PAY + 50_000n) throw new Error('The company wallet holds too little. Stop and tell the owner.');
    writeFileSync(basePath, JSON.stringify({ ...Object.fromEntries(Object.entries(startBalances).map(([k, v]) => [k, String(v)])), bounties: String(num(await read(CONTRACT, 'bountyCount()(uint256)'))) }, null, 1));
  }
  const base = json(basePath);

  // Company.
  const wasFunded = existsSync(fundingPath);
  await signIn('company');
  await shot('02-company-not-connected');
  await press('Connect wallet');
  await c.until(barHas('test USDC'), 'the balance in the wallet line', 60);
  const bar = await text('.walletbar');
  const companyShown = (Number(await usdc(COMPANY)) / 1e6).toFixed(2);
  check('connected: the address and the chain balance', bar.includes('0xb922') && bar.includes(`${companyShown} test USDC`), bar);
  check('the page asks to add Arc: USDC as native, 18 decimals', wallet.addParams?.nativeCurrency.decimals === 18 && wallet.addParams.nativeCurrency.symbol === 'USDC' && wallet.addParams.chainId === CHAIN, JSON.stringify(wallet.addParams?.nativeCurrency));
  if (!FORK) check('the add request names the real RPC and explorer', new URL(wallet.addParams.rpcUrls[0]).hostname === 'rpc.testnet.arc.io' && wallet.addParams.blockExplorerUrls?.[0] === 'https://explorer.testnet.arc.io' && wallet.addParams.chainName === 'Arc Testnet');
  await shot('03-company-connected');

  if (!existsSync(join(folder, 'ledger.json'))) {
    await press('Post a bounty');
    await c.until(`!!document.querySelector('.overlay select')?.value && !!document.querySelectorAll('.overlay input')[0]?.value`, 'the stored failure, already picked', 60);
    const form = await c.js(`({ failure: document.querySelector('.overlay select').selectedOptions[0].textContent, pay: document.querySelectorAll('.overlay input')[2].value, title: document.querySelectorAll('.overlay input')[0].value })`);
    check('the post form opens with the stored failure and pay 1', form.pay === '1' && /stalled|stops/i.test(form.failure), JSON.stringify(form));
    await shot('04-post-form');
    const started = Date.now();
    if (sends.some(s => s.kind === 'create')) throw new Error('A create was sent, but the board has no funding row. Check the hash in .check_sends.json before you spend more.');
    await press('Post and deposit'); // One press: it posts, then funds, with no second button.
    await c.until(`${hasButton('Confirm in your wallet')} !== undefined || document.querySelector('[data-step="funded"]')?.dataset.state === 'ok' || !!document.querySelector('.walleterr')`, 'the wallet step', 90);
    if (await c.js(`!!document.querySelector('.walleterr')`)) throw new Error(`Fund failed: ${await text('.walleterr')}`);
    await shot('06-funding-confirm-in-wallet');
    await c.until(`document.querySelector('[data-step="funded"]')?.dataset.state === 'ok' || !!document.querySelector('.walleterr')`, 'funded', 240);
    if (await c.js(`!!document.querySelector('.walleterr')`)) throw new Error(`Fund failed: ${await text('.walleterr')}`);
    console.log(`  post and fund took ${((Date.now() - started) / 1000).toFixed(1)} s`);
  } else if (!wasFunded) {
    await press('Try again');
    await c.until(`document.querySelector('[data-step="funded"]')?.dataset.state === 'ok' || !!document.querySelector('.walleterr')`, 'funded', 240);
    if (await c.js(`!!document.querySelector('.walleterr')`)) throw new Error(`Fund failed: ${await text('.walleterr')}`);
  }
  const funding = json(fundingPath);
  const funded = {};
  for (const [name, tx] of Object.entries(funding.txs)) { const r = await receipt(tx); funded[name] = r; check(`${name} receipt status 1, from the company`, BigInt(r.status) === 1n && r.from.toLowerCase() === COMPANY, link(tx)); }
  check('both funding transactions exist', funded.approve && funded.create_bounty);
  const row = (await read(CONTRACT, 'bounties(uint256)(address,address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64,bool)', String(funding.chain_bounty))).split('\n');
  check('the contract holds this bounty: company, agent, arbiter, pay', row[0].toLowerCase() === COMPANY && row[1].toLowerCase() === RESOLVER && row[2].toLowerCase() === ARBITER && num(row[4]) === PAY, row.slice(0, 3).join(' '));
  check('this run made one chain bounty', num(await read(CONTRACT, 'bountyCount()(uint256)')) === BigInt(base.bounties) + 1n);
  if (!wasFunded) {
    check('the contract got exactly the pay, read from the chain', (await usdc(CONTRACT)) === BigInt(base.contract) + PAY);
    check('no allowance stays open', num(await read(USDC, 'allowance(address,address)(uint256)', COMPANY, CONTRACT)) === 0n);
    await c.until(barHas(`${(Number(await usdc(COMPANY)) / 1e6).toFixed(2)} test USDC`), 'the balance after funding', 30);
  }
  const hrefs = await c.js(`[...document.querySelectorAll('[data-step="funded"] a')].map(a => a.href)`);
  check('Funded shows both explorer links', hrefs.length === 2 && hrefs.every(h => h.startsWith('https://explorer.testnet.arc.io/tx/')) || FORK, hrefs.join(' '));
  await showChain();
  await shot('07-funded');

  // Engineer: the wallet moves to account 2, then the person signs out and signs in again.
  wallet.role = 'engineer';
  await c.js(`window.__wallet.emit('accountsChanged', [${JSON.stringify(ENGINEER)}])`);
  await wait(1500);
  await shot('08-wallet-moved-to-account-2');
  await c.js(`document.querySelector('[aria-label="Sign out"]').click()`);
  await c.until(`location.pathname === '/login.html'`, 'the login page', 30);
  await signIn('engineer');
  const popupsAtEngineer = wallet.popups.length;
  await c.until(`!!${hasButton('Save this wallet')} || !!${hasButton('Connect wallet')} || ${barHas('Payout wallet saved')}`, 'the engineer wallet line', 60);
  if (await c.js(`!!${hasButton('Connect wallet')}`)) await press('Connect wallet');
  await press('Save this wallet');
  await c.until(barHas('Payout wallet saved'), 'the saved wallet', 60);
  const side = await text('.walletbar');
  check('the wallet line shows the proved wallet', side.includes('0x4E58') || side.includes('0x4e58'), side);
  check('saving took a signature', wallet.popups.slice(popupsAtEngineer).includes('sign:engineer'), wallet.popups.slice(popupsAtEngineer).join());
  await showChain();
  await shot('09-engineer-wallet-saved');

  // The stored good fix.
  if (!existsSync(fixPath)) {
    await press('Submit a fix');
    await c.until(`document.querySelector('.overlay textarea')?.dataset.ready === '1'`, 'the source', 60);
    await press('Use the stored good fix');
    await wait(500);
    await shot('10-submit-stored-fix');
    await press('Run check, then simulation');
    await c.until(`!document.querySelector('.overlay')`, 'the submit', 60);
  }
  const proofAt = Date.now();
  await c.until(`document.querySelector('[data-step="proposed"]')?.dataset.state === 'ok' || !!document.querySelector('.detail .err')`, 'the agent proposes', PROOF_S);
  await c.until(`document.querySelector('[data-step="proposed"]')?.dataset.state === 'ok'`, 'the agent proposes', 180);
  console.log(`  gate to proposal ${((Date.now() - proofAt) / 1000).toFixed(1)} s`);
  const detail = await text('.detail');
  check('the gate accepted this fix', /The fix holds on the hidden worlds/.test(detail), detail.slice(0, 200));
  check('the recorded proof says so on screen', detail.includes('Recorded proof') && detail.includes('The chain transactions are real'));

  // The dispute window. Skipped on a rerun that arrives after it closed.
  if (await c.js(`/\\d+ s left/.test(document.querySelector('[data-step="dispute-window"]')?.textContent ?? '')`)) {
    await showChain();
    await shot('11-dispute-window');
    const left = async () => Number((await c.js(`document.querySelector('[data-step="dispute-window"]')?.textContent ?? ''`)).match(/(\d+) s left/)?.[1] ?? -1);
    const first = await left();
    await wait(3000);
    const next = await left();
    check('the countdown moves', next < first && first <= 60, `${first} then ${next}`);
    check('nothing is paid during the window, read from the chain', (await usdc(ENGINEER)) === BigInt(base.engineer));
    const steps = json(stepsPath);
    let early = false;
    try { tool('call', '--rpc-url', RPC, '--from', RESOLVER, CONTRACT, 'payout(uint256,bytes32)', String(steps.chain_bounty), steps.fingerprint); } catch { early = true; }
    check('the contract refuses pay before the window ends', early);
  }

  // The agent finalizes and pays. The engineer presses nothing.
  await c.until(`document.querySelector('[data-step="paid"]')?.dataset.state === 'ok'`, 'the agent pays', PAID_S);
  const steps = json(stepsPath);
  for (const name of ['propose', 'finalize', 'payout']) {
    const r = await receipt(steps.txs[name]);
    check(`${name} receipt status 1, from the agent`, BigInt(r.status) === 1n && r.from.toLowerCase() === RESOLVER, link(steps.txs[name]));
  }
  const after = await usdcNow();
  check('the engineer balance rose by exactly 1, read from the chain', after.engineer === BigInt(base.engineer) + PAY, `${usd(base.engineer)} to ${usd(after.engineer)}`);
  check('the contract is back where it began', after.contract === BigInt(base.contract), usd(after.contract));
  const failure = (await read(CONTRACT, 'failures(uint256,bytes32)(address,uint256,bytes32,uint64,bool,uint8)', String(steps.chain_bounty), steps.fingerprint)).split('\n');
  check('the contract says Claimed, for the engineer', num(failure[5]) === 4n && failure[0].toLowerCase() === ENGINEER, failure.join(' '));
  let again = false;
  try { tool('call', '--rpc-url', RPC, '--from', RESOLVER, CONTRACT, 'payout(uint256,bytes32)', String(steps.chain_bounty), steps.fingerprint); } catch { again = true; }
  check('a second payout would revert', again);
  check('the engineer sent no transaction', !wallet.popups.some(p => p.startsWith('tx:engineer')), wallet.popups.join());
  await c.until(`document.querySelector('.chainbalance')?.dataset.balance === ${JSON.stringify(String(after.engineer))}`, 'the balance on the page', 30);
  const shown = (Number(after.engineer) / 1e6).toFixed(2);
  await c.until(barHas(`${shown} test USDC`), 'the engineer balance in the wallet line', 30);
  check('the page shows 6-decimal USDC, not wei', (await text('.walletbar')).includes(`${shown} test USDC`), await text('.walletbar'));
  await c.until(`(document.querySelector('.list')?.innerText ?? '').includes('Paid')`, 'Paid in the list', 30);
  await showChain();
  await shot('12-paid');
  await c.js(`document.querySelector('.detail')?.scrollIntoView({ block: 'start' }); document.scrollingElement.scrollTop = 0`);
  await shot('13-paid-top-of-page');

  // Keys and leaks: the password itself, compared and never printed.
  const password = readFileSync(PASSWORD_FILE, 'utf8').trim();
  const agentLog = log.join('').match(/Agent log: (\S+)/)?.[1];
  const logged = agentLog && existsSync(agentLog) ? readFileSync(agentLog, 'utf8') : '';
  check('the agent log has no password or key words', Boolean(agentLog) && !logged.includes(password) && !/private.?key|mnemonic|keystore/i.test(logged), scrub(logged.slice(0, 200)));
  check('the page has no password', !(await c.js(`document.documentElement.outerHTML + JSON.stringify(localStorage)`)).includes(password));
  const unexpected = c.problems.filter(p => !/Failed to load resource|status of 4/.test(p));
  check('no page exceptions', unexpected.length === 0, [...new Set(unexpected)].slice(0, 4).join(' | '));

  // The explorer, as a judge opens it. A read of a public page.
  if (!FORK) {
    await c.send('Page.navigate', { url: link(steps.txs.payout) });
    await wait(9000);
    const page = await c.js(`document.body.innerText`).catch(() => '');
    check('the explorer shows the payout', page.toLowerCase().includes(steps.txs.payout.toLowerCase()) && /success/i.test(page), page.slice(0, 200));
    await shot('14-explorer-payout');
  }

  console.log('  slowest page requests:', JSON.stringify(await c.js(`[...(window.__net?.done ?? [])].sort((a, b) => b[1] - a[1]).slice(0, 5)`)));
  const times = [...seenReceipts.entries()].filter(([, v]) => v.got).map(([, v]) => `${v.got - v.first} ms, ${v.asks} asks`);
  console.log('  page receipt waits:', times.join('; ') || 'none');
  const end = await usdcNow();
  console.log('  USDC now', Object.entries(end).map(([k, v]) => `${k} ${usd(v)}`).join(', '));
  run = 'finished';
} catch (err) {
  check('the flow finished', false, scrub(err));
  try {
    await c.shot(join(OUT, 'failure.png'));
    console.log('steps:', await stepWords());
    console.log('bar:', scrub(await text('.walletbar')));
    console.log('errors:', scrub(await c.js(`[...document.querySelectorAll('.walleterr, .err, .bad')].map(n => n.innerText).join(' | ')`)));
    console.log('popups:', wallet.popups.join());
    console.log('open requests:', JSON.stringify(await c.js(`[...window.__net.open].map(([k, t]) => [k, Math.round(performance.now() - t)])`)));
    console.log('slowest and last:', JSON.stringify(await c.js(`[...window.__net.done].sort((a, b) => b[1] - a[1]).slice(0, 12).concat(window.__net.done.slice(-12))`)));
    console.log('page problems:', scrub(c.problems.slice(-3).join(' | ')));
  } catch { /* the page is gone */ }
} finally {
  c.close();
  bridge.close();
  await stopDemo();
  anvil?.kill();
  delay?.kill();
  if (FORK) rmSync(boardRoot, { recursive: true, force: true });
}
console.log(FORK ? `PNGs: ${OUT}` : '', failed ? `${failed} failed` : `all passed (${run})`);
setTimeout(() => process.exit(failed ? 1 : 0), 300);
