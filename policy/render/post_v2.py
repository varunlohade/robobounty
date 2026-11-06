"""Film finish for the v2 look, on Blender's linear EXR: lens faults in linear light, then Blender's own AgX
image formation (baked once to a LUT by bake_agx.py), then a light grade and grain.

post_v2.py <input.exr> <output.png> [--seed N]
"""
import argparse
import os
from pathlib import Path

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LUT_PATH = ROOT / "design" / "render" / "_cache" / "agx_mhc_65.npy"
LG2_MIN, LG2_SPAN = -12.47393, 25.0

EXPOSURE = 1.0
CA = 0.00065         # radial scale difference of red and blue at the frame corner
VIGNETTE = 0.16      # linear-light loss at the corner
BLOOM = (0.016, 0.006)
HALATION = 0.010
SATURATION = 0.96
GRAIN = 0.009
_lut = None


def lut():
    global _lut
    if _lut is None:
        if not LUT_PATH.exists():
            raise SystemExit(f"missing {LUT_PATH}: run bake_agx.py through Blender (render.py does this)")
        _lut = np.load(LUT_PATH).astype(np.float32)
    return _lut


def apply_lut(enc):
    """Trilinear lookup. enc is 0..1 in lg2 space, shape (h, w, 3)."""
    L = lut()
    n = L.shape[0] - 1
    p = np.clip(enc, 0, 1) * n
    i = np.minimum(p.astype(np.int32), n - 1)
    f = p - i
    r, g, b = i[..., 0], i[..., 1], i[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    c00 = L[r, g, b] * (1 - fr) + L[r + 1, g, b] * fr
    c01 = L[r, g, b + 1] * (1 - fr) + L[r + 1, g, b + 1] * fr
    c10 = L[r, g + 1, b] * (1 - fr) + L[r + 1, g + 1, b] * fr
    c11 = L[r, g + 1, b + 1] * (1 - fr) + L[r + 1, g + 1, b + 1] * fr
    c0 = c00 * (1 - fg) + c10 * fg
    c1 = c01 * (1 - fg) + c11 * fg
    return c0 * (1 - fb) + c1 * fb


def radial(ch, k, xx, yy, w, h):
    s = 1 + k * (xx * xx + yy * yy) / 2.0
    mx = (xx * s + 1) * w / 2 - 0.5
    my = (yy * s + 1) * h / 2 - 0.5
    return cv2.remap(ch, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def grade(rgb, seed):
    h, w = rgb.shape[:2]
    x = np.maximum(np.nan_to_num(rgb, posinf=64.0), 0.0) * EXPOSURE
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    aspect = h / w
    xx = (xx + 0.5) / w * 2 - 1
    yy = ((yy + 0.5) / h * 2 - 1) * aspect
    # Lateral chromatic aberration grows toward the corners.
    x = np.dstack([radial(x[..., 0], CA, xx, yy / aspect, w, h),
                   x[..., 1], radial(x[..., 2], -CA, xx, yy / aspect, w, h)])
    # Veiling glare and bloom, then a warm halation from only the hottest highlights.
    near = cv2.GaussianBlur(x, (0, 0), w / 220.0)
    wide = cv2.GaussianBlur(x, (0, 0), w / 28.0)
    x = x * (1 - BLOOM[0] - BLOOM[1]) + near * BLOOM[0] + wide * BLOOM[1]
    hot = np.maximum(x - 2.2, 0)
    x = x + cv2.GaussianBlur(hot, (0, 0), w / 400.0) * np.array([1.0, 0.45, 0.25], np.float32) * HALATION * 10
    r2 = (xx * xx + (yy / aspect * aspect) ** 2) / (1 + aspect * aspect)
    x = x * (1 - VIGNETTE * np.clip(r2, 0, 1)[..., None] ** 1.2)

    enc = (np.log2(np.maximum(x, 1e-5)) - LG2_MIN) / LG2_SPAN
    y = apply_lut(enc)

    # Grade in display space: small hue split, cool shadows, faint warmth at the top.
    lum = (y * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(axis=2, keepdims=True)
    y = lum + (y - lum) * SATURATION
    y = y + (1 - lum) ** 2 * np.array([-0.010, 0.001, 0.008], np.float32) + lum ** 2 * np.array([0.006, 0.001, -0.007], np.float32)
    # A small S curve round the middle, then lens acutance to offset the denoiser, then a scan's lifted black.
    y = y + 0.42 * (y - 0.46) * (1 - np.abs(2 * y - 1))
    y = np.clip(y + 0.08 * (y - cv2.GaussianBlur(y, (0, 0), 1.2)), 0, 1)
    y = 0.008 + y * (1 - 0.008)

    # Grain: built at 1.3x so that clumps are softer than one pixel, stronger in the mids.
    rng = np.random.default_rng(seed)
    g = rng.normal(0, 1, (h, w, 3)).astype(np.float32)
    g = g * 0.45 + g[:, :, [1]] * 0.8
    g = cv2.GaussianBlur(g, (0, 0), 0.7) * 1.9
    weight = 0.45 + 0.9 * np.clip(y * (1 - y) * 4, 0, 1)
    return np.clip(y + g * GRAIN * weight, 0, 1)


def process(src, dst, seed=1, bits=16):
    img = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit("cannot read " + src)
    out = grade(img[:, :, :3][:, :, ::-1].astype(np.float32), seed)
    if bits == 16:
        cv2.imwrite(dst, (out[:, :, ::-1] * 65535 + 0.5).astype(np.uint16))
    else:
        cv2.imwrite(dst, (out[:, :, ::-1] * 255 + 0.5).astype(np.uint8))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    process(a.input, a.output, a.seed)
