"""Turns a DA3 result npz into a depth video and a point cloud orbit video. Only uses the real model output.
Usage: depth_panes.py <npz> <out_stem>
"""
import subprocess, sys
import cv2
import numpy as np

W, H, FPS = 960, 540, 30
z = np.load(sys.argv[1]); stem = sys.argv[2]
depth, conf, ext, K, imgs = z["depth"], z["conf"], z["extrinsics"], z["intrinsics"], z["images"]
print("frames", depth.shape, "conf", float(conf.min()), float(conf.max()))

def writer(path):
    return subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                             "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)

lo, hi = np.percentile(depth, [2, 98])
w = writer(f"{stem}_depth.mp4")
for i in range(len(depth)):
    d = np.clip((depth[i] - lo) / (hi - lo), 0, 1)
    c = cv2.applyColorMap((255 * (1 - d)).astype(np.uint8), cv2.COLORMAP_TURBO)
    c = cv2.resize(c, (W, H), interpolation=cv2.INTER_LINEAR)
    for _ in range(FPS): w.stdin.write(c.tobytes())
w.stdin.close(); w.wait()

pts, cols = [], []
thr = np.percentile(conf, 30)
for i in range(len(depth)):
    h, wd = depth[i].shape
    u, v = np.meshgrid(np.arange(wd), np.arange(h))
    keep = conf[i] > thr
    xyz = np.linalg.inv(K[i]) @ np.stack([u[keep], v[keep], np.ones(keep.sum())]) * depth[i][keep]
    E = np.eye(4); E[:3] = ext[i][:3]
    world = np.linalg.inv(E) @ np.vstack([xyz, np.ones(xyz.shape[1])])
    pts.append(world[:3].T); cols.append(imgs[i][keep][:, ::-1])
pts, cols = np.vstack(pts), np.vstack(cols)
E0 = np.eye(4); E0[:3] = ext[len(ext) // 2][:3]
cam = (E0[:3, :3] @ pts.T).T + E0[:3, 3]
print("points", len(cam), "z percentiles", np.percentile(cam[:, 2], [2, 50, 98]).round(3))
keep = cam[:, 2] < np.percentile(cam[:, 2], 95)
cam, cols = cam[keep], cols[keep]
centre = np.array([0, 0, np.median(cam[:, 2])])
f = 0.9 * W
w = writer(f"{stem}_cloud.mp4")
N = 9 * FPS
for k in range(N):
    a = np.radians(28) * np.sin(2 * np.pi * k / N)
    c, s = np.cos(a), np.sin(a)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    p = (cam - centre) @ R.T + centre
    good = p[:, 2] > 1e-3
    q, cc = p[good], cols[good]
    x = (f * q[:, 0] / q[:, 2] + W / 2).astype(int); y = (f * q[:, 1] / q[:, 2] + H / 2).astype(int)
    ok = (x >= 0) & (x < W - 1) & (y >= 0) & (y < H - 1)
    x, y, zz, cc = x[ok], y[ok], q[:, 2][ok], cc[ok]
    order = np.argsort(-zz)
    img = np.full((H, W, 3), 18, np.uint8)
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        img[y[order] + dy, x[order] + dx] = cc[order]
    w.stdin.write(img.tobytes())
w.stdin.close(); w.wait()
