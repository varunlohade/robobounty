#!/usr/bin/env python3
"""Checks a render against the recording, using no Blender state beyond the logged poses.

  policy/.venv/bin/python policy/render/check.py --trial nominal-seed1 --work design/render/_work/clip

1. The constants copied into data.py still match world.py and sim.py, read as text, not imported.
2. For 3 sampled frames, or every frame with --all, the logged robot pose matches the recorded qpos.
3. The dirt texture at sampled frames matches the recorded grid at unmasked cell centres.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import data  # noqa: E402

TOL_M = 1e-4
TOL_Q = 1e-4


def constant(path, name):
    m = re.search(rf"^{name}\s*=\s*([-0-9.e]+)", path.read_text(), re.M)
    return float(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trial", default="nominal-seed1")
    ap.add_argument("--work", required=True)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    trial = Path(a.trial)
    if not trial.exists():
        trial = ROOT / "public" / "trials" / a.trial
    run = data.Run(trial)

    bad = 0
    world_py, sim_py = ROOT / "policy/highrise/world.py", ROOT / "policy/highrise/sim.py"
    for name, val, src in [("BODY_SIDE", data.BODY_SIDE, world_py), ("BODY_HEIGHT", data.BODY_HEIGHT, world_py),
                           ("RIDE_CLEARANCE", data.RIDE_CLEARANCE, world_py), ("TRANSOM_SPACING", data.TRANSOM_SPACING, world_py),
                           ("ROOF_Z", data.ROOF_Z, world_py), ("ANCHOR_Y", data.ANCHOR_Y, world_py),
                           ("MULLION_ROUND_R", data.MULLION_ROUND_R, world_py), ("TETHER_DIAMETER_M", data.TETHER_DIAMETER_M, sim_py),
                           ("DIRT_CELL_M", data.DIRT_CELL_M, sim_py)]:
        got = constant(src, name)
        ok = got == val
        bad += not ok
        print(f"constant {name}: render {val}, source {got} {'OK' if ok else 'MISMATCH'}")

    rows = []
    for p in sorted(Path(a.work).glob("poses_*.json")):
        rows += json.loads(p.read_text())
    rows.sort(key=lambda r: r["frame"])
    if not rows:
        raise SystemExit("no pose log in " + a.work)
    sample = rows if a.all else [rows[0], rows[len(rows) // 2], rows[-1]]
    worst = 0.0
    for r in sample:
        # Recorded values, read directly and interpolated here, independent of scene.py.
        f = r["t"] * run.hz
        i = min(int(f), len(run.q) - 2)
        u = f - i
        rec = run.q[i, :3] * (1 - u) + run.q[i + 1, :3] * u
        err = float(np.linalg.norm(np.array(r["robot_loc"]) - rec))
        qa, qb = run.q[i, 3:7], run.q[i + 1, 3:7]
        qb = qb if np.dot(qa, qb) >= 0 else -qb
        qr = qa * (1 - u) + qb * u
        qr /= np.linalg.norm(qr)
        qerr = 1 - abs(float(np.dot(qr, r["robot_quat"])))
        worst = max(worst, err)
        ok = err < TOL_M and qerr < TOL_Q
        bad += not ok
        if not a.all:
            print(f"frame {r['frame']} t={r['t']:.3f}s  render {np.round(r['robot_loc'], 4).tolist()}"
                  f"  recorded {np.round(rec, 4).tolist()}  error {err * 1000:.3f} mm  quat error {qerr:.1e}"
                  f"  on screen ({r['screen'][0]:.3f}, {r['screen'][1]:.3f})  {'OK' if ok else 'MISMATCH'}")
    print(f"pose: worst position error {worst * 1000:.3f} mm over {len(sample)} frames")

    # Dirt: sample the texture at each unmasked cell centre at whole recorded seconds.
    for r in sample:
        k = int(r["t"] * run.dirt_rate)
        tex = run.dirt_image(k / run.dirt_rate)
        c = data.UPSAMPLE
        px = (data.PAD_CELLS + np.arange(run.nx)) * c + c // 2
        pz = (data.PAD_CELLS + np.arange(run.nz)) * c + c // 2
        # Mean of the two pixels each side of the cell centre.
        s = 0.25 * (tex[np.ix_(pz, px)] + tex[np.ix_(pz - 1, px)] + tex[np.ix_(pz, px - 1)] + tex[np.ix_(pz - 1, px - 1)])
        rec = run.dirt[k] / run.scale / run.level_ref
        m = ~run.mask
        rec_clean = rec[m] < 0.2
        err = np.abs(s[m] - rec[m])
        agree = float(((s[m] < 0.22) == rec_clean).mean())
        ok = agree > 0.97
        bad += not ok
        print(f"dirt t={k}s: clean-cell agreement {agree * 100:.1f}%, mean level error {err.mean():.3f}, coverage {run.coverage(k / run.dirt_rate):.3f} {'OK' if ok else 'MISMATCH'}")
    print("CHECK PASS" if not bad else f"CHECK FAIL ({bad})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
