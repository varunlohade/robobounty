// The whole wallet flow on a local anvil, with a test wallet injected in headless Chrome. No Arc call. Local only: the wallet forwards to anvil's unlocked public dev accounts.
// node src/board/tools/check_wallet.mjs [--ports WEB,RUN,SITE,BOARD] [--anvil PORT] [--record-proof]. Saves design/board/wallet-*.png.
// --record-proof keeps the real gate result of this run for the film, when no stored proof matches.
import { execFileSync, spawn } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { openChrome, wait } from '../../lab/tools/browser.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf(`--${name}`); return i < 0 ? fallback : process.argv[i + 1]; };
const ROOT = resolve(import.meta.dirname, '../../..');
const [webPort, runPort, sitePort, boardPort] = arg('ports', '8199,8198,8297,8298').split(',').map(Number);
const ANVIL = Number(arg('anvil', '7545'));
const RPC = `http://127.0.0.1:${ANVIL}`;
const WEB = `http://localhost:${webPort}`;
const BOARD = `http://127.0.0.1:${boardPort}`;
const OUT = join(ROOT, 'design/board');
const PY = join(ROOT, 'policy/.venv/bin/python');
const USDC = '0x3600000000000000000000000000000000000000';
const COMPANY = '0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266', ENGINEER = '0x70997970c51812dc3a010c7d01b50e0d17dc79c8'; // Anvil's public dev accounts, on this local chain only.
const CHAIN = '0x4cef52';
const PASSWORD = 'local-check-password-not-a-secret';
const STORED = join(ROOT, 'policy/runs/demo/window/stored_proof.json');
const PROOF_S = 1500, POST_S = 300;

let failed = 0;
const check = (name, ok, detail = '') => { if (!ok) failed++; console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? `: ${String(detail).slice(0, 300)}` : ''}`); };
const cast = (...a) => execFileSync('cast', a, { encoding: 'utf8' }).trim();
const rpc = (...a) => cast('rpc', '--rpc-url', RPC, ...a);
const read = (to, sig, ...a) => cast('call', '--rpc-url', RPC, to, sig, ...a);
const num = text => BigInt(text.split(/\s/)[0]);
const usdc = who => num(read(USDC, 'balanceOf(address)(uint256)', who));
const receipt = tx => JSON.parse(rpc('eth_getTransactionReceipt', tx));

const anvil = spawn('anvil', ['--host', '127.0.0.1', '--port', String(ANVIL), '--chain-id', '5042002', '--block-time', '1', '--silent'], { stdio: 'ignore' });
for (let i = 0; i < 50; i++) { try { cast('chain-id', '--rpc-url', RPC); break; } catch { await wait(200); } }
const keys = mkdtempSync(join(tmpdir(), 'wallet-check-keys-'));
for (const role of ['resolver', 'arbiter']) execFileSync('cast', ['wallet', 'new', keys, role, '--unsafe-password', PASSWORD], { stdio: 'ignore' });
execFileSync('sh', ['-c', `umask 077; printf %s '${PASSWORD}' > '${join(keys, 'password')}'`]);
const signer = role => cast('wallet', 'address', '--keystore', join(keys, role), '--password-file', join(keys, 'password')).toLowerCase();
const RESOLVER = signer('resolver'), ARBITER = signer('arbiter');
for (const a of [RESOLVER, ARBITER]) rpc('anvil_setBalance', a, '0x56bc75e2d63100000');
const mock = JSON.parse(readFileSync(join(ROOT, 'contracts/out/Mocks.sol/MockUSDC.json'), 'utf8')).deployedBytecode.object;
rpc('anvil_setCode', USDC, mock);
rpc('anvil_setStorageAt', USDC, '0x0', `0x${'6'.padStart(64, '0')}`);
const unlocked = (from, to, sig, ...a) => cast('send', '--rpc-url', RPC, '--unlocked', '--from', from, to, sig, ...a);
unlocked(COMPANY, USDC, 'mint(address,uint256)', COMPANY, '10000000');

const boardRoot = join(ROOT, `policy/runs/board/wallet_check_${Date.now()}`);
mkdirSync(boardRoot, { recursive: true });
const env = { ...process.env, ARC_RPC_URL: RPC, ARC_WALLET_DIR: keys, ARC_CAP_USDC: '2' };
console.log(execFileSync(PY, [join(ROOT, 'policy/bounty/arc_wallet.py'), 'deploy', '--yes', '--root', boardRoot], { env, encoding: 'utf8' }).split('\n').filter(l => /"contract": "0x/.test(l)).join(''));
const CONTRACT = JSON.parse(readFileSync(join(boardRoot, 'arc.json'), 'utf8')).contract;

const log = [];
const demo = spawn('bash', [join(ROOT, 'scripts/demo.sh'), '--recorded', '--arc', '--ports', `${webPort},${runPort},${sitePort},${boardPort}`, '--board-root', boardRoot], { stdio: ['ignore', 'pipe', 'pipe'], env });
demo.stdout.on('data', d => log.push(String(d)));
demo.stderr.on('data', d => log.push(String(d)));
const t0 = Date.now();
while (!log.join('').includes('Press Ctrl+C')) {
  if (demo.exitCode !== null || Date.now() - t0 > 120_000) throw new Error(`demo.sh did not start: ${log.join('')}`);
  await wait(200);
}
check('demo.sh says the wallet flow is on', log.join('').includes('The wallet flow is on'));

// A test wallet with the shape of MetaMask's. A popup becomes one line in window.__popups. localStorage sets who it is and what it refuses.
const TEST_WALLET = `(() => {
  const state = () => JSON.parse(localStorage.getItem('testWallet') || '{}');
  const put = next => localStorage.setItem('testWallet', JSON.stringify({ ...state(), ...next }));
  if (state().none) return;
  const listeners = {};
  const refuse = () => Object.assign(new Error('User rejected the request.'), { code: 4001 });
  const forward = async (method, params) => { const r = await fetch(${JSON.stringify(RPC)}, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) }); const j = await r.json(); if (j.error) throw Object.assign(new Error(j.error.message), { code: j.error.code }); return j.result; };
  const popup = name => { const log = JSON.parse(localStorage.getItem('testPopups') || '[]'); log.push(name); localStorage.setItem('testPopups', JSON.stringify(log)); };
  window.__wallet = { emit(name, value) { (listeners[name] || []).forEach(f => f(value)); } };
  window.ethereum = {
    on(name, f) { (listeners[name] ||= []).push(f); },
    removeListener() {},
    async request({ method, params = [] }) {
      const s = state();
      if (method === 'eth_chainId') return s.chain || '0x1';
      if (method === 'eth_accounts') return s.connected ? [s.account] : [];
      if (method === 'eth_requestAccounts') { popup('connect'); if (s.reject === 'connect') throw refuse(); put({ connected: true }); return [s.account]; }
      if (method === 'wallet_switchEthereumChain') { popup('switch'); if (s.reject === 'switch') throw refuse(); if (!s.added && params[0].chainId !== '0x1') throw Object.assign(new Error('Unrecognized chain'), { code: 4902 }); put({ chain: params[0].chainId }); return null; }
      if (method === 'wallet_addEthereumChain') { popup('add:' + params[0].chainName + ':' + params[0].nativeCurrency.symbol + ':' + params[0].nativeCurrency.decimals); put({ added: true }); return null; }
      if (method === 'personal_sign') { popup('sign'); if (s.reject === 'sign') throw refuse(); return forward('personal_sign', [params[0], s.signAs || params[1]]); }
      if (method === 'eth_sendTransaction') {
        const selector = params[0].data.slice(0, 10);
        popup('tx:' + selector);
        if (s.chain !== ${JSON.stringify(CHAIN)}) throw new Error('The page sent a transaction on the wrong chain');
        if (s.rejectTx === selector) throw refuse();
        return forward('eth_sendTransaction', [s.revertTx === selector ? { ...params[0], gas: '0xea60' } : params[0]]);
      }
      return forward(method, params);
    },
  };
})();`;

const c = await openChrome({ width: 1440, height: 900 });
await c.send('Network.enable');
await c.send('Page.addScriptToEvaluateOnNewDocument', { source: TEST_WALLET });
const go = path => c.send('Page.navigate', { url: `${WEB}/${path}` });
const text = sel => c.js(`document.querySelector(${JSON.stringify(sel)})?.innerText ?? ''`);
const setWallet = v => c.js(`localStorage.setItem('testWallet', ${JSON.stringify(JSON.stringify(v))})`);
const popups = async () => JSON.parse(await c.js(`localStorage.getItem('testPopups') || '[]'`));
const clearPopups = () => c.js(`localStorage.removeItem('testPopups')`);
const hasButton = label => `[...document.querySelectorAll('button')].find(b => b.textContent.trim() === ${JSON.stringify(label)})`;
const press = async (label, seconds = 30) => { await c.until(`!!${hasButton(label)} && !${hasButton(label)}.disabled`, `the button "${label}"`, seconds); await c.js(`${hasButton(label)}.click()`); };
const walletError = async (words, what) => { await c.until(`(document.querySelector('.walleterr')?.innerText ?? '').includes(${JSON.stringify(words)})`, what, 30); check(what, true, await text('.walleterr')); };
const stepState = name => c.js(`document.querySelector('[data-step="${name}"]')?.dataset.state ?? null`);
const stepTx = name => c.js(`[...document.querySelectorAll('[data-step="${name}"] [data-tx]')].map(n => n.dataset.tx)`);
const shot = async name => { await wait(300); await c.shot(join(OUT, `wallet-${name}.png`)); };
const showChain = () => c.js(`[...document.querySelectorAll('.detail h2')].find(n => n.textContent === 'On chain')?.scrollIntoView({ block: 'start' })`);
const login = async (role, next = 'bounties.html') => {
  await go(`login.html?switch=1&next=${encodeURIComponent(next)}`);
  const label = role === 'company' ? 'Demo company' : 'Demo engineer';
  const find = `[...(document.querySelector('.lg-sheet')?.querySelectorAll('button, a') ?? [])].find(n => n.textContent.trim().startsWith(${JSON.stringify(label)}))`;
  await c.until(`!!${find}`, label, 30);
  await wait(500);
  await c.js(`${find}.click()`);
  await c.until(`location.pathname === '/bounties.html' && document.querySelector('.sh-who')?.dataset.who === ${JSON.stringify(role)}`, `the ${role} session`, 30);
  await c.until(`!!document.querySelector('.walletbar') && !document.querySelector('.walletbar').hidden`, 'the wallet line', 30);
};
const postBounty = async (title, group, pay) => {
  await press('Post a bounty');
  await c.until(`[...document.querySelectorAll('.overlay select option')].some(o => o.value.endsWith(${JSON.stringify(`/${group}`)}) && o.value.startsWith('0000000000000000000000000a4c0001'))`, `the ${group} failure`, 30);
  await c.js(`(() => { const s = document.querySelector('.overlay select'); s.value = [...s.options].find(o => o.value.startsWith('0000000000000000000000000a4c0001') && o.value.endsWith(${JSON.stringify(`/${group}`)})).value; s.dispatchEvent(new Event('change')); const i = document.querySelectorAll('.overlay input'); i[0].value = ${JSON.stringify(title)}; i[2].value = ${JSON.stringify(String(pay))}; })()`);
  const started = Date.now();
  await press('Post the bounty');
  await c.until(`!document.querySelector('.overlay') && document.querySelector('.detail h1')?.textContent === ${JSON.stringify(title)}`, `the bounty "${title}"`, POST_S);
  return (Date.now() - started) / 1000;
};
// A direct request to the board, with this page's board token, as a hostile page script would send it.
const boardPost = (path, body) => c.js(`import('/src/site/auth.ts').then(a => a.boardAuth(true)).then(t => fetch(${JSON.stringify(BOARD + path)}, { method: 'POST', headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' }, body: ${JSON.stringify(JSON.stringify(body))} })).then(async r => ({ status: r.status, body: await r.json() }))`);

try {
  // No wallet.
  await go('login.html');
  await c.until(`document.readyState === 'complete'`, 'login', 30);
  await setWallet({ none: true });
  await login('company');
  check('without a wallet, the page still shows the label', (await text('.walletbar')).includes('Local stand-in chain. Not Arc. Not real money.'), await text('.walletbar'));
  await press('Connect wallet');
  await walletError('No browser wallet found', 'no wallet: a plain message');
  await shot('no-wallet');

  // Wrong network: the person refuses the switch.
  await setWallet({ account: COMPANY, chain: '0x1', reject: 'switch' });
  await go('bounties.html');
  await c.until(`!!${hasButton('Connect wallet')}`, 'Connect', 30);
  await press('Connect wallet');
  await walletError('rejected the network switch', 'wrong network, switch refused: a plain message');
  await c.until(`(document.querySelector('.walletbar')?.innerText ?? '').includes('another network')`, 'the wrong network line', 10);
  check('wrong network: no balance shows as if ready', !(await text('.walletbar')).includes('test USDC'));
  await shot('wrong-network');

  // The right network, which the wallet does not know yet.
  await setWallet({ account: COMPANY, chain: '0x1', connected: true });
  await go('bounties.html');
  await press('Switch network');
  await c.until(`(document.querySelector('.walletbar')?.innerText ?? '').includes('10.00 test USDC')`, 'the balance from the chain', 30);
  check('the wallet is asked to add the chain, USDC with 18 decimals', (await popups()).some(p => p === 'add:Local stand-in chain:USDC:18'), (await popups()).join());
  const bar = await text('.walletbar');
  check('connected: address, balance, label', bar.includes('0xf39fd6') && bar.includes('10.00 test USDC') && bar.includes('Not real money'), bar);
  await shot('connected');

  // Post, then fund with each failure on the way.
  const postS = await postBounty('The robot stops short near the top', 'stalled', 1);
  check('a new bounty says it is not funded', (await text('.list')).includes('Not funded'));
  const shownWorlds = await c.js(`fetch(${JSON.stringify(`${BOARD}/api/bounties/1`)}).then(r => r.json()).then(b => b.public_worlds.map(w => ({ index: w.index, replay: w.replay })))`);
  const worldFile = await c.js(`fetch(${JSON.stringify(`${BOARD}/api/bounties/1/public/`)} + ${JSON.stringify(shownWorlds[0]?.index)} + '/world.json').then(r => r.status)`);
  check('the posted bounty shows its public failing worlds, with replays', shownWorlds.length === 3 && shownWorlds.every(w => w.replay) && worldFile === 200, JSON.stringify(shownWorlds));
  await showChain();
  await shot('not-funded');
  await clearPopups();
  const APPROVE = cast('sig', 'approve(address,uint256)'), CREATE = cast('sig', 'createBounty(address,address,bytes32,uint256,uint256,uint256,uint64,uint64,uint64)');
  await setWallet({ account: COMPANY, chain: CHAIN, connected: true, added: true, rejectTx: APPROVE });
  await press('Fund from my wallet');
  await walletError('rejected the USDC approval', 'rejected tx: a plain message');
  check('rejected tx: nothing on chain', num(read(CONTRACT, 'bountyCount()(uint256)')) === 0n && (await stepState('funded')) === 'live');
  await shot('rejected-tx');

  await setWallet({ account: COMPANY, chain: CHAIN, connected: true, added: true, revertTx: CREATE });
  await press('Fund from my wallet');
  await walletError('reverted on chain', 'reverted tx: a plain message');
  check('reverted tx: the page does not show funded', (await stepState('funded')) === 'live' && !existsSync(join(boardRoot, '1/arc_funding.json')));
  await shot('reverted-tx');
  unlocked(COMPANY, USDC, 'approve(address,uint256)', CONTRACT, '0');

  await setWallet({ account: COMPANY, chain: CHAIN, connected: true, added: true });
  await clearPopups();
  const fundAt = Date.now();
  await press('Fund from my wallet');
  await c.until(`document.querySelector('[data-step="funded"]')?.dataset.state === 'ok'`, 'funded', 60);
  const funding = (await popups()).filter(p => p.startsWith('tx:')).join();
  check('funding sends two wallet transactions, approve then create', funding === `tx:${APPROVE},tx:${CREATE}`, funding);
  const fundTxs = await stepTx('funded');
  check('funded: approve and create have receipts with status 1', fundTxs.length === 2 && fundTxs.every(t => BigInt(receipt(t).status) === 1n), fundTxs.join());
  check('the contract holds the pay', usdc(CONTRACT) === 1_000_000n && usdc(COMPANY) === 9_000_000n);
  await c.until(`(document.querySelector('.walletbar')?.innerText ?? '').includes('9.00 test USDC')`, 'the company balance after funding', 15);
  await showChain();
  await shot('funded');

  // A client cannot claim funding with some other receipt.
  const forged = await boardPost('/api/arc/bounties/1/funded', { create_tx: fundTxs[0] });
  check('another tx hash does not fund a bounty', forged.status === 409 && forged.body.error === 'tx_not_funding', JSON.stringify(forged));

  // The engineer proves a wallet.
  await setWallet({ account: ENGINEER, chain: CHAIN, connected: true, added: true, reject: 'sign' });
  await login('engineer');
  await c.until(`!!${hasButton('Save this wallet')}`, 'Save this wallet', 30);
  check('an unproved engineer cannot submit', await c.js(`${hasButton('Submit a fix')}.disabled`));
  await press('Save this wallet');
  await walletError('rejected the signature', 'rejected signature: a plain message');
  await shot('rejected-signature');
  await setWallet({ account: ENGINEER, chain: CHAIN, connected: true, added: true, signAs: COMPANY });
  await go('bounties.html');
  await press('Save this wallet');
  await walletError('does not come from this wallet', 'a signature from another wallet is refused');
  await setWallet({ account: ENGINEER, chain: CHAIN, connected: true, added: true });
  await go('bounties.html');
  await clearPopups();
  await press('Save this wallet');
  await c.until(`(document.querySelector('.walletbar')?.innerText ?? '').includes('Payout wallet saved')`, 'the saved wallet', 30);
  const side = await text('.sh-who');
  check('the side bar shows the proved wallet', side.includes('0x7099') && side.includes('signature checked'), side);
  await shot('saved');

  // The stored good fix. With a stored proof this is seconds, and without one it is a real proof.
  const hadProof = existsSync(STORED);
  await press('Submit a fix');
  await c.until(`document.querySelector('.overlay textarea')?.dataset.ready === '1'`, 'the source', 30);
  await press('Use the stored good fix');
  await wait(400);
  await press('Run check, then simulation');
  await c.until(`!document.querySelector('.overlay')`, 'the submit', 30);
  const proofAt = Date.now();
  await c.until(`document.querySelector('[data-step="proposed"]')?.dataset.state === 'ok'`, 'the agent proposes', PROOF_S);
  console.log(`  gate to proposal ${((Date.now() - proofAt) / 1000).toFixed(1)} s`);
  const detail = await text('.detail');
  check('the gate accepted this fix', /The fix holds on the hidden worlds/.test(detail), detail.slice(0, 200));
  if (hadProof) check('a recorded proof says so on screen', detail.includes('Recorded proof') && detail.includes('The chain transactions are real'));
  await c.until(`/\\d+ s left/.test(document.querySelector('[data-step="dispute-window"]')?.innerText ?? '')`, 'the countdown', 30);
  await showChain();
  await shot('dispute');
  const firstLeft = Number((await text('[data-step="dispute-window"]')).match(/(\d+) s left/)[1]);
  await wait(3000);
  const nextLeft = Number((await text('[data-step="dispute-window"]')).match(/(\d+) s left/)[1]);
  check('the countdown moves', nextLeft < firstLeft && firstLeft <= 60, `${firstLeft} then ${nextLeft}`);
  check('nothing is paid during the window', usdc(ENGINEER) === 0n);
    let earlyRefused = false;
  try { read(CONTRACT, 'payout(uint256,bytes32)', '1', JSON.parse(readFileSync(join(boardRoot, '1/fixes/1/arc_steps.json'), 'utf8')).fingerprint, '--from', RESOLVER); } catch { earlyRefused = true; }
  check('the contract refuses pay before the window ends', earlyRefused);

  // The agent finalizes and pays. The engineer presses nothing.
  await c.until(`document.querySelector('[data-step="paid"]')?.dataset.state === 'ok'`, 'the agent pays', 150);
  console.log(`  fund to paid ${((Date.now() - fundAt) / 1000).toFixed(1)} s`);
  check('the money reached the engineer, read from the chain', usdc(ENGINEER) === 1_000_000n && usdc(CONTRACT) === 0n, String(usdc(ENGINEER)));
  await c.until(`document.querySelector('.chainbalance')?.dataset.balance === '1000000'`, 'the balance on the page', 15);
  await c.until(`(document.querySelector('.walletbar')?.innerText ?? '').includes('1.00 test USDC')`, 'the engineer balance in the wallet line', 15);
  const steps = JSON.parse(readFileSync(join(boardRoot, '1/fixes/1/arc_steps.json'), 'utf8'));
  const chainTxs = Object.entries(steps.txs);
  check('propose, finalize and payout each have a receipt with status 1', ['propose', 'finalize', 'payout'].every(k => steps.txs[k]) && chainTxs.every(([, t]) => BigInt(receipt(t).status) === 1n), chainTxs.map(([k, t]) => `${k} ${t.slice(0, 10)}`).join(', '));
  check('the agent sent them, from the resolver wallet', ['propose', 'finalize', 'payout'].every(k => receipt(steps.txs[k]).from.toLowerCase() === RESOLVER));
  check('the engineer saw only sign popups, and no transaction', !(await popups()).some(p => p.startsWith('tx:')) && (await popups()).includes('sign'), (await popups()).join());
  check('the list says Paid', (await text('.list')).includes('Paid'));
  await showChain();
  await shot('paid');

  // No double pay, either way.
  const fp = steps.fingerprint;
  const refused = (from, sig) => { try { read(CONTRACT, sig, '1', fp, '--from', from); return false; } catch { return true; } };
  check('double pay: a second payout reverts', refused(RESOLVER, 'payout(uint256,bytes32)'));
  check('double pay: a claim after the payout reverts', refused(ENGINEER, 'claim(uint256,bytes32)'));
  await setWallet({ account: ENGINEER, chain: CHAIN, connected: true, added: true, revertTx: cast('sig', 'claim(uint256,bytes32)') });
  const claimData = cast('calldata', 'claim(uint256,bytes32)', '1', fp);
  const claimTx = await c.js(`ethereum.request({ method: 'eth_sendTransaction', params: [{ from: ${JSON.stringify(ENGINEER)}, to: ${JSON.stringify(CONTRACT)}, data: ${JSON.stringify(claimData)} }] })`);
  for (let i = 0; i < 20 && !JSON.parse(rpc('eth_getTransactionReceipt', claimTx)); i++) await wait(500);
  check('double claim: the tx reverts on chain', BigInt(receipt(claimTx).status) === 0n);
  const again = await boardPost('/api/arc/bounties/1/fixes/1/claimed', { tx: claimTx });
  check('double claim: the server refuses its receipt', again.status === 409 && again.body.error === 'tx_reverted', JSON.stringify(again));
  check('double claim: no money moved', usdc(ENGINEER) === 1_000_000n);
  await setWallet({ account: ENGINEER, chain: CHAIN, connected: true, added: true });

  // The company rejects during the window: a wallet signature, then the arbiter's key.
  await setWallet({ account: COMPANY, chain: CHAIN, connected: true, added: true });
  await login('company');
  await postBounty('The robot slips on the glass', 'slip_distance', 1);
  await press('Fund from my wallet');
  await c.until(`document.querySelector('[data-step="funded"]')?.dataset.state === 'ok'`, 'the second funding', 60);
  const placed = JSON.parse(execFileSync(PY, [join(ROOT, 'policy/bounty/check_wallet_helper.py'), boardRoot, '2', ENGINEER], { encoding: 'utf8' }));
  check('the check placed a fix with no gate, for this rejection only', Boolean(placed.fingerprint));
  await c.until(`/\\d+ s left/.test(document.querySelector('[data-step="dispute-window"]')?.innerText ?? '')`, 'the second window', 30);
  await press('Reject');
  await c.until(`document.querySelector('[data-step="dispute-window"]')?.dataset.state === 'bad'`, 'the rejection on chain', 30);
  const rejected = JSON.parse(readFileSync(join(boardRoot, '2/fixes/1/arc_steps.json'), 'utf8'));
  check('reject: the arbiter sent it, with a receipt', receipt(rejected.txs.reject).from.toLowerCase() === ARBITER && BigInt(receipt(rejected.txs.reject).status) === 1n, rejected.txs.reject);
  check('reject: the money stays in the contract and the engineer got none of it', usdc(CONTRACT) === 1_000_000n && usdc(ENGINEER) === 1_000_000n);
  await showChain();
  await shot('rejected');

  // The cap, in code, before any send.
  await postBounty('Third bounty over the cap', 'coverage', 1).catch(() => null);
  await c.until(`!!${hasButton('Fund from my wallet')}`, 'a third bounty', 10).catch(() => null);
  if (await c.js(`!!${hasButton('Fund from my wallet')}`)) {
    await press('Fund from my wallet');
    await walletError('ARC_CAP_USDC', 'over the cap: refused before any send');
  } else check('over the cap: a third bounty could not be posted to test it', false);

  // Keys.
  const agentLog = log.join('').match(/Agent log: (\S+)/)?.[1];
  const logged = agentLog && existsSync(agentLog) ? readFileSync(agentLog, 'utf8') : '';
  check('the agent log holds no password or key words', Boolean(agentLog) && !logged.includes(PASSWORD) && !/private|mnemonic|keystore/i.test(logged), logged.slice(0, 200));
  const unexpected = c.problems.filter(p => !/Failed to load resource|status of 4/.test(p));
  check('no page exceptions', unexpected.length === 0, [...new Set(unexpected)].slice(0, 4).join(' | '));

  if (process.argv.includes('--record-proof') && !hadProof) console.log(execFileSync(PY, [join(ROOT, 'policy/bounty/arc_wallet.py'), 'record-proof', '--root', boardRoot, '--bounty', '1', '--fix', '1'], { encoding: 'utf8' }));
  console.log(`  post ${postS.toFixed(1)} s`);
} catch (err) {
  check('the flow finished', false, String(err));
  try { await c.shot(join(OUT, 'wallet-failure.png')); console.log('page:', (await text('.walletbar')), '|', (await text('.detail')).slice(0, 800)); } catch { /* the page is gone */ }
} finally {
  c.close();
  demo.kill('SIGINT');
  for (let i = 0; i < 150 && demo.exitCode === null; i++) await wait(100);
  anvil.kill();
  rmSync(keys, { recursive: true, force: true });
  rmSync(boardRoot, { recursive: true, force: true });
}
console.log(failed ? `${failed} failed` : 'all passed');
setTimeout(() => process.exit(failed ? 1 : 0), 300);
