"""Facts the sim reads from a validated v5 world: raised solids, vents, patches, the cradle and the glass left to clean.

It uses world5.effect_of, the same rule compile5 uses, so an object is in these lists only if it is a physics
object in physics_xml. Rotated and round solids use their world-axis bounding box here. MuJoCo contact uses the true shape.
"""
import math

import numpy as np

import world5 as W

DIRT_CELL_M = 0.05


def _rect(world, obj):
    x, _, z = W.object_center(world, obj)
    ex, _, ez = W.half_extents(obj)
    return x - ex, x + ex, z - ez, z + ez


def rects(world):
    """Raised solids as (x0, x1, z0, z1, outer face off the glass, inner face off the glass). The moving cradle is not here."""
    out = []
    for o in world["objects"]:
        if o["solid"] and o["kind"] != "cradle" and W.effect_of(o) == "physics":
            out.append((*_rect(world, o), o["pos"]["out_m"] + W.half_extents(o)[1], W.gap_m(o)))
    return out


def regions(world, kind, value):
    """Objects of one kind as (x0, x1, z0, z1, value of one prop)."""
    return [(*_rect(world, o), o["props"][value]) for o in world["objects"] if o["kind"] == kind]


def cradle(world):
    return next((o for o in world["objects"] if o["kind"] == "cradle"), None)


def cradle_z(obj, top, t):
    return top - obj["pos"]["below_top_m"] + obj["props"]["travel_m"] / 2 * math.sin(2 * math.pi * t / obj["props"]["period_s"])


def cap_half_width(world):
    R, h = W.MULLION_ROUND_R, max(world["panes"]["joint_depth_m"], W.MULLION_MIN_H)
    return math.sqrt(max(0.0, R * R - (R - h) ** 2))


def dirt_grid(world):
    a = W.area_rect(world)
    nx = max(1, round((a["x1"] - a["x0"]) / DIRT_CELL_M))
    nz = max(1, round((a["z1"] - a["z0"]) / DIRT_CELL_M))
    return nx, nz, a["x0"] + (np.arange(nx) + 0.5) * DIRT_CELL_M, a["z0"] + (np.arange(nz) + 0.5) * DIRT_CELL_M


def clean_mask(world):
    """The dirt cells that count towards coverage: on the glass, and not under a joint cap or a solid."""
    nx, nz, cx, cz = dirt_grid(world)
    mask = np.ones((nz, nx), bool)
    half = cap_half_width(world) + DIRT_CELL_M / 2
    for x in W.mullion_xs(world):
        mask[:, np.abs(cx - x) < half] = False
    for z in W.transom_zs(world):
        mask[np.abs(cz - z) < half, :] = False
    g = W.glass_rect(world)
    mask[:, (cx < g["x0"]) | (cx > g["x1"])] = False
    mask[(cz < g["z0"]) | (cz > g["z1"]), :] = False
    for x0, x1, z0, z1, _, _ in rects(world):
        mask[np.ix_((cz > z0) & (cz < z1), (cx > x0) & (cx < x1))] = False
    return mask
