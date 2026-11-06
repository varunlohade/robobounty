// MOCK of the 0G Storage SDK, for local checks. A local folder stands in for the network, and the sha256 stands in for the Merkle root. ZG_MOCK_STORAGE picks a failure.
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
const store = () => process.env.ZG_MOCK_STORE;
const root = path => '0x' + createHash('sha256').update(readFileSync(path)).digest('hex');
export class ZgFile {
  constructor(path) { this.path = path; }
  static async fromFilePath(path) { return new ZgFile(path); }
  async merkleTree() { return [{ rootHash: () => root(this.path) }, null]; }
  async close() {}
}
export class Indexer {
  async upload(file) {
    if (process.env.ZG_MOCK_STORAGE === 'hang') await new Promise(r => setTimeout(r, 60000));
    if (process.env.ZG_MOCK_STORAGE === 'fail') return [null, new Error('secret detail from the network')];
    const hash = root(file.path);
    copyFileSync(file.path, `${store()}/${hash}`);
    return [{ rootHash: hash, txHash: '0x' + 'fe'.repeat(32) }, null];
  }
  async download(hash, out) {
    if (!existsSync(`${store()}/${hash}`)) return new Error('missing');
    const data = readFileSync(`${store()}/${hash}`);
    if (process.env.ZG_MOCK_STORAGE === 'tamper') data[0] ^= 1;
    writeFileSync(out, data);
    return null;
  }
}
