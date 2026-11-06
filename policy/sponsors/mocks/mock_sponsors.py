"""LOCAL MOCK of the 0G Router and the World ID verify endpoint and World App. Loopback only. It proves nothing about the real services: no signature or zero-knowledge proof is checked here.

mock_sponsors.py --port N. Shapes follow the official docs as read on 2026-11-06.
"""
import argparse
import hashlib
import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "server" / "fixtures"
PROVIDER = "0x" + "d9" * 20
KEY = "mock-zg-key-not-a-secret"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, obj, headers=()):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send(204, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path == "/v1/chat/completions":
            return self.chat(body)
        if self.path.startswith("/api/v4/verify/"):
            return self.verify(body)
        if self.path == "/mock/world-app":
            return self.world_app(body)
        self.send(404, {"error": "not_found"})

    def chat(self, body):
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self.send(401, {"error": {"code": "invalid_api_key"}})
        if self.headers.get("X-0G-Provider-Trust-Mode") != "private" or body.get("verify_tee") is not True:
            return self.send(400, {"error": {"code": "mock_wants_private_and_verify_tee"}})
        model = body.get("model", "")
        if model == "mock-no-provider":
            return self.send(503, {"error": {"code": "no_provider_for_trust_mode"}})
        schema_text = body["messages"][0]["content"]
        fixture = "scenarios.json" if '"groups"' in schema_text else "brief.json"
        content = (FIXTURES / fixture).read_text() if (FIXTURES / fixture).exists() else '{"ok": true}'
        if '"findings"' in schema_text:
            content = '{"findings": []}'
        if model == "mock-not-json":
            content = "<script>not json</script>"
        if model == "mock-duplicate-keys":
            content = '{"a": 1, "a": 2}'
        tail = {"mock-sig-bad": "bad", "mock-no-tee": "none", "mock-check-throws": "throw"}.get(model, "good")
        request_id = uuid.uuid4().hex
        trace = {"request_id": request_id, "provider": PROVIDER, "billing": {"input_cost": "1", "output_cost": "2", "total_cost": "3"}, "tee_verified": model != "mock-router-false"}
        self.send(200, {"id": f"chat-{request_id}-{tail}", "choices": [{"message": {"role": "assistant", "content": content}}], "x_0g_trace": trace},
                  headers=[("ZG-Res-Key", f"chat-{request_id}-{tail}")])

    def verify(self, body):
        env = body.get("environment")
        items = body.get("responses") or []
        if not items or any(str(i.get("proof", [""])[0]).startswith("0xbad") for i in items):
            return self.send(400, {"success": False, "code": "all_verifications_failed", "detail": "On-chain proof verification failed.",
                                   "results": [{"identifier": i.get("identifier"), "success": False, "code": "verification_error"} for i in items]})
        self.send(200, {"success": True, "action": body.get("action"), "environment": env, "results": [{"identifier": i["identifier"], "success": True, "nullifier": i["nullifier"]} for i in items]})

    def world_app(self, body):
        """Stands in for a phone. Same human key, same nullifier: this is how a replay looks."""
        human = str(body.get("human", "human-1"))
        if body.get("outcome") == "reject":
            return self.send(200, {"success": False, "error": "user_rejected"})
        nullifier = "0x" + hashlib.sha256(f"{human}|{body['action']}".encode()).hexdigest()
        self.send(200, {"success": True, "result": {"protocol_version": "4.0", "nonce": body["nonce"], "action": body["action"], "environment": body.get("environment"),
                                                     "responses": [{"identifier": "proof_of_human", "signal_hash": body["signal_hash"], "proof": ["0xaa"] * 5, "nullifier": nullifier, "issuer_schema_id": 1, "expires_at_min": 1756166400}]}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
