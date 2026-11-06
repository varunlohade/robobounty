"""The text-to-3D service on the pod. Standard library only. It binds to localhost, so the only way in is the SSH tunnel. Prompts reach it as data, in a fixed charset.

POST /image {"prompt", "mode", "seed"} draws one picture. POST /mesh {"image", "mode", "seed"} builds a textured GLB from a finished picture. GET /job/<id>, /image/<id>, /glb/<id> and /health read.
The same request returns the same job. Finished jobs stay on /workspace.
"""
import hashlib
import itertools
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path("/workspace/t3d")
OUT = ROOT / "out"
PORT = 18765
MODES = ("quality",)
MAX_SEED = 1000
PROMPT_RE = re.compile(r"[A-Za-z0-9 ,.'()/:;%-]{3,1000}")
ID_RE = re.compile(r"[0-9a-f]{16}")
ENV = {**os.environ, "HF_HOME": str(ROOT / "hf"), "HY3DGEN_MODELS": str(ROOT / "hy3dgen"), "U2NET_HOME": str(ROOT / "u2net"), "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}
JOBS = {}
TODO = queue.PriorityQueue()
ORDER = itertools.count()
LOCK = threading.Lock()
STATUS = {"state": "starting", "load_s": None}


class Worker:
    def __init__(self, python, script):
        log = open(ROOT / f"{Path(script).stem}.log", "ab")
        self.p = subprocess.Popen([str(ROOT / python / "bin/python"), str(ROOT / "svc" / script)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, env=ENV, text=True, bufsize=1)

    def read(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("worker died")
        return json.loads(line)

    def send(self, row):
        self.p.stdin.write(json.dumps(row) + "\n")
        self.p.stdin.flush()


def update(job, **fields):
    with LOCK:
        job.update(fields)
    (OUT / job["id"] / "job.json").write_text(json.dumps(job))


def run_image(img, job):
    update(job, state="running", stage="image")
    img.send({"prompt": job["prompt"], "out": str(OUT / job["id"] / "image.png"), "seed": job["seed"], "mode": job["mode"]})
    made = img.read()
    if "error" in made:
        return update(job, state="failed", stage="failed", error=made["error"])
    update(job, state="done", stage="done", seconds=made["seconds"], peak_gb=made["peak_gb"], timing={"image": made["seconds"]})


def run_mesh(hy, job):
    folder = OUT / job["id"]
    shutil.copyfile(OUT / job["image"] / "image.png", folder / "image.png")
    update(job, state="running", stage="shape")
    hy.send({"folder": str(folder), "seed": job["seed"], "mode": job["mode"]})
    while True:
        row = hy.read()
        if "stage" not in row:
            break
        update(job, stage=row["stage"])
    if "error" in row:
        return update(job, state="failed", stage="failed", error=row["error"])
    update(job, state="done", stage="done", seconds=row["seconds"], faces=row["faces"], peak_gb=row["peak_gb"], timing=row["timing"], glb_sha256=hashlib.sha256((folder / "textured.glb").read_bytes()).hexdigest())


def loop():
    started = time.time()
    STATUS["state"] = "loading"
    try:
        img, hy = Worker("venv-img", "img_worker.py"), Worker("venv-hy", "hy_worker.py")
        img.read()
        hy.read()
    except (RuntimeError, ValueError):
        STATUS["state"] = "worker_failed"
        return
    STATUS.update(state="ready", load_s=round(time.time() - started, 1))
    while True:
        _, _, job = TODO.get()
        try:
            (run_image(img, job) if job["kind"] == "image" else run_mesh(hy, job))
        except Exception as error:  # a dead worker fails the job and stops the service, so nobody waits on it
            update(job, state="failed", stage="failed", error=type(error).__name__)
            STATUS["state"] = "worker_failed"
            return


def submit(fields):
    jid = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:16]
    with LOCK:
        job = JOBS.get(jid)
        if job and job["state"] != "failed":
            return job
        job = {"id": jid, **fields, "state": "queued", "stage": "queued", "queued_at": time.time()}
        JOBS[jid] = job
    (OUT / jid).mkdir(parents=True, exist_ok=True)
    TODO.put((MODES.index(fields["mode"]), next(ORDER), job))
    return job


def _mode_seed(body):
    mode, seed = body.get("mode", "quality"), body.get("seed", 0)
    if mode not in MODES or isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
        raise ValueError
    return mode, seed


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if parts[0] == "health":
            with LOCK:
                active = sum(j["state"] in ("queued", "running") for j in JOBS.values())
                done = [j["seconds"] for j in JOBS.values() if j["state"] == "done" and j["kind"] == "mesh" and j["mode"] == "quality"]
            return self.send(200, {**STATUS, "active": active, "mean_seconds": round(sum(done) / len(done), 1) if done else None})
        if len(parts) == 2 and parts[1] in JOBS:
            job = JOBS[parts[1]]
            if parts[0] == "job":
                return self.send(200, job)
            if parts[0] == "glb" and job["state"] == "done" and job["kind"] == "mesh":
                return self.send(200, (OUT / job["id"] / "textured.glb").read_bytes(), "model/gltf-binary")
            if parts[0] == "image" and job["state"] == "done" and job["kind"] == "image":
                return self.send(200, (OUT / job["id"] / "image.png").read_bytes(), "image/png")
        return self.send(404, {"error": "not_found"})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 8192)))
            mode, seed = _mode_seed(body)
            if self.path == "/image":
                if not isinstance(body["prompt"], str) or not PROMPT_RE.fullmatch(body["prompt"]):
                    raise ValueError
                return self.send(200, submit({"kind": "image", "prompt": body["prompt"], "mode": mode, "seed": seed}))
            if self.path == "/mesh":
                image = body["image"]
                if not isinstance(image, str) or not ID_RE.fullmatch(image) or JOBS.get(image, {}).get("state") != "done" or JOBS[image]["kind"] != "image":
                    raise ValueError
                return self.send(200, submit({"kind": "mesh", "image": image, "mode": mode, "seed": seed}))
        except (ValueError, KeyError, AttributeError, TypeError):
            return self.send(400, {"error": "bad_request"})
        return self.send(404, {"error": "not_found"})


def main():
    OUT.mkdir(exist_ok=True)
    for path in OUT.glob("*/job.json"):
        job = json.loads(path.read_text())
        if job["state"] == "done" and "kind" in job:
            JOBS[job["id"]] = job
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
