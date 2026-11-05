#!/bin/sh
# Task 1: one real SmolVLA episode on LIBERO on Apple Silicon.
cd "$(dirname "$0")"
export LIBERO_CONFIG_PATH=$PWD/.libero MUJOCO_GL=cgl PYTORCH_ENABLE_MPS_FALLBACK=1 TOKENIZERS_PARALLELISM=false WANDB_MODE=disabled
exec .venv/bin/lerobot-eval --policy.path=HuggingFaceVLA/smolvla_libero --env.type=libero --env.task=libero_spatial --eval.n_episodes=1 --eval.batch_size=1 --policy.device=mps --output_dir=runs/ep1 --seed=1
