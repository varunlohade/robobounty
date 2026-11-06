"""Turns a generated GLB into physics data: generate_object.py process <glb> "<description>". The GLB is data. Nothing in it executes, and only geometry is read here.

Steps: file checks, trimesh load, triangle cap, finite bounds, repair, scale, CoACD convex hulls (at most 16), mass from volume and a density table.
The result is one JSON file per GLB sha in generated/. Worlds name a sha and a size, and read the hulls through load(). The reader part needs the standard library only.
Only `process` needs trimesh and coacd, and they live in policy/.venv-gen. Mass is a reasoned guess from a table, not a measurement. Generated objects stay fixed in both worlds, so physics does not read the mass.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "generated"
INDEX = CACHE / "index.json"
WEB = HERE.parent.parent / "public" / "generated"
SHA_RE = re.compile(r"[0-9a-f]{64}")
MAX_GLB_BYTES = 300 * 2**20
MAX_TRIANGLES = 3_000_000
PHYSICS_TRIANGLES = 40_000
MIN_PART_AREA = 0.002  # a loose part below this share of the surface is a crumb, and gets no collision shape
MAX_HULLS = 16
MAX_HULL_VERTICES = 64
MIN_HULL_VOLUME = 1e-7  # of a unit-sized object
MIN_SIZE_M, MAX_SIZE_M = 0.05, 12.0
STOP_WORDS = {"a", "an", "the", "of", "with", "on", "in", "and", "some", "add"}
# Bulk kg per cubic metre of the outer shell, by the first word found. Claude's reasoned guesses for mostly hollow things.
DENSITY = (("pump", 2500.0), ("motor", 3000.0), ("valve", 3500.0), ("gearbox", 3500.0), ("compressor", 1500.0), ("generator", 1200.0), ("anchor", 7000.0), ("chain", 4000.0), ("sandbag", 1500.0), ("concrete", 2300.0), ("barrier", 2300.0),
           ("cylinder", 900.0), ("drum", 300.0), ("barrel", 300.0), ("crate", 300.0), ("pallet", 250.0), ("toolbox", 500.0), ("cabinet", 400.0), ("panel", 400.0), ("unit", 350.0), ("chest", 1500.0), ("cone", 120.0), ("ladder", 200.0), ("bucket", 150.0))
DEFAULT_DENSITY = 800.0


class BadGlb(Exception):
    """A fixed code. No text from the file reaches it."""


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]


def density_of(description):
    found = set(words(description))
    return next((d for word, d in DENSITY if word in found), DEFAULT_DENSITY)


def _index():
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def library():
    """Every cached description, for the AI's function note."""
    return sorted(row["description"] for row in _index().values())


def find(description):
    """The cached entry for a description, or None. An exact match wins. Otherwise the shortest entry that holds all the words, and two equal candidates mean no match."""
    if not isinstance(description, str):
        return None
    index = _index()
    asked = words(description)
    if not asked:
        return None
    exact = index.get(" ".join(asked))
    if exact:
        return exact
    holding = sorted((row for key, row in index.items() if set(asked) <= set(key.split())), key=lambda r: len(words(r["description"])))
    if not holding or (len(holding) > 1 and len(words(holding[0]["description"])) == len(words(holding[1]["description"]))):
        return None
    return holding[0]


def load(sha):
    """The hull data of a sha. Raises BadGlb when it is not there or not sound, so a world cannot name a file."""
    if not isinstance(sha, str) or not SHA_RE.fullmatch(sha):
        raise BadGlb("bad_sha")
    path = CACHE / f"{sha}.json"
    if not path.exists():
        raise BadGlb("not_cached")
    data = json.loads(path.read_text())
    hulls = data["hulls"]
    if not 1 <= len(hulls) <= MAX_HULLS or any(not 4 <= len(h["v"]) <= MAX_HULL_VERTICES for h in hulls):
        raise BadGlb("bad_hulls")
    if not all(math.isfinite(c) for h in hulls for p in h["v"] for c in p):
        raise BadGlb("bad_hulls")
    return data


def size_of(asset, real_size_m):
    """The bounding box in metres. real_size_m is the longest side."""
    return [round(side * real_size_m, 6) for side in asset["unit_size"]]


def scaled_hulls(asset, real_size_m):
    """Vertices in metres, about the object's centre, z up."""
    return [[[c * real_size_m for c in p] for p in h["v"]] for h in asset["hulls"]]


def mass_kg(asset, real_size_m):
    return round(asset["unit_volume"] * real_size_m**3 * asset["density_kg_m3"], 2)


def _read_mesh(path):
    import numpy as np
    import trimesh

    raw = path.read_bytes()
    if len(raw) > MAX_GLB_BYTES:
        raise BadGlb("too_big")
    if raw[:4] != b"glTF":
        raise BadGlb("not_glb")
    try:
        mesh = trimesh.load(str(path), file_type="glb", force="mesh", process=False)
    except Exception:
        raise BadGlb("unreadable") from None
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise BadGlb("no_mesh")
    if len(mesh.faces) > MAX_TRIANGLES:
        raise BadGlb("too_many_triangles")
    if not np.isfinite(mesh.vertices).all():
        raise BadGlb("not_finite")
    return mesh, hashlib.sha256(raw).hexdigest()


def _repair(mesh):
    """Welded, crumbs gone, holes closed, faces outward, and few enough triangles for CoACD."""
    import numpy as np
    import trimesh

    mesh = trimesh.Trimesh(mesh.vertices, mesh.faces, process=True, validate=True)
    parts = mesh.split(only_watertight=False)
    if len(parts) > 1:
        total = sum(p.area for p in parts)
        parts = [p for p in parts if p.area >= MIN_PART_AREA * total]
        mesh = trimesh.util.concatenate(parts)
    if len(mesh.faces) > PHYSICS_TRIANGLES:
        mesh = mesh.simplify_quadric_decimation(face_count=PHYSICS_TRIANGLES)
    trimesh.repair.fill_holes(mesh)
    trimesh.repair.fix_normals(mesh)
    if not np.isfinite(mesh.vertices).all():
        raise BadGlb("not_finite")
    return mesh


def _hulls(mesh):
    import coacd
    import numpy as np
    import trimesh

    coacd.set_log_level("error")
    parts = coacd.run_coacd(coacd.Mesh(mesh.vertices, mesh.faces), threshold=0.04, max_convex_hull=MAX_HULLS, preprocess_mode="auto", decimate=True, max_ch_vertex=MAX_HULL_VERTICES, seed=0)
    out, volume = [], 0.0
    for verts, faces in parts:
        hull = trimesh.Trimesh(np.asarray(verts), np.asarray(faces), process=True).convex_hull
        if hull.volume < MIN_HULL_VOLUME or np.linalg.matrix_rank(hull.vertices - hull.vertices.mean(axis=0), tol=1e-6) < 3:
            continue
        volume += float(hull.volume)
        out.append({"v": np.round(hull.vertices, 5).tolist(), "f": hull.faces.tolist()})
    if not out:
        raise BadGlb("no_hulls")
    return out[:MAX_HULLS], volume


def process(glb, description, suggested_size_m=1.0, density=None, check=""):
    """Cached by the GLB's sha. Returns the entry and copies the GLB to public/generated/ for the browser and Blender."""
    import numpy as np

    path = Path(glb)
    mesh, sha = _read_mesh(path)
    out = CACHE / f"{sha}.json"
    if not out.exists():
        # The GLB is y up. Worlds are z up: (x, y, z) goes to (x, -z, y). The whole file's bounds set centre and scale, so the browser, which reads the same bounds, draws it in the same place.
        v = np.asarray(mesh.vertices, dtype=np.float64)
        low, high = v.min(axis=0), v.max(axis=0)
        longest = float((high - low).max())
        if not math.isfinite(longest) or longest <= 0.0:
            raise BadGlb("not_finite")
        centre = (low + high) / 2
        unit = (v - centre) / longest
        mesh.vertices = np.column_stack((unit[:, 0], -unit[:, 2], unit[:, 1]))
        triangles = len(mesh.faces)
        clean = _repair(mesh)
        hulls, volume = _hulls(clean)
        side = (high - low) / longest
        data = {"sha256": sha, "description": description, "triangles": triangles, "unit_size": [round(float(side[0]), 6), round(float(side[2]), 6), round(float(side[1]), 6)],
                "unit_volume": round(volume, 6), "density_kg_m3": density if density is not None else density_of(description), "suggested_size_m": suggested_size_m, "check": check, "density_note": "A reasoned guess from a table, not a measurement.", "hulls": hulls}
        CACHE.mkdir(exist_ok=True)
        tmp = out.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, separators=(",", ":")))
        tmp.replace(out)
    data = json.loads(out.read_text())
    WEB.mkdir(parents=True, exist_ok=True)
    if not (WEB / f"{sha}.glb").exists():
        shutil.copyfile(path, WEB / f"{sha}.glb")
    index = _index()
    index[" ".join(words(description))] = {"description": description, "sha256": sha, "hulls": len(data["hulls"]), "unit_size": data["unit_size"], "check": data.get("check", "")}
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    tmp.replace(INDEX)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["process"])
    ap.add_argument("glb")
    ap.add_argument("description")
    ap.add_argument("--size", type=float, default=1.0)
    ap.add_argument("--density", type=float)
    ap.add_argument("--check", default="")
    a = ap.parse_args()
    try:
        size = min(max(a.size, MIN_SIZE_M), MAX_SIZE_M)
        data = process(a.glb, a.description, size, a.density, a.check)
    except BadGlb as bad:
        print(json.dumps({"ok": False, "code": str(bad)}))
        sys.exit(1)
    print(json.dumps({"ok": True, "sha256": data["sha256"], "hulls": len(data["hulls"]), "triangles": data["triangles"], "unit_size": data["unit_size"], "unit_volume": data["unit_volume"]}))


if __name__ == "__main__":
    main()
