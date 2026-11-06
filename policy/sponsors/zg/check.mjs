// Our own check of one 0G reply, with the official SDK: processResponse(provider, chatID). JSON on stdin and stdout. It needs no key: the wallet is random and only reads.
// Prints {"result": true|false|null} or {"result": "unavailable", "why": <fixed code>}. The caller treats anything but true as not verified.
const sdkName = process.env.ZG_SDK_MODULE || '@0gfoundation/0g-compute-ts-sdk';
const ethersName = process.env.ZG_ETHERS_MODULE || 'ethers';
const say = o => { console.log(JSON.stringify(o)); process.exit(0); };
let text = '';
for await (const chunk of process.stdin) text += chunk;
const req = JSON.parse(text);
let sdk, ethers;
try {
  sdk = await import(sdkName);
  ethers = await import(ethersName);
} catch {
  say({ result: 'unavailable', why: 'sdk_not_installed' });
}
try {
  const provider = new ethers.JsonRpcProvider(process.env.ZG_RPC_URL || 'https://evmrpc.0g.ai');
  const wallet = ethers.Wallet.createRandom().connect(provider);
  const broker = await sdk.createZGComputeNetworkBroker(wallet);
  const result = await broker.inference.processResponse(req.provider, req.chat_id);
  say({ result: result === true || result === false ? result : null });
} catch {
  say({ result: 'unavailable', why: 'check_threw' });
}
