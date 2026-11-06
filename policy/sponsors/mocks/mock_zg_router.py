"""LOCAL MOCK of the 0G Router's chat call, for checks. Loopback only. It proves nothing about the real service: it checks no signature. The model name picks the behaviour.

mock_zg_router.py --port N. Shapes follow docs.0g.ai as read on 2026-11-07.
"""
import argparse
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        if self.path != "/v1/chat/completions":
            return self.send(404, {"error": "not_found"})
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self.send(401, {"error": {"code": "invalid_api_key"}})
        if body.get("model", "").startswith("mock-fast"):  # The fast route: a private header or a TEE request here is a bug.
            if self.headers.get("X-0G-Provider-Trust-Mode") or "verify_tee" in body:
                return self.send(400, {"error": {"code": "mock_fast_wants_no_private_header"}})
            if body["model"] == "mock-fast-503":
                return self.send(503, {"error": {"code": "no_provider"}})
            return self.send(200, {"id": "chat-fast", "choices": [{"message": {"role": "assistant", "content": '{"calls": [], "say": "mock"}'}}], "x_0g_trace": {"request_id": uuid.uuid4().hex, "provider": "0x" + "00" * 20}})
        if self.headers.get("X-0G-Provider-Trust-Mode") != "private" or body.get("verify_tee") is not True or body.get("response_format") != {"type": "json_object"}:
            return self.send(400, {"error": {"code": "mock_wants_private_verify_tee_and_json_mode"}})
        model = body.get("model", "")
        if model == "mock-no-provider":
            return self.send(503, {"error": {"code": "no_provider_for_trust_mode"}})
        if model == "mock-slow":
            time.sleep(30)
        content = {"mock-not-json": "<script>not json</script>", "mock-duplicate-keys": '{"a": 1, "a": 2}'}.get(model, '{"calls": [], "say": "mock"}')
        tail = {"mock-sig-bad": "bad", "mock-no-tee": "none", "mock-check-throws": "throw"}.get(model, "good")
        request_id = uuid.uuid4().hex
        trace = {"request_id": request_id, "provider": PROVIDER, "billing": {"input_cost": "1", "output_cost": "2", "total_cost": "3"}}
        if model not in ("mock-no-tee", "mock-check-throws-no-router"):
            trace["tee_verified"] = model != "mock-router-false"
        self.send(200, {"id": f"chat-{request_id}-{tail}", "choices": [{"message": {"role": "assistant", "content": content}}], "x_0g_trace": trace}, headers=[("ZG-Res-Key", f"chat-{request_id}-{tail}")])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
