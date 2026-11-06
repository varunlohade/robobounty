# SimFoundry on a rented NVIDIA machine

This Mac stops at stage 2. Stages 3-14 need the steps below. Nothing here has run yet. The owner holds every account, key and rental.

## Machine

- GPU: RTX 4090, 24 GB, with `s7_mesh.low_vram=true`. Docs floor is 16 GiB. Stage 7 default needs about 29 GiB. An RTX 5090, 32 GB, needs no flag.
- Disk: 300 GB on one volume. Docs say about 250 GB for all envs. The core four envs use less, but no doc gives a figure.
- System RAM and CPU: 64 GB and 8 vCPU. This is my estimate. The docs do not state it.
- OS: Linux. CUDA 12.8 at exactly `/usr/local/cuda-12.8`, because `install_any6d.sh` hard-codes that path.
- SSH: use a full SSH port, not the web terminal. The install runs for hours.

## Time and cost

RunPod list prices, read 2026-11-06. Check them before you start.

| Card | Community | Secure |
|---|---|---|
| RTX 4090 | $0.34/h | $0.89/h |
| RTX 5090 | $0.69/h | $1.19/h |

- Install: "hours" per the docs. Assume 4 hours. This is my estimate.
- Scene: about 20 minutes for 3 tabletop objects, per the docs. The README claims under an hour.
- One first run: about 5 hours. That is about $2 on Community or $5 on Secure, with a 4090.
- Extra: storage for the volume, and Gemini calls in stages 3, 5, 6, 8, 11. I did not measure either one.

## Do this before you pay for a machine

1. Ask for Hugging Face access to `facebook/sam3` and `briaai/RMBG-2.0`. README also lists `facebook/dinov3-vitl16-pretrain-lvd1689m`. Approval can take time. Anonymous requests to the first two get 401 today.
2. Make a Hugging Face read token.
3. Make a Gemini API key at AI Studio.

## Commands

On the Mac, send the input. The file must exist first.

```bash
scp -P <port> design/shell/hull-scan.mp4 root@<host>:/workspace/
```

On the machine. Run the preflight first and stop if a line fails.

```bash
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
command -v mamba git-lfs ffmpeg
ls -d /usr/local/cuda-12.8
df -h /workspace

cd /workspace
git lfs install
git clone https://github.com/NVlabs/SimFoundry.git
cd SimFoundry
nohup bash scripts/installation/install_everything.sh --only "simfoundry hunyuan any6d da3" > install.log 2>&1 &
tail -f install.log
```

After the install, in the shell you run from:

```bash
export HF_TOKEN=<owner token>
export GEMINI_API_KEY=<owner key>
export GCLOUD_PROJECT=<any project name>
bash scripts/installation/download_checkpoints.sh --default
```

First prove the machine on NVIDIA's own sample. Then run the hull.

```bash
bash scripts/pipeline/A_reconstruction/run.sh --scene-name fruits \
  --video-fpath docs/assets/example_videos/Fruits.mp4 -- s7_mesh.low_vram=true

bash scripts/pipeline/A_reconstruction/run.sh --scene-name hull \
  --video-fpath /workspace/hull-scan.mp4 -- s7_mesh.low_vram=true
```

Results land in `Data/<scene>/s14_og/`. Copy them back:

```bash
scp -P <port> -r root@<host>:/workspace/SimFoundry/Data/hull ./policy/simfoundry_lab/work/
```

Stop the machine when you finish. A stopped pod can still bill for storage.

## What can go wrong

- Stages 13-14 import OmniGibson on Isaac Sim, headless. The install guide also shows Isaac Sim log noise from stage 11. I have not tested Isaac Sim in a RunPod container, and Vulkan may be missing there. If this fails, stage 10 output and any stage 11-12 output still exist under `Data/<scene>/`.
- The hull will likely fail at stage 3. It looks for one flat `desk, table, counter`, and rejects frames whose surface does not fit a plane. Objects must be 1.5-60 cm above that plane. A curved hull with a robot under it is outside that design. The input is a render, not real footage.
- The room is not reconstructed by default. Automatic background generation is listed as "coming soon". The published example uses a phone scan placed by hand.
- `--bg-splat` adds a background splat, but this needs the extra envs and more disk.

## Licenses

The repo's own license table marks required parts as restricted. Read it before any paid use.

- FoundationPose and Any6D: non-commercial.
- Depth Anything 3 large weights, which stage 2 uses: CC-BY-NC-4.0.
- Hunyuan3D-2.1: no grant in the EU, UK or South Korea.
- SimFoundry's own code: Apache-2.0.
