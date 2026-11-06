// MOCK of the ethers calls in zg/check.mjs and zg/storage.mjs. No network. It opens no real keystore: it only checks that the file is there and the password is not empty.
import { readFileSync } from 'node:fs';
export class JsonRpcProvider {
  async getNetwork() { return { chainId: BigInt(process.env.ZG_MOCK_CHAIN ?? 16602) }; }
  async getBalance() { return BigInt(process.env.ZG_MOCK_BALANCE ?? 10 ** 17); }
}
export const Wallet = {
  createRandom: () => ({ connect: () => ({}) }),
  fromEncryptedJson: async (text, password) => {
    if (!JSON.parse(text).crypto || !password) throw new Error('mock');
    return { address: '0x' + 'ab'.repeat(20), connect() { return this; } };
  },
};
