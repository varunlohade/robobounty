"""Runs Depth Anything 3 (same weights and resolution as SimFoundry stage 2) on Apple MPS.

This is not a SimFoundry entry point. Stage 2 hard-codes device="cuda" and crashes here, so this calls upstream DA3's API directly.
Usage: da3_mps.py <frames_dir> <out_npz> [model]
"""
import glob
import sys
import time

import numpy as np
import torch
from depth_anything_3.api import DepthAnything3

frames = sorted(glob.glob(f"{sys.argv[1]}/*.png"))
model_name = sys.argv[3] if len(sys.argv) > 3 else "DA3NESTED-GIANT-LARGE-1.1"
start = time.time()
model = DepthAnything3.from_pretrained(f"depth-anything/{model_name}").to("mps")
print(f"loaded {model_name} in {time.time() - start:.0f}s", flush=True)
start = time.time()
pred = model.inference(frames, process_res=448)
print(f"inference on {len(frames)} frames took {time.time() - start:.0f}s", flush=True)
print("peak mps MB", torch.mps.driver_allocated_memory() // 2**20, flush=True)
np.savez_compressed(sys.argv[2], depth=pred.depth, conf=pred.conf, extrinsics=pred.extrinsics, intrinsics=pred.intrinsics,
                    images=pred.processed_images, frames=np.array(frames))
print("depth", pred.depth.shape, "range", float(pred.depth.min()), float(pred.depth.max()), flush=True)
