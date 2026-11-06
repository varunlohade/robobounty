"""The two model backends. Each returns (status, text, seconds). A written file is untrusted data: it is read as bytes, and nothing runs it."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import gate as G
import prompt as P

CODEX = "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex"
ASTRA_MODEL = os.environ.get("GENERATOR_ASTRA_MODEL", "gpt-6-astra")
ASTRA_TIMEOUT_S = 900
READ_CAP = G.MAX_BYTES * 2


def _read_regular(path):
    """Refuses a symlink. Reads no more than the cap plus one byte, so the gate still sees an oversized file."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read(READ_CAP + 1)


def astra(brief, previous, reasons, try_dir, network):
    ws = try_dir / "workspace"
    ws.mkdir(parents=True, exist_ok=False)
    text = P.agent_prompt(brief, previous, reasons)
    (try_dir / "prompt.txt").write_text(text)
    cmd = ["nice", "-n", "15", CODEX, "exec", "-m", ASTRA_MODEL, "--skip-git-repo-check", "-s", "workspace-write",
           "-c", f"sandbox_workspace_write.network_access={'true' if network else 'false'}", "-C", str(ws), text]
    t0 = time.time()
    with (try_dir / "codex.log").open("wb") as log:
        try:
            p = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, timeout=ASTRA_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return "error:timeout", None, round(time.time() - t0, 1)
    seconds = round(time.time() - t0, 1)
    (try_dir / "workspace_files.json").write_text(json.dumps(sorted(str(q.relative_to(ws)) for q in ws.rglob("*"))))
    try:
        return "scene", _read_regular(ws / "scene.xml"), seconds
    except FileNotFoundError:
        pass
    except OSError:
        return "error:not_a_regular_file", None, seconds
    try:
        return "declined", _read_regular(ws / "DECLINED.txt"), seconds
    except OSError:
        return (f"error:exit_{p.returncode}" if p.returncode else "error:no_file"), None, seconds


def claude(brief, previous, reasons, try_dir, network):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "crashlab"))
    import llm
    text = P.json_prompt(brief, previous, reasons)
    (try_dir / "prompt.txt").write_text(text)
    t0 = time.time()
    try:
        reply = llm.complete_json(text, P.JSON_SCHEMA)
    except llm.LLMError as e:
        return f"error:{e}", None, round(time.time() - t0, 1)
    seconds = round(time.time() - t0, 1)
    if reply.get("status") == "declined":
        return "declined", str(reply.get("reason", "")).encode()[:READ_CAP], seconds
    if reply.get("status") != "scene" or not isinstance(reply.get("mjcf"), str):
        return "error:bad_reply", None, seconds
    return "scene", reply["mjcf"].encode()[:READ_CAP + 1], seconds


BACKENDS = {"astra": astra, "claude": claude}
