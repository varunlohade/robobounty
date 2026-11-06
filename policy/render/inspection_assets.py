#!/usr/bin/env python3
"""Fetches the CC0 maps for the inspection render into design/render/_cache/tex. Git ignores them. Safe to re-run.

ambientCG (ambientcg.com) releases these under CC0 1.0. Only .jpg members of each zip are written.
"""
import subprocess
import zipfile
from pathlib import Path

CACHE = Path(__file__).resolve().parents[2] / "design" / "render" / "_cache" / "tex"
MAPS = ["Concrete034", "Concrete042A", "Metal032", "Metal049A", "DiamondPlate008A", "Rust009", "SurfaceImperfections013", "SurfaceImperfections015", "SurfaceImperfections016", "Scratches003"]


def main():
    for name in MAPS:
        d = CACHE / name
        if list(d.glob("*.jpg")):
            continue
        d.mkdir(parents=True, exist_ok=True)
        z = d / "a.zip"
        subprocess.check_call(["curl", "-sSL", "--retry", "5", "-o", str(z), f"https://ambientcg.com/get?file={name}_2K-JPG.zip"])
        with zipfile.ZipFile(z) as f:
            for m in f.namelist():
                if m.endswith(".jpg"):
                    (d / Path(m).name).write_bytes(f.read(m))
        z.unlink()
        print("fetched", name)


if __name__ == "__main__":
    main()
