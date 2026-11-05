"""One real SmolVLA episode on a varied LIBERO scene: run_scene.py <scene.json> --out <dir>"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scene as scene_schema

MODEL_ID = "HuggingFaceVLA/smolvla_libero"
MODEL_REVISION = "6721902bc4d61e50a3bfdb11dfb4cb626f05d102"
MAX_STEPS = 280  # lerobot's limit for libero_spatial
GENESIS = "0" * 64


def load_policy(device, env_cfg):
    from huggingface_hub import snapshot_download
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.envs.factory import make_env_pre_post_processors
    from lerobot.policies import make_policy, make_pre_post_processors

    path = snapshot_download(MODEL_ID, revision=MODEL_REVISION, local_files_only=True)
    cfg = PreTrainedConfig.from_pretrained(path)
    cfg.pretrained_path = Path(path)
    cfg.device = device
    policy = make_policy(cfg=cfg, env_cfg=env_cfg)
    policy.eval()
    pre, post = make_pre_post_processors(
        policy_cfg=cfg, pretrained_path=cfg.pretrained_path,
        preprocessor_overrides={"device_processor": {"device": device}},
    )
    env_pre, env_post = make_env_pre_post_processors(env_cfg=env_cfg, policy_cfg=cfg)
    return policy, pre, post, env_pre, env_post


def video_frame(obs):
    import numpy as np
    pixels = obs["pixels"]
    return np.concatenate([pixels["image"][::-1, ::-1], pixels["image2"][::-1, ::-1]], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="mps")
    args = ap.parse_args()

    try:
        scene = scene_schema.load(args.scene)
    except (scene_schema.SceneError, OSError) as e:
        print(f"REJECTED {args.scene}: {e}", file=sys.stderr)
        return 2
    out = Path(args.out)
    if (out / "result.json").exists():
        print(f"REFUSED: {out} already holds a result", file=sys.stderr)
        return 2

    started = time.time()
    import numpy as np
    import torch
    from lerobot.envs.configs import LiberoEnv as LiberoEnvConfig
    from lerobot.envs.utils import preprocess_observation
    from lerobot.utils.constants import ACTION
    from lerobot.utils.io_utils import write_video
    from lerobot.utils.random_utils import set_seed

    import sim

    out.mkdir(parents=True, exist_ok=True)
    (out / "scene.json").write_text(scene_schema.canonical(scene) + "\n")
    digest = scene_schema.scene_hash(scene)
    result = {
        "status": "scene_invalid", "success": None, "steps": 0, "reason": "scene_invalid",
        "scene_sha256": digest, "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "device": args.device, "control_hz": sim.CONTROL_HZ, **sim.versions(),
    }

    set_seed(scene["seed"])
    wrapper, raw_obs, settle = sim.prepare(scene)
    inner = wrapper._env.env
    result["task"] = wrapper.task_description
    result["settle"] = settle
    result["model_state_sha256"] = sim.model_sha(inner.sim)
    result["start_state_sha256"] = sim.state_sha(inner.sim)
    if not settle["valid"]:
        result["wall_s"] = time.time() - started
        (out / "result.json").write_text(json.dumps(result, indent=1) + "\n")
        print(f"SCENE INVALID: {settle['problems']}", file=sys.stderr)
        wrapper.close()
        return 3

    env_cfg = LiberoEnvConfig(task=sim.SUITE, task_ids=[scene["task_id"]], observation_height=sim.IMAGE_SIZE,
                              observation_width=sim.IMAGE_SIZE, fps=sim.CONTROL_HZ)
    policy, pre, post, env_pre, env_post = load_policy(args.device, env_cfg)
    policy.reset()
    set_seed(scene["seed"])

    outcome = sim.Outcome(wrapper)
    observation = wrapper._format_raw_obs(raw_obs)
    frames = [video_frame(observation)]
    head = sim.step_digest(GENESIS, -1, [], result["start_state_sha256"])
    success = bad_action = False
    out_of_range = steps = 0
    episode_start = time.time()
    with (out / "actions.jsonl").open("w") as log, torch.no_grad():
        log.write(json.dumps({"i": -1, "a": [], "s": result["start_state_sha256"], "h": head}) + "\n")
        while steps < MAX_STEPS and not success:
            batch = preprocess_observation(sim.batched(observation))
            batch["task"] = [wrapper.task_description]
            batch = pre(env_pre(batch))
            action = post(policy.select_action(batch))
            action = env_post({ACTION: action})[ACTION]
            action = action.to("cpu").numpy()[0].astype(np.float64)
            if action.shape != (7,) or not np.isfinite(action).all():
                bad_action = True
                break
            out_of_range += int(np.any(np.abs(action) > 1.0))
            observation, _, _, _, info = wrapper.step(action)
            success = bool(info["is_success"])
            steps += 1
            outcome.update()
            frames.append(video_frame(observation))
            values = [float(x) for x in action]
            state = sim.state_sha(inner.sim)
            head = sim.step_digest(head, steps - 1, values, state)
            log.write(json.dumps({"i": steps - 1, "a": values, "s": state, "h": head}) + "\n")

    reason, metrics = outcome.finish(success, bad_action)
    (out / "final_state.json").write_text(json.dumps(sim.final_state(inner.sim)) + "\n")
    write_video(out / "video.mp4", frames, sim.CONTROL_HZ)
    result.update({
        "status": "invalid_action" if bad_action else "completed",
        "success": success, "steps": steps, "reason": reason, "metrics": metrics,
        "actions_out_of_range": out_of_range,
        "wall_s": time.time() - started, "episode_s": time.time() - episode_start,
        "action_chain_head": head, "final_state_sha256": sim.state_sha(inner.sim),
    })
    (out / "result.json").write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "success", "steps", "reason", "wall_s", "scene_sha256")}))
    wrapper.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
