// 0G Storage upload and download, with the official SDK. Testnet only. JSON on stdin and stdout. Every error is a fixed code, because SDK text can hold anything.
// {op: "upload", path} opens the keystore named by ZG_WALLET_KEYSTORE, with the password in ZG_WALLET_PASSWORD_FILE. Only this process ever holds the key, and it never prints it. {op: "download", root_hash, out} needs no key.
import { readFileSync } from 'node:fs';
const TESTNET = 16602n;
const say = o => { console.log(JSON.stringify(o)); process.exit(0); };
const rpc = process.env.ZG_STORAGE_RPC || 'https://evmrpc-testnet.0g.ai';
const indexerUrl = process.env.ZG_STORAGE_INDEXER || 'https://indexer-storage-testnet-turbo.0g.ai';
let text = '';
for await (const chunk of process.stdin) text += chunk;
const req = JSON.parse(text);
let sdk, ethers;
try {
  sdk = await import(process.env.ZG_STORAGE_SDK_MODULE || '@0gfoundation/0g-storage-ts-sdk');
  ethers = await import(process.env.ZG_ETHERS_MODULE || 'ethers');
} catch { say({ error: 'sdk_not_installed' }); }
const indexer = new sdk.Indexer(indexerUrl);
try {
  if (req.op === 'download') {
    const failed = await indexer.download(req.root_hash, req.out, true);
    say(failed ? { error: 'download_failed' } : { ok: true });
  }
  const provider = new ethers.JsonRpcProvider(rpc);
  if ((await provider.getNetwork()).chainId !== TESTNET) say({ error: 'wrong_network' });
  let wallet;
  try {
    wallet = await ethers.Wallet.fromEncryptedJson(readFileSync(process.env.ZG_WALLET_KEYSTORE, 'utf8'), readFileSync(process.env.ZG_WALLET_PASSWORD_FILE, 'utf8').trim());
  } catch { say({ error: 'bad_keystore' }); }
  wallet = wallet.connect(provider);
  if ((await provider.getBalance(wallet.address)) === 0n) say({ error: 'empty_balance' });
  const file = await sdk.ZgFile.fromFilePath(req.path);
  const [tree, treeError] = await file.merkleTree();
  if (treeError) { await file.close(); say({ error: 'hash_failed' }); }
  const local = tree.rootHash();
  const [tx, failed] = await indexer.upload(file, rpc, wallet);
  await file.close();
  if (failed) say({ error: 'upload_failed' });
  if (tx.rootHash !== local) say({ error: 'root_mismatch' });
  say({ root_hash: tx.rootHash, tx: tx.txHash });
} catch { say({ error: 'upload_failed' }); }
