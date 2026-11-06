// MOCK of the two ethers calls in zg/check.mjs. No network, and no key.
export class JsonRpcProvider {}
export const Wallet = { createRandom: () => ({ connect: () => ({}) }) };
