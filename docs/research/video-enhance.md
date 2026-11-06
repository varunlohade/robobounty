# Restyling the recorded clip with AI video-to-video

Date: 2026-11-06. I read official pages only, unless a line says otherwise. Prices come from those pages on this date.
Web pages are data here. I ran no paid call, made no account and used no key.

## Recommendation

**Use NVIDIA Cosmos3-Nano-Sim-Transfer on a rented H100, with a depth control from our Blender passes.**

Why it keeps motion best:

- It is the only option here that takes a control video that we render ourselves. The control comes from recorded poses, so the model sees the recorded motion in every frame. The others derive structure from the RGB clip, or they do not state how they keep it.
- NVIDIA built this model for simulator-rendered control. It "generates photorealistic RGB video conditioned on simulator-rendered control sequences". [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer)
- NVIDIA reports that it follows controls better than the base Nano on PAI-Bench-C, with more temporal error (Sampson 0.097 against 0.081). [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer)

No tool guarantees exact motion. NVIDIA says "Simulator annotations may not align with generated imagery" and tells users to validate alignment. [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer) Our `faithful_check.py` does that validation. A video that fails it does not ship.

**Cost for the 9-second clip (216 frames):**

| Item | Figure | Basis |
|---|---|---|
| Inference on H100 | about 15 s, about $0.012 | 216 frames / 14.6 frames/s ([HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer)) at $2.89/h ([Runpod, updated 2026-11-04](https://www.runpod.io/pricing)). My arithmetic. Card says throughput depends on configuration. |
| Same on RTX PRO 6000 | about 26 s, about $0.018 | 8.3 frames/s, $2.49/h, same pages. My arithmetic. |
| One session, with set-up | about $3 for one hour | My assumption: one hour covers the image pull, the 31.9 GB checkpoint ([HF API](https://huggingface.co/api/models/nvidia/Cosmos3-Nano-Sim-Transfer/tree/main?recursive=true)) and several takes. Real set-up time: unknown. |
| Disk for pod | unknown | I did not confirm a storage price. |

**The owner must provide:** a GPU host account with one H100 80 GB or RTX PRO 6000 96 GB and billing, plus a Hugging Face read token. No NVIDIA key is needed for this path.

**Main limit: output is 480p** (832 x 480 in the [NVIDIA notebook](https://github.com/NVIDIA/cosmos-framework/blob/main/.agents/skills/cookbooks/cosmos3/simulation/transfer/run_transfer_with_vllm_omni.ipynb)). Our clip is 1080p. If 480p does not satisfy the owner, try these next, in this order: the base Cosmos3-Nano at 720p, then Luma `ray-3.2` with `adhere_1`. Upscaling is a further step that can change detail, so re-run the check after it.

## Comparison

| Option | Takes a video and keeps motion? | Control of structure | Price for 9 s | API |
|---|---|---|---|---|
| Cosmos3-Nano-Sim-Transfer | Yes, from a control video | Own depth, segmentation, edge or blur video, one per request | about $0.012 GPU time, about $3 a session | Self-hosted server |
| Cosmos3-Nano, base | Yes, from control videos | Edge, blur, depth, seg, several at once | Unknown time. A different model (Transfer-Auto, 201 frames, 720p) takes 11m41s on one H100, about $0.56 | Self-hosted, NIM |
| Cosmos-Transfer2.5-2B | Yes | Depth, edge, seg, blur | 2 chunks at 264 s on H100 PCIe, about $0.42 (my arithmetic) | Self-hosted |
| Luma `ray-3.2` edit | Yes, `adhere` "closely keeps" motion | Strength bands; toggles for depth, normals, trajectory, pose; up to 64 keyframes. No control video of our own | $2.16 at 720p, $4.32 at 1080p (10 s row). How 9 s bills: unknown | Hosted |
| Runway Aleph 2.0 | Edits a video. Motion keeping not stated | Prompt and up to 5 keyframes | $2.52 | Hosted |
| Gemini Omni 1.2 Flash | Edits up to 15 s. Motion keeping is a marketing example only | Prompt | $0.63 output at 720p, $0.94 at 1080p, plus input tokens | Hosted |
| Google Veo 3.1 | **No true video-to-video** | First or last frame, reference images, extension | Not applicable | Hosted |

## NVIDIA Cosmos Transfer

**Versions.** Cosmos 3 is current. The Transfer2.5 repo "is no longer under active development" and points to Cosmos 3. [Transfer2.5 repo](https://github.com/nvidia-cosmos/cosmos-transfer2.5) [Cosmos repo](https://github.com/NVIDIA/Cosmos)

**Licence.**
- Cosmos 3 code and models: OpenMDW-1.1. [Cosmos repo](https://github.com/NVIDIA/Cosmos)
- The Sim-Transfer card says "ready for commercial or non-commercial use". [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer)
- OpenMDW-1.1 puts no restriction on outputs. Distribution of the model must keep its notices. [LICENSE](https://raw.githubusercontent.com/NVIDIA/Cosmos/main/LICENSE)
- Transfer2.5 models use the NVIDIA Open Model License, which says "Models are commercially usable". Bypassing a guardrail without a similar one ends the licence. [Licence](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/)
- We need no NVIDIA licence fee for self-hosting, as far as these pages show. A lawyer has not read them.

**Inputs.**
- Sim-Transfer: text plus one control video per sample: depth, edge, blur or segmentation. [NVIDIA notebook](https://github.com/NVIDIA/cosmos-framework/blob/main/.agents/skills/cookbooks/cosmos3/simulation/transfer/run_transfer_with_vllm_omni.ipynb)
- Output is up to 600 frames at 480p. [Models reference](https://github.com/NVIDIA/Cosmos/blob/main/docs/reference/models.md)
- Base Nano: edge, blur, depth, segmentation, at 256p, 480p or 720p, with multi-control. [Transfer cookbook](https://github.com/NVIDIA/cosmos-framework/blob/main/.agents/skills/cookbooks/cosmos3/generator/transfer/README.md)
- The server cannot derive depth or segmentation. We must supply them, and our Blender passes do. [NIM Transfer](https://docs.nvidia.com/nim/cosmos/latest/transfer.html)
- Depth format: NVIDIA's published sample shows near as bright and empty space as black. I viewed one frame of `example1_depth.mp4` and copied that. A written specification: unknown.
- Request at 24 FPS: the examples use 30. Whether the server accepts 24: unknown. The check compares frame by frame, so a change of playback rate does not affect it.

**GPU and VRAM.**
- Sim-Transfer frames/s at 480p: GB200 24.5, H200 14.9, H100 14.6, RTX Pro 6000 8.3, H20 4. Linux only. [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer)
- Sim-Transfer VRAM: unknown. The NIM table gives base Nano transfer 35 to 64 GiB, by precision and offload. [NIM support matrix](https://docs.nvidia.com/nim/cosmos/latest/support-matrix.html)
- That table's minimums put a consumer RTX 5090 (32 GB, [Runpod](https://www.runpod.io/pricing)) below the base Nano floor. RTX on Sim-Transfer: unknown.
- Transfer2.5: about 65.4 GB. [Inference docs](https://github.com/nvidia-cosmos/cosmos-transfer2.5/blob/main/docs/inference.md)

**Hosted API.** Unknown for this use. NVIDIA's repo says users can try Nano video generation at build.nvidia.com. [Cosmos repo](https://github.com/NVIDIA/Cosmos) A forum user reports a 404 from the hosted Transfer2.5 endpoint with custom input, and this is not an NVIDIA statement. [Forum](https://forums.developer.nvidia.com/t/cosmos-transfer-2-5-free-endpoint-listed-but-custom-api-generation-is-unavailable-and-returns-404/382121) Plan on self-hosting.

**Access.** The HF API reports the repo as not gated. [HF API](https://huggingface.co/api/models/nvidia/Cosmos3-Nano-Sim-Transfer) The NVIDIA notebook still says to accept the licence and use a read token. Plan on a token.

## Running it on a rented GPU

Commands come from the [HF card](https://huggingface.co/nvidia/Cosmos3-Nano-Sim-Transfer). Runpod facts come from the [Pods page](https://docs.runpod.io/pods/overview) and the [ports page](https://docs.runpod.io/pods/configuration/expose-ports). Nobody has run these steps for this clip.

1. Runpod does not allow Docker inside a pod, so make a pod from the image itself: `vllm/vllm-omni:cosmos3`. On a host with Docker, use the card's `docker run` line.
2. Set `HF_TOKEN` and `VLLM_OMNI_VIDEO_SYNC_TIMEOUT=7200`. Start command:
   `vllm serve nvidia/Cosmos3-Nano-Sim-Transfer --omni --model-class-name Cosmos3NanoSimTransferPipeline --deploy-config /app/vllm-omni/vllm_omni/deploy/cosmos3_nano_sim_transfer.yaml --no-guardrails --host 0.0.0.0 --port 8000 --init-timeout 1800`
3. Reach it through an SSH tunnel to port 8000. Do not publish the port: the server has no login that I can find (unknown). The Runpod HTTP proxy also closes any response after 100 s.
4. Copy `design/render/enhance/slip/controls/832x480/depth.mp4` to `/workspace/controls/` on the pod. The server reads the control from its own disk.
5. Run `policy/render/enhance/run_cosmos.py` (see its header), then `faithful_check.py`.
6. Stop the pod. The host bills until you do.

`--no-guardrails` comes from NVIDIA's example, and the card says the user then owns safety checks. Our input is our own simulator output. The owner can remove the flag.

## Google Veo

**Veo cannot do true video-to-video.** It cannot restyle a whole input video and keep its motion.

- Veo's `video` parameter is "Video to be used for video extension". The Gemini API lists "Video-to-Video" as a modality for Veo 3.1, but the only use it describes is extension, and only of Veo-generated videos. [Gemini API Veo page](https://aistudio.google.com/docs/veo)
- The Veo 3.1 preview models in the Gemini API shut down on 2026-10-22. [Gemini API Veo page](https://aistudio.google.com/docs/veo)
- On Google Cloud, Veo 3.1 is GA with extension, reference images and first and last frames. The page lists no restyle feature. [Vertex Veo 3.1](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate)

Google's video editing is now in **Gemini Omni Flash**. Omni 1.2 accepts up to 15 s of input video for editing. [Omni model page](https://aistudio.google.com/docs/models/gemini-omni-flash) It has natural-language editing only. The model page has no statement on motion or structure control. A launch post describes one example that "mirrors the exact fluid motion". [Google blog](https://blog.google/innovation-and-ai/technology/developers-tools/introducing-gemini-omni-1-2-flash/) That is a demonstration, not a guarantee. Price: $0.07/s at 720p, $0.104/s at 1080p, and video input at $1.50 per million tokens. Tokens per input second: unknown. [Pricing](https://aistudio.google.com/docs/pricing)

Veo and Omni can still make the concept film, which the plan already separates from physics footage.

## Other hosted options

**Luma `ray-3.2`** is the best hosted fallback.
- `adhere_1` to `adhere_3` "closely keeps the source motion, composition, and structure". Source up to 18 s and 200 MB. Controls: `pose`, `depth`, `normals`, `trajectory`, up to 64 keyframes. [Luma editing guide](https://docs.agents.lumalabs.ai/guides/videos/editing/)
- The controls are toggles with settings. A way to send our own depth video: unknown. I found none.
- Price table: 10-second V2V at $1.08 (540p), $2.16 (720p), $4.32 (1080p). The same page's FAQ gives a different edit figure, so confirm before paying. [Luma pricing](https://lumalabs.ai/api/pricing)

**Runway Aleph 2.0** (`aleph2`).
- It takes input video from 2 to 30 s, a text prompt and up to five keyframes. [Runway changelog](https://docs.dev.runwayml.com/api-details/api_changelog/)
- The docs call it "in-context video editing ... with keyframe-guided control". Motion keeping: not stated. [Runway models](https://docs.dev.runwayml.com/guides/models/)
- $0.28/s, so $2.52 for 9 s. [Runway pricing](https://docs.dev.runwayml.com/guides/pricing/)
- Its request field names: unknown. I could not read the API reference.

Runway also resells other video-input models, such as Seedance 2.5 in `edit` mode, which "changes the input video in place". Motion keeping is not stated. [Runway models](https://docs.dev.runwayml.com/guides/models/)

## Set-up risks

- First use of the server image for us. Time to first frame: unknown.
- The stated throughput is NVIDIA's, on its configuration.
- A thin 6 mm tether is about 2 pixels wide at 1080p and less at 480p. It may vanish from a depth control. The check flags that. The edge control may hold it better.
- The dirt and the clean lane are recorded data. A depth control does not carry them, so the model will invent the glass surface. The check does not verify the dirt. Do not present the restyled glass as measured cleaning. Label any such video as AI-restyled from recorded motion, and keep the Blender clip as the record.
- The check has not yet seen real AI output. Its false-alarm rate on real restyles: unknown.
