// Signs a World ID request and hashes a signal with the official IDKit code. JSON on stdin and stdout. The signing key comes from the env, for this process only.
import { signRequest } from '@worldcoin/idkit-core/signing';
import { hashSignal } from '@worldcoin/idkit-core/hashing';

let text = '';
for await (const chunk of process.stdin) text += chunk;
const req = JSON.parse(text);
if (req.op === 'hash') {
  console.log(JSON.stringify({ signal_hash: hashSignal(req.signal) }));
} else if (req.op === 'sign') {
  const s = signRequest({ signingKeyHex: process.env.WORLD_RP_SIGNING_KEY, action: req.action, ttl: 300 });
  console.log(JSON.stringify({ sig: s.sig, nonce: s.nonce, created_at: s.createdAt, expires_at: s.expiresAt }));
} else {
  process.exit(2);
}
