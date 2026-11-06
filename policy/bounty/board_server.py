"""Bounty board server on 127.0.0.1:5298. It accepts only the board page's origin and host, on every route. A request with no Origin is refused.

One gate runs at a time, and at most QUEUE_CAP wait. Each tester name gets MAX_PER_TESTER submissions per bounty. World ID is not connected, so a new name gets past that cap.
LOCAL LEDGER. NOT ON CHAIN. No money, wallet, key or account exists here. Results are simulated with hand-built physics.

GET  /api/health
GET  /api/bounties
GET  /api/bounties/<id>
GET  /api/bounties/<id>/submissions
GET  /api/bounties/<id>/submissions/<n>
POST /api/bounties                     {title, company, scenarios, cap, per_failure, limits, window?}
POST /api/bounties/<id>/submit         {tester, world, seed}
POST /api/bounties/<id>/failures/<fingerprint>/reject|finalize   {}
POST /api/bounties/<id>/failures/<fingerprint>/claim             {tester, secret}. submit returned the secret, once.
POST /api/bounties/<id>/submissions/<n>/replay                   {}, writes the replay of the recorded run once
GET  /api/bounties/<id>/submissions/<n>/replay/<file>
"""
import argparse
import json
import os
import queue
import re
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board_fix_routes
import board_gate
import board_spec
import board_store as B
import gate as G

HOST = "127.0.0.1"
PORT = 5298
PAGE_ORIGINS = {f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (5299, 5199, os.environ.get("CRASHLAB_WEB_PORT", 5199))}  # 5199 serves the site that holds bounties.html. scripts/demo.sh sets the port when vite runs on another one.
QUEUE_CAP = 4
MAX_WORLD_BYTES = G.MAX_SUBMISSION_BYTES
MAX_SUBMIT_BODY = 3 * MAX_WORLD_BYTES  # JSON escapes make the body larger than the world, and the world has its own limit
MAX_POST_BODY = MAX_WORLD_BYTES
MAX_STEP_BODY = 256
POST_FIELDS = {"title", "company", "scenarios", "cap", "per_failure", "limits"}
SUBMIT_FIELDS = {"tester", "world", "seed"}
ROUTE = re.compile(r"/api/bounties/([0-9]{1,9})(?:/(submit|submissions)(?:/([0-9]{1,9}))?)?")
STEP_ROUTE = re.compile(r"/api/bounties/([0-9]{1,9})/failures/(0x[0-9a-f]{64})/(reject|finalize|claim)")
REPLAY_ROUTE = re.compile(r"/api/bounties/([0-9]{1,9})/submissions/([0-9]{1,9})/replay(?:/([a-z.]+))?")
REPLAY_FILES = {"manifest.json": "application/json", "model.xml": "application/xml", "qpos.json": "application/json", "result.json": "application/json", "world.json": "application/json",
                "controller.py.txt": "text/plain", "trace.json": "application/json", "wind.json": "application/json", "dirt.bin": "application/octet-stream"}
LABELS = {"ledger_label": B.LEDGER_LABEL, "world_id_label": B.WORLD_ID_LABEL}
ERROR_STATUS = {"unknown_bounty": 404, "unknown_submission": 404, "tester_cap": 429, "ledger_refused": 409, "no_recorded_run": 404, "replay_refused": 409, **board_fix_routes.ERROR_STATUS}

ROOT = B.ROOT
WAITING = queue.Queue(QUEUE_CAP)
SUBMIT_LOCK = threading.Lock()
EXPORT_LOCK = threading.Lock()


def worker():
    while True:
        row, world = WAITING.get()
        try:
            board_gate.run(row, world, ROOT)
        except Exception:
            result = {"accepted": False, "code": "gate_crashed", "reason": "The board stopped this submission with an error, so there is no verdict.", "stage": "gate", "runs": 0, "check_passed": False}
            B.save_submission({**row, "state": "done", "result": result}, ROOT)


class Refused(Exception):
    def __init__(self, status, code, reason):
        super().__init__(reason)
        self.status, self.code, self.reason = status, code, reason


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "crashlab-board"
    sys_version = ""
    timeout = 30

    def log_message(self, *_):
        return

    def allowed(self):
        return self.headers.get("Origin") in PAGE_ORIGINS and self.headers.get("Host", "") in {f"{HOST}:{PORT}", f"localhost:{PORT}"}

    def head(self, status, ctype, length):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if self.allowed():
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.send_header("Content-Length", str(length))

    def reply(self, status, obj):
        body = json.dumps(obj).encode()
        self.head(status, "application/json", len(body))
        self.end_headers()
        self.wfile.write(body)

    def fail(self, status, code, reason):
        if status >= 400 and status not in (404, 409, 429, 503):
            self.close_connection = True  # the body may be unread
        self.reply(status, {"error": code, "reason": reason, **LABELS})

    def do_OPTIONS(self):
        if not self.allowed():
            return self.fail(403, "origin_refused", "This origin or host is not the board page.")
        self.head(204, "text/plain", 0)
        self.send_header("Access-Control-Allow-Methods", "GET, POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "60")
        self.end_headers()

    def body(self, limit, fields, optional=()):
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            raise Refused(415, "bad_content_type", "The body must be application/json.")
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdigit():
            raise Refused(411, "no_length", "The request needs a Content-Length.")
        if int(length) > limit:
            raise Refused(413, "body_too_large", f"The body is larger than {limit} bytes.")
        try:
            value = json.loads(self.rfile.read(int(length)).decode("utf-8"), parse_constant=G.W._reject_constant, object_pairs_hook=G._no_duplicate_keys)
        except (ValueError, RecursionError, OverflowError):
            raise Refused(400, "bad_json", "The body is not strict JSON.") from None
        if not isinstance(value, dict) or not fields <= set(value) <= fields | set(optional):
            raise Refused(400, "bad_fields", f"The body must have exactly these fields: {', '.join(sorted(fields))}.")
        return value

    def do_GET(self):
        if not self.allowed():
            return self.fail(403, "origin_refused", "This origin or host is not the board page.")
        try:
            if board_fix_routes.route(self, "GET", ROOT):
                return None
            if self.path == "/api/health":
                return self.reply(200, {"ok": True, "waiting": WAITING.qsize(), "queue_cap": QUEUE_CAP, "max_per_tester": B.MAX_PER_TESTER, "robot": B.ROBOT, "sim_label": B.SIM_LABEL, "max_world_bytes": MAX_WORLD_BYTES, "fields": G.W.FIELDS, "reference_world": G.W.load(board_spec.NOMINAL), "aliases": board_spec.ALIASES, **LABELS})
            if self.path == "/api/bounties":
                return self.reply(200, {"bounties": B.list_bounties(ROOT), **LABELS})
            m = REPLAY_ROUTE.fullmatch(self.path)
            if m and m[3]:
                return self.replay_file(int(m[1]), int(m[2]), m[3])
            m = ROUTE.fullmatch(self.path)
            if not m or m[2] == "submit":
                return self.fail(404, "not_found", "There is no such route.")
            bounty_id = int(m[1])
            if m[3]:
                return self.reply(200, {**B.get_submission(bounty_id, int(m[3]), ROOT), **LABELS})
            if m[2]:
                return self.reply(200, {"submissions": B.list_submissions(bounty_id, ROOT), **LABELS})
            return self.reply(200, B.get(bounty_id, ROOT))
        except B.BoardError as e:
            return self.fail(ERROR_STATUS.get(e.code, 400), e.code, e.reason)

    def do_POST(self):
        if not self.allowed():
            return self.fail(403, "origin_refused", "This origin or host is not the board page.")
        try:
            if board_fix_routes.route(self, "POST", ROOT):
                return None
            if self.path == "/api/bounties":
                return self.post_bounty()
            m = ROUTE.fullmatch(self.path)
            if m and m[2] == "submit" and not m[3]:
                return self.submit(int(m[1]))
            m = STEP_ROUTE.fullmatch(self.path)
            if m:
                v = self.body(MAX_STEP_BODY, {"tester", "secret"} if m[3] == "claim" else set())
                row = B.ledger_step(int(m[1]), m[2], m[3], v.get("tester"), ROOT, secret=v.get("secret"))
                return self.reply(200, {"failure": row, "bounty": B.get(int(m[1]), ROOT), **LABELS})
            m = REPLAY_ROUTE.fullmatch(self.path)
            if m and not m[3]:
                return self.make_replay(int(m[1]), int(m[2]))
            self.close_connection = True
            return self.fail(404, "not_found", "There is no such route.")
        except Refused as r:
            return self.fail(r.status, r.code, r.reason)
        except B.BoardError as e:
            return self.fail(ERROR_STATUS.get(e.code, 400), e.code, e.reason)

    def make_replay(self, bounty_id, n):
        self.body(MAX_STEP_BODY, set())
        B.get_submission(bounty_id, n, ROOT)
        if not EXPORT_LOCK.acquire(blocking=False):
            raise Refused(503, "replay_busy", "Another replay is being written. Try again in a few seconds.")
        try:
            board_gate.export_replay(bounty_id, n, ROOT)
        finally:
            EXPORT_LOCK.release()
        return self.reply(200, {"base": f"/api/bounties/{bounty_id}/submissions/{n}/replay", **LABELS})

    def replay_file(self, bounty_id, n, name):
        B.get_submission(bounty_id, n, ROOT)
        path = ROOT / str(bounty_id) / "submissions" / str(n) / "replay" / name
        if name not in REPLAY_FILES or not path.is_file():
            return self.fail(404, "not_found", "There is no such replay file.")
        data = path.read_bytes()
        self.head(200, REPLAY_FILES[name], len(data))
        self.end_headers()
        self.wfile.write(data)

    def post_bounty(self):
        v = self.body(MAX_POST_BODY, POST_FIELDS, ("window",))
        window = {"window": v["window"]} if "window" in v else {}
        return self.reply(201, B.post(v["title"], v["company"], v["scenarios"], v["cap"], v["per_failure"], v["limits"], root=ROOT, **window))

    def submit(self, bounty_id):
        v = self.body(MAX_SUBMIT_BODY, SUBMIT_FIELDS)
        world = v["world"]
        if not isinstance(world, str):
            raise Refused(400, "bad_world", "The world must be the pasted text of one JSON file.")
        if len(world.encode("utf-8", "replace")) > MAX_WORLD_BYTES:
            raise Refused(413, "world_too_large", f"The world is larger than {MAX_WORLD_BYTES} bytes.")
        with SUBMIT_LOCK:
            B.require_room(bounty_id, v["tester"], ROOT)
            if B.get(bounty_id, ROOT)["status"] != "open":
                raise Refused(409, "cap_reached", "The cap of this bounty is used up.")
            if WAITING.full():
                raise Refused(503, "queue_full", f"{QUEUE_CAP} submissions are already waiting. Try again soon. This did not use one of your submissions.")
            secret = B.new_claim_secret()
            row = B.reserve(bounty_id, v["tester"], v["seed"], ROOT, secret=secret)
            WAITING.put_nowait((row, world))
            ahead = WAITING.qsize() - 1
        return self.reply(202, {"claim_secret": secret, "n": row["n"], "state": row["state"], "ahead": ahead, "used": row["used_before"] + 1, "of": B.MAX_PER_TESTER, **LABELS})


def main():
    global ROOT, PORT
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(B.ROOT))
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    ROOT, PORT = Path(a.root), a.port
    ROOT.mkdir(parents=True, exist_ok=True)
    B.mark_interrupted(ROOT)
    threading.Thread(target=worker, daemon=True).start()
    board_fix_routes.start(ROOT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True

    def stop(*_):
        board_gate.stop_running()
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"CrashLab bounty board on http://{HOST}:{PORT}. {B.LEDGER_LABEL} {B.WORLD_ID_LABEL}.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
