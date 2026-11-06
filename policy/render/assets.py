#!/usr/bin/env python3
"""Fetches the CC0 maps for the v2 look into design/render/_cache. Git ignores them. Safe to re-run.

Poly Haven (polyhaven.com) and ambientCG (ambientcg.com) release these under CC0 1.0.
"""
import subprocess
import zipfile
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "design" / "render" / "_cache"
SKY = "kloofendal_overcast_puresky"
MAPS = ["SurfaceImperfections003", "SurfaceImperfections013", "SurfaceImperfections015", "SurfaceImperfections016",
        "Fingerprints003", "Scratches003", "Smear005", "Leaking016A", "Metal051A"]


def fetch(url, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["curl", "-sSL", "--retry", "5", "-C", "-", "-o", str(dst), url])


def main():
    sky = CACHE / "hdri" / f"{SKY}.exr"
    if not sky.exists():
        fetch(f"https://dl.polyhaven.org/file/ph-assets/HDRIs/exr/4k/{SKY}_4k.exr", sky)
    for name in MAPS:
        d = CACHE / "tex" / name
        if list(d.glob("*.jpg")):
            continue
        z = d / "a.zip"
        fetch(f"https://ambientcg.com/get?file={name}_2K-JPG.zip", z)
        with zipfile.ZipFile(z) as f:
            for m in f.namelist():
                if m.endswith(".jpg"):
                    (d / Path(m).name).write_bytes(f.read(m))
        z.unlink()
        print("fetched", name)


if __name__ == "__main__":
    main()
