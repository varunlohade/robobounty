"""Text to image on the pod, under venv-img: Qwen-Image-2512, kept on the GPU. One JSON request per stdin line, one JSON reply per stdout line."""
import json
import sys
import time
import traceback

OUT = sys.stdout
sys.stdout = sys.stderr  # imports and pipelines print freely. The reply stream stays clean.
import torch
from diffusers import DiffusionPipeline

NEGATIVE = "text, watermark, logo, people, hands, background scenery, floor, cast shadow, cropped, blurry, cartoon, low quality, multiple objects"


def main():
    pipe = DiffusionPipeline.from_pretrained("Qwen/Qwen-Image-2512", torch_dtype=torch.bfloat16).to("cuda")
    OUT.write(json.dumps({"ready": True}) + "\n")
    OUT.flush()
    for line in sys.stdin:
        req = json.loads(line)
        started = time.time()
        torch.cuda.reset_peak_memory_stats()
        try:
            seed = torch.Generator("cuda").manual_seed(req["seed"])
            image = pipe(prompt=req["prompt"], negative_prompt=NEGATIVE, width=1328, height=1328, num_inference_steps=50, true_cfg_scale=4.0, generator=seed).images[0]
            image.save(req["out"])
            peak = round(torch.cuda.max_memory_reserved() / 2**30, 1)
            torch.cuda.empty_cache()  # gives the VRAM back between jobs, for other work on this card
            row = {"seconds": round(time.time() - started, 1), "peak_gb": peak}
        except Exception as error:  # one bad image fails its job, and the loaded models stay
            traceback.print_exc()
            torch.cuda.empty_cache()
            row = {"error": type(error).__name__}
        OUT.write(json.dumps(row) + "\n")
        OUT.flush()


if __name__ == "__main__":
    main()
