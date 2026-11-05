"""Film finish on Blender's linear EXR output: tone curve, restrained grade, soft bloom, grain.

post.py <input.exr> <output.png> [--seed N]
Uses Pillow-free OpenCV for EXR input and PNG output.
"""
import argparse
import os

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2  # noqa: E402
import numpy as np  # noqa: E402

EXPOSURE = 1.0
GRAIN = 0.012


def aces_ish(x):
    """A gentle filmic shoulder (Hable style) with a soft toe, normalised so white stays white."""
    A, B, C, D, E, F = 0.22, 0.30, 0.10, 0.20, 0.01, 0.30
    def f(v):
        return ((v * (A * v + C * B) + D * E) / (v * (A * v + B) + D * F)) - E / F
    return f(x) / f(7.0)


def grade(rgb, seed):
    h, w = rgb.shape[:2]
    x = np.maximum(rgb, 0.0) * EXPOSURE

    # Bloom in linear light: only the brightest skies and rims spill, barely.
    small = cv2.GaussianBlur(x, (0, 0), w / 110.0)
    wide = cv2.GaussianBlur(x, (0, 0), w / 24.0)
    x = x * 0.955 + small * 0.03 + wide * 0.015

    x = aces_ish(x * 1.75)
    # Restrained colour: pull saturation down, cool the shadows toward grey-teal, leave highlights neutral.
    lum = (x * np.array([0.2126, 0.7152, 0.0722])).sum(axis=2, keepdims=True)
    x = lum + (x - lum) * 0.92
    tint = np.array([0.93, 1.005, 1.01])
    x = x * (1 + (tint - 1) * (1 - np.clip(lum, 0, 1)))

    # Display encode, then a small S curve.
    x = np.clip(x, 0, 1) ** (1 / 2.2)
    x = x + 0.11 * (x - 0.5) * (1 - np.abs(2 * x - 1))
    x = np.clip(x, 0, 1)

    # A touch of lens-scale acutance to offset the denoiser, then a slightly lower black point.
    x = np.clip(x + 0.28 * (x - cv2.GaussianBlur(x, (0, 0), 1.1)), 0, 1)
    x = np.clip((x - 0.022) / (1 - 0.022), 0, 1)

    # Grain: monochrome-weighted, slightly soft like a scan, stronger in the mids.
    rng = np.random.default_rng(seed)
    g = rng.normal(0, 1, (h, w, 3)).astype(np.float32)
    g = g * np.array([0.5, 0.5, 0.5]) + g[:, :, [1]] * 0.75
    g = cv2.GaussianBlur(g, (0, 0), 0.62)
    weight = 0.55 + 1.2 * (x * (1 - x) * 4) ** 1.0 * 0.5
    x = x + g * GRAIN * weight
    return np.clip(x, 0, 1)


def process(src, dst, seed=1):
    img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit("cannot read " + src)
    rgb = img[:, :, :3][:, :, ::-1].astype(np.float32)
    out = grade(rgb, seed)
    # 16-bit PNG, so banding in the haze cannot come from this step.
    cv2.imwrite(dst, (out[:, :, ::-1] * 65535 + 0.5).astype(np.uint16))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    process(a.input, a.output, a.seed)
