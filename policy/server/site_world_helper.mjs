// Signs a World ID request with the official IDKit code. JSON on stdin and stdout. The signing key comes from the env, for this process only.
import { signRequest } from '@worldcoin/idkit-core/signing';
import { hashSignal } from '@worldcoin/idkit-core/hashing';

let text = '';
for await (const chunk of process.stdin) text += chunk;
const req = JSON.parse(text);
if (req.hash_signal !== undefined) {
  console.log(JSON.stringify({ signal_hash: hashSignal(req.hash_signal) }));
  process.exit(0);
}
const options = { signingKeyHex: process.env.WORLD_RP_SIGNING_KEY, ttl: 300 };
if (req.action) options.action = req.action;
const s = signRequest(options);
console.log(JSON.stringify({ sig: s.sig, nonce: s.nonce, created_at: s.createdAt, expires_at: s.expiresAt }));
