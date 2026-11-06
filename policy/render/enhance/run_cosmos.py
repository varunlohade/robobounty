#!/usr/bin/env python3
"""Sends one control video to a Cosmos3-Nano-Sim-Transfer server on a GPU host you rent. It spends GPU time, so it
refuses to start without a stated clip and a cost estimate. Check the result with faithful_check.py.

  COSMOS_HOST=http://127.0.0.1:8000 COSMOS_CONTROL_DIR=/workspace/controls \
  policy/.venv/bin/python policy/render/enhance/run_cosmos.py \
      --clip design/render/clip_slip.mp4 --cost-estimate-usd 3 --control depth

Env only: COSMOS_HOST (server URL), COSMOS_CONTROL_DIR (folder on the server that holds <control>.mp4, because the
server reads the control from its own disk), COSMOS_API_KEY (optional, if your proxy needs a bearer token).
--dry-run prints the request and sends nothing.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
MODEL = "nvidia/Cosmos3-Nano-Sim-Transfer"
SIZE = "832x480"  # The model's 480p bucket. The clip's 16:9 is 2.5% off this shape.
TIMEOUT_S = 7260
H100_FPS = 14.6  # The model card's 480p figure.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, required=False)
    ap.add_argument("--cost-estimate-usd", type=float, required=False)
    ap.add_argument("--passes", type=Path, default=ROOT / "design/render/enhance/slip")
    ap.add_argument("--control", choices=["depth", "edge", "seg"], default="depth")
    ap.add_argument("--prompt-file", type=Path, default=HERE / "prompt_slip.txt")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.clip is None:
        sys.exit("refused: state the clip with --clip")
    if a.cost_estimate_usd is None or a.cost_estimate_usd <= 0:
        sys.exit("refused: state a cost estimate above zero with --cost-estimate-usd")
    man = json.loads((a.passes / "manifest.json").read_text())
    if a.clip.resolve() != (ROOT / man["clip"]).resolve():
        sys.exit(f"refused: {a.clip} is not the clip these passes came from ({man['clip']})")
    control = a.passes / "controls" / SIZE / f"{a.control}.mp4"
    if not control.exists():
        sys.exit(f"refused: no control video at {control}. Run export_passes.py first")

    host, remote = os.environ.get("COSMOS_HOST"), os.environ.get("COSMOS_CONTROL_DIR")
    if not host or not remote:
        sys.exit("refused: set COSMOS_HOST and COSMOS_CONTROL_DIR. Copy the control video to that folder on the server")

    frames, fps = man["frames"], man["fps"]
    extra = {"session_id": uuid.uuid4().hex, "reset": True, "close_session": True, "resolution": "480",
             "max_prompt_tokens": 4096, "kv_cache_inference_size": 30, "attention_sink_size": 3,
             "emphasize_control_in_prompt": False, a.control: {"control_path": f"{remote.rstrip('/')}/{a.control}.mp4"}}
    form = {"model": MODEL, "prompt": a.prompt_file.read_text().strip(), "size": SIZE, "num_frames": str(frames),
            "fps": str(fps), "seed": str(a.seed), "extra_params": json.dumps(extra)}
    out = a.out or ROOT / "design/render/enhance/out" / f"{man['shot']}_{a.control}_{a.seed}.mp4"

    print(f"clip {a.clip}, {frames} frames, control {control}")
    print(f"your cost estimate ${a.cost_estimate_usd:.2f}. Inference alone is about {frames / H100_FPS:.0f} s on an H100 by the model card; the host bills from pod start to pod stop")
    if a.dry_run:
        print(json.dumps({"url": f"{host.rstrip('/')}/v1/videos/sync", "form": form}, indent=1))
        return

    headers = {"Accept": "video/mp4"}
    key = os.environ.get("COSMOS_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(f"{host.rstrip('/')}/v1/videos/sync", data=urllib.parse.urlencode(form).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
        body = r.read()
    if body[4:8] != b"ftyp":
        sys.exit(f"server did not return an MP4: {body[:300]!r}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    print(f"{out}\nnext: policy/.venv/bin/python policy/render/enhance/faithful_check.py --video {out} --passes {a.passes}")


if __name__ == "__main__":
    main()
