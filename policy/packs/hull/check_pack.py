"""Runs the hull worlds, judges them from their records, saves the record. Exit code 0 means every check held.

Run from policy/: nice -n 10 .venv/bin/python -m packs.hull.check_pack
Every number is simulated. Nothing here is compared with a real ship or robot.
"""
import json
import sys

import numpy as np

from .. import missing
from . import model as M
from . import pack as P
from . import sim as S
from . import world as W

OUT = S.HERE / "out"
SEED = 0
bad = []


def report(ok, text):
    print(("OK   " if ok else "FAIL ") + text, flush=True)
    if not ok:
        bad.append(text)


def row(name, r):
    print(f"     {name}: {r['verdict']}, coverage {r['coverage']:.1%}, slip p95 {r['wheel_slip_p95']:.1%}, lane error {r['lane_error_max_m']:.3f} m, biggest gap {r['gap_max_m'] * 1000:.1f} mm, time {r['time_s']:.0f} s. {r['reason']}", flush=True)


def worker(world, seed=SEED, out=None):
    rec, meta = P.run(world, seed=seed, out=out)
    return rec, meta, P.judge(rec, world)


def brush_path_mask(rec):
    """Cells within a disc radius of any recorded brush centre, plus a margin of two cells. Everything else must be untouched."""
    xs, ys = S.cell_centres()
    mask = np.zeros(S.grid_shape(), bool)
    idx = [M.BODIES.index(b) for b in M.BRUSHES]
    reach = M.BRUSH_R + 2 * S.CELL_M
    for p in rec["body_q"][::5][:, idx, :2].reshape(-1, 2):
        ix0, ix1 = np.searchsorted(xs, p[0] - reach), np.searchsorted(xs, p[0] + reach)
        iy0, iy1 = np.searchsorted(ys, p[1] - reach), np.searchsorted(ys, p[1] + reach)
        xx, yy = xs[ix0:ix1][None, :] - p[0], ys[iy0:iy1][:, None] - p[1]
        mask[iy0:iy1, ix0:ix1] |= xx * xx + yy * yy <= reach * reach
    return mask


def main():
    report(not missing(P), f"pack exposes the contract, missing: {missing(P)}")
    report(W.call(P.new_world(), "set_current", {"speed_ms": 99.0, "dir_deg": 0.0})["result"] == "cannot_build:out_of_range", "a current of 99 m/s is refused")
    report(W.call(P.new_world(), "nope", {})["result"] == "cannot_build:unknown_function", "an unknown function is refused")
    pic = W.call(P.new_world(), "set_hull_mark", {"text": "FR 200"})
    report(pic["result"] == W.PICTURE and not pic["rerun"], "a hull mark is a picture edit: the physics hash stays the same")

    base = P.new_world()
    rec, meta, res = worker(base, out=OUT / "nominal.npz")
    row("nominal", res)
    report(res["passed"], "the nominal world passes")
    report(abs(meta["total_mass_kg"] - 25.0) < 0.01, f"mass {meta['total_mass_kg']:.1f} kg")
    print(f"     run: {res['time_s']:.0f} s simulated at {meta['rtf']:.0f}x real time. Buoyancy {meta['buoyancy_n']:.0f} N.")

    mask = brush_path_mask(rec)
    s, b = S.final_fouling(rec)
    changed = (np.abs(s - rec["fouling0_slime"] / 255.0) > 1e-6) | (np.abs(b - rec["fouling0_barnacle"] / 255.0) > 1e-6)
    report(int((changed & ~mask).sum()) == 0, f"fouling changed only under the recorded brush paths: {int(changed.sum())} cells changed, {int((changed & ~mask).sum())} outside the paths, {int((~changed).sum())} untouched")

    rec2, _, res2 = worker(base)
    h1, h2 = S.record_hash(rec), S.record_hash(rec2)
    report(h1 == h2, f"same seed repeats exactly: {h1[:16]} and {h2[:16]}")
    rec3, _, res3 = worker(base, seed=SEED + 1)
    row("seed 1", res3)
    report(S.record_hash(rec3) != h1, "another seed gives another record")

    results = {"nominal": res, "seed_1": res3, "record_sha256": h1}
    variants = [
        ("strong_current", ("set_current", {"speed_ms": 2.0, "dir_deg": 90.0})),
        ("thick_seam", ("set_seam", {"height_m": 0.03})),
        ("weak_magnets", ("set_magnet", {"force_n": 60.0, "rear_fraction": 0.35, "gap_scale_m": 0.008})),
    ]
    for name, call in variants:
        world = W.build(call)
        r, _, j = worker(world, out=OUT / f"{name}.npz")
        row(name, j)
        results[name] = j
        report(not j["passed"], f"{name} changes the result: {j['verdict']}")
    (OUT / "results.json").write_text(json.dumps(results, indent=1))
    print("CHECK PASS" if not bad else f"CHECK FAIL ({len(bad)})")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
