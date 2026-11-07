// The browser's own wallet, through EIP-1193 (MetaMask, Rabby). No key ever reaches this page. Each failure becomes one plain sentence.
import { encodeFunctionData, formatUnits, stringToHex } from 'viem';
import type { ArcConfig, FundPlan } from './api.ts';

interface Provider { request(a: { method: string; params?: unknown[] }): Promise<any>; on?(event: string, run: (...a: any[]) => void): void }
const provider = (): Provider | null => (window as unknown as { ethereum?: Provider }).ethereum ?? null;

export class WalletError extends Error {}
const NO_WALLET = 'No browser wallet found. Install MetaMask or Rabby, then reload this page.';
const RECEIPT_MS = 120_000;
const RECEIPT_POLL_MS = 500;
const RECEIPT_READ_MS = 3_000;
let chainRpc: string | null = null; // Set when the page moves to the chain. Only read from: it sends nothing and signs nothing.
const TIP_WEI = 1_000_000_000n;
const ARC_TESTNET = '0x4cef52'; // 5042002. Fixed here, so a page or server fault cannot move a send to another chain.

const codeOf = (e: any): number | undefined => e?.code ?? e?.data?.originalError?.code ?? e?.cause?.code;
function plain(e: unknown, rejected: string): Error {
  if (e instanceof WalletError) return e;
  const code = codeOf(e);
  if (code === 4001) return new WalletError(rejected);
  if (code === -32002) return new WalletError('Your wallet already has a request open. Open the wallet and answer it.');
  return new WalletError(`The wallet refused this: ${(e as Error)?.message?.split('\n')[0] ?? 'no reason given'}. Nothing is marked as done.`);
}

async function ask(method: string, params: unknown[], rejected: string) {
  const p = provider();
  if (!p) throw new WalletError(NO_WALLET);
  const asked = performance.now();
  try { return await p.request({ method, params }); } catch (e) { throw plain(e, rejected); } finally { console.info(`[wallet] ${method}: ${((performance.now() - asked) / 1000).toFixed(1)} s`); }
}

export const hasWallet = () => provider() !== null;
export const onWalletChange = (run: () => void) => { const p = provider(); p?.on?.('accountsChanged', run); p?.on?.('chainChanged', run); };
export const shownUsdc = (base: string | bigint) => Number(formatUnits(BigInt(base), 6)).toFixed(2);

// No popup: only what the wallet already allows this page.
export async function current(): Promise<{ address: string | null; chain: string | null }> {
  const p = provider();
  if (!p) return { address: null, chain: null };
  const [accounts, chain] = await Promise.all([p.request({ method: 'eth_accounts' }), p.request({ method: 'eth_chainId' })]).catch(() => [[], null]);
  return { address: accounts?.[0]?.toLowerCase() ?? null, chain: chain ? String(chain).toLowerCase() : null };
}

export async function connect(): Promise<string> {
  const accounts = await ask('eth_requestAccounts', [], 'You rejected the wallet connection. Nothing was shared.');
  if (!accounts?.[0]) throw new WalletError('The wallet shared no account. Unlock it and try again.');
  return accounts[0].toLowerCase();
}

const NETWORK = (c: ArcConfig) => ({ chainId: c.chain_hex, chainName: c.real ? 'Arc Testnet' : 'Local stand-in chain', nativeCurrency: { name: 'USDC', symbol: 'USDC', decimals: 18 }, rpcUrls: [c.rpc_url], ...(c.explorer_home ? { blockExplorerUrls: [c.explorer_home] } : {}) });

export async function useArc(c: ArcConfig) {
  chainRpc = c.rpc_url ?? null;
  const name = c.real ? 'Arc testnet' : 'the local stand-in chain';
  const rejected = `You rejected the network switch. Your wallet stays on another network, so nothing was sent.`;
  const p = provider();
  if (!p) throw new WalletError(NO_WALLET);
  try {
    await p.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: c.chain_hex }] });
  } catch (e) {
    if (codeOf(e) !== 4902) throw plain(e, rejected);
    await ask('wallet_addEthereumChain', [NETWORK(c)], rejected);
    await ask('wallet_switchEthereumChain', [{ chainId: c.chain_hex }], rejected);
  }
  const chain = String(await p.request({ method: 'eth_chainId' })).toLowerCase();
  if (chain !== c.chain_hex) throw new WalletError(`Your wallet is on another network. Switch it to ${name}. Nothing was sent.`);
}

export async function sign(address: string, message: string) {
  return ask('personal_sign', [stringToHex(message), address], 'You rejected the signature. Nothing was saved.') as Promise<string>;
}

// A wallet that sets too low a fee on Arc gets dropped with no error, so the server's fee goes along with each send.
async function send(address: string, to: string, data: string, plan: { fee_wei: string }, what: string): Promise<string> {
  const fee = BigInt(plan.fee_wei);
  const chain = String(await ask('eth_chainId', [], `You rejected the ${what} in your wallet. Nothing was sent.`)).toLowerCase();
  if (chain !== ARC_TESTNET) throw new WalletError('Your wallet is on another network, so nothing was sent. Press the button again to switch back.');
  return ask('eth_sendTransaction', [{ from: address, to, data, chainId: ARC_TESTNET, maxFeePerGas: `0x${fee.toString(16)}`, maxPriorityFeePerGas: `0x${(TIP_WEI < fee ? TIP_WEI : fee).toString(16)}` }], `You rejected the ${what} in your wallet. Nothing was sent.`);
}

// Rabby can take minutes to answer a receipt request, so the page also reads the chain itself. Whichever sees the receipt first wins, and a slow wallet blocks nothing.
async function chainReceipt(tx: string) {
  if (!chainRpc) return null;
  try {
    const res = await fetch(chainRpc, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_getTransactionReceipt', params: [tx] }), signal: AbortSignal.timeout(RECEIPT_READ_MS) });
    return (await res.json()).result ?? null;
  } catch { return null; }
}

export async function waitReceipt(tx: string, what: string) {
  const until = Date.now() + RECEIPT_MS;
  let fromWallet: any = null;
  let asking = false;
  while (Date.now() < until) {
    if (!asking) {
      asking = true;
      void ask('eth_getTransactionReceipt', [tx], '').then(got => { fromWallet = got; }, () => { /* the chain read still runs */ }).finally(() => { asking = false; });
    }
    const got = await chainReceipt(tx) ?? fromWallet;
    if (got) {
      if (BigInt(got.status) !== 1n) throw new WalletError(`The ${what} reverted on chain. It moved no money.`);
      return got;
    }
    await new Promise(r => setTimeout(r, RECEIPT_POLL_MS));
  }
  throw new WalletError(`No receipt for the ${what} after ${RECEIPT_MS / 1000} s. It may still land, so check your wallet before you try again.`);
}

const APPROVE = [{ type: 'function', name: 'approve', stateMutability: 'nonpayable', inputs: [{ type: 'address', name: 'spender' }, { type: 'uint256', name: 'amount' }], outputs: [{ type: 'bool' }] }] as const;
const CREATE = [{ type: 'function', name: 'createBounty', stateMutability: 'nonpayable', inputs: [{ type: 'address', name: 'resolver' }, { type: 'address', name: 'arbiter' }, { type: 'bytes32', name: 'specHash' }, { type: 'uint256', name: 'cap' }, { type: 'uint256', name: 'perFailure' }, { type: 'uint256', name: 'topPrize' }, { type: 'uint64', name: 'deadline' }, { type: 'uint64', name: 'grace' }, { type: 'uint64', name: 'disputeWindow' }], outputs: [{ type: 'uint256' }] }] as const;
const CLAIM = [{ type: 'function', name: 'claim', stateMutability: 'nonpayable', inputs: [{ type: 'uint256', name: 'bountyId' }, { type: 'bytes32', name: 'fingerprint' }], outputs: [] }] as const;

export const sendApprove = (address: string, plan: FundPlan) => send(address, plan.usdc, encodeFunctionData({ abi: APPROVE, args: [plan.contract as `0x${string}`, BigInt(plan.approve ?? plan.cap)] }), plan, 'USDC approval');
export const sendCreate = (address: string, plan: FundPlan) => send(address, plan.contract, encodeFunctionData({ abi: CREATE, args: [plan.resolver as `0x${string}`, plan.arbiter as `0x${string}`, plan.spec_hash as `0x${string}`, BigInt(plan.cap), BigInt(plan.per_failure), BigInt(plan.top_prize), BigInt(plan.deadline), BigInt(plan.grace), BigInt(plan.dispute_window)] }), plan, 'bounty funding');
export const sendClaim = (address: string, contract: string, chainBounty: number, fingerprint: string, fee_wei: string) => send(address, contract, encodeFunctionData({ abi: CLAIM, args: [BigInt(chainBounty), fingerprint as `0x${string}`] }), { fee_wei }, 'claim');
