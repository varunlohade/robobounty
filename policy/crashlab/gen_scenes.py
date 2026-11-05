"""Reproducible scene batch: gen_scenes.py --n N --seed S --out <dir>. Scene i does not depend on N."""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene as scene_schema

TARGET_ON_TABLE_TASKS = (0, 1, 2, 6, 8)  # the bowl sits on the table, so it can slide
BOWL_2, COOKIES, RAMEKIN, PLATE = 1, 2, 3, 4
SUPPORT_BY_TASK = {3: COOKIES, 5: RAMEKIN}  # moving these drops the target
TARGET_OFFSET_M, DISTRACTOR_OFFSET_M = 0.05, 0.04


def make_scene(batch_seed, index):
    rng = random.Random(f"crashlab:{batch_seed}:{index}")
    task = rng.randrange(10)
    scene = {
        "schema": 1,
        "task_id": task,
        "init_state": rng.randrange(50),
        "seed": rng.randrange(scene_schema.MAX_SEED + 1),
    }
    moves = []
    if task in TARGET_ON_TABLE_TASKS and rng.random() < 0.7:
        moves.append({
            "object": scene_schema.TARGET_OBJECT,
            "dx": round(rng.uniform(-TARGET_OFFSET_M, TARGET_OFFSET_M), 3),
            "dy": round(rng.uniform(-TARGET_OFFSET_M, TARGET_OFFSET_M), 3),
            "dyaw": round(rng.uniform(-3.14, 3.14), 2),
        })
    for obj in (BOWL_2, COOKIES, RAMEKIN, PLATE):
        if obj != SUPPORT_BY_TASK.get(task) and rng.random() < 0.25:
            moves.append({
                "object": obj,
                "dx": round(rng.uniform(-DISTRACTOR_OFFSET_M, DISTRACTOR_OFFSET_M), 3),
                "dy": round(rng.uniform(-DISTRACTOR_OFFSET_M, DISTRACTOR_OFFSET_M), 3),
                "dyaw": round(rng.uniform(-3.14, 3.14), 2),
            })
    if moves:
        scene["objects"] = moves
    if rng.random() < 0.3:
        scene["light"] = round(rng.uniform(0.5, 1.5), 2)
    if rng.random() < 0.2:
        scene["colours"] = [{
            "object": rng.choice((BOWL_2, COOKIES, RAMEKIN, PLATE)),
            "rgb": [round(rng.random(), 2) for _ in range(3)],
        }]
    if rng.random() < 0.2:
        scene["clutter"] = [{
            "x": round(rng.uniform(-0.25, 0.25), 3),
            "y": round(rng.uniform(-0.1, 0.35), 3),
            "yaw": round(rng.uniform(-3.14, 3.14), 2),
            "half_size": round(rng.uniform(0.015, 0.03), 3),
            "rgb": [round(rng.random(), 2) for _ in range(3)],
        }]
    return scene_schema.validate(scene)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.n < 1 or not 0 <= args.seed <= scene_schema.MAX_SEED:
        ap.error("--n must be at least 1 and --seed must be in [0, 2^31-1]")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for i in range(args.n):
        scene = make_scene(args.seed, i)
        (out / f"scene_{i:05d}.json").write_text(scene_schema.canonical(scene) + "\n")
    print(f"wrote {args.n} scenes to {out}")


if __name__ == "__main__":
    main()
