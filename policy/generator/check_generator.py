"""Checks the gate and limits with no LLM: hostile MJCF is rejected before compile, and a valid scene runs and replays."""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gate as G
import harness as H
import prompt as P

GLASS = '<geom name="glass" type="box" size="30 0.05 80" pos="1.2 0.05 80"/>'


def wrap(body, asset=""):
    return f"<mujoco><asset>{asset}</asset><worldbody>{GLASS}{body}</worldbody></mujoco>"


def nested(depth):
    return "<body>" * depth + '<geom size="1"/>' + "</body>" * depth


BOMB = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        '<mujoco model="&c;"><worldbody>' + GLASS + "</worldbody></mujoco>")
HOSTILE = {
    "external_include": ("forbidden_element", wrap('<include file="/etc/passwd"/>')),
    "include_top_level": ("forbidden_element", f'<mujoco><include file="evil.xml"/><worldbody>{GLASS}</worldbody></mujoco>'),
    "entity_bomb": ("dtd_forbidden", BOMB),
    "external_entity": ("dtd_forbidden", '<!DOCTYPE m [<!ENTITY x SYSTEM "file:///etc/passwd">]><mujoco model="&x;"><worldbody>' + GLASS + "</worldbody></mujoco>"),
    "dtd_case_trick": ("dtd_forbidden", '<!doctype m><mujoco><worldbody>' + GLASS + "</worldbody></mujoco>"),
    "utf16_smuggle": ("not_utf8", BOMB.encode("utf-16")),
    "huge_geom_count": ("too_many_elements", wrap('<geom type="sphere" size="1"/>' * 5000)),
    "geoms_over_cap": ("too_many", wrap('<geom type="sphere" size="1"/>' * (G.MAX_GEOMS + 1))),
    "solid_over_cap": ("too_many", wrap('<geom type="sphere" size="1" conaffinity="1"/>' * (G.MAX_SOLID_GEOMS + 1))),
    "huge_file": ("file_too_large", wrap("<!-- " + "x" * (G.MAX_BYTES + 1) + " -->")),
    "timestep_zero": ("forbidden_element", f'<mujoco><option timestep="0"/><worldbody>{GLASS}</worldbody></mujoco>'),
    "nan_position": ("bad_number", wrap('<geom type="sphere" size="1" pos="nan 0 0"/>')),
    "inf_size": ("bad_number", wrap('<geom type="sphere" size="inf"/>')),
    "overflow_number": ("bad_number", wrap('<geom type="sphere" size="1e999"/>')),
    "file_path_texture": ("file_reference", wrap("", '<texture name="t" type="2d" file="/Users/varun/.ssh/id_rsa"/>')),
    "traversal_skybox": ("file_reference", wrap("", '<texture type="skybox" fileup="../../secret.png"/>')),
    "nested_depth": ("too_deep", wrap(nested(200))),
    "very_deep_stack": ("too_deep", wrap(nested(15000))),
    "mesh": ("forbidden_element", wrap("", '<mesh name="m" file="a.stl"/>')),
    "mesh_geom": ("bad_enum", wrap('<geom type="mesh" size="1"/>')),
    "flexcomp": ("forbidden_element", wrap('<flexcomp name="f" type="grid" count="99 99 99" spacing="1 1 1"/>')),
    "replicate": ("forbidden_element", wrap('<replicate count="100000"><geom size="1"/></replicate>')),
    "plugin": ("forbidden_element", f'<mujoco><extension><plugin plugin="mujoco.elasticity.solid"/></extension><worldbody>{GLASS}</worldbody></mujoco>'),
    "custom": ("forbidden_element", f'<mujoco><custom><text name="a" data="b"/></custom><worldbody>{GLASS}</worldbody></mujoco>'),
    "script_value": ("bad_name", wrap('<geom name="javascript:alert(1)" type="sphere" size="1"/>')),
    "script_in_type": ("bad_enum", wrap('<geom type="$(curl evil)" size="1"/>')),
    "instruction": ("instruction_forbidden", '<?php system("id"); ?>' + wrap("")),
    "cdata": ("cdata_forbidden", wrap("<![CDATA[x]]>")),
    "text_payload": ("text_forbidden", wrap("rm -rf /")),
    "joint": ("forbidden_element", wrap('<body><freejoint/><geom type="sphere" size="1"/></body>')),
    "impostor_robot": ("reserved_name", wrap('<body name="robot"><geom type="sphere" size="1"/></body>')),
    "impostor_tether": ("reserved_name", wrap('<geom name="tether_x" type="sphere" size="1"/>')),
    "repeated_name": ("repeated_name", wrap('<geom name="a" type="sphere" size="1"/><geom name="a" type="sphere" size="1"/>')),
    "huge_texture": ("texture_too_large", wrap("", "".join(f'<texture name="t{i}" type="2d" builtin="flat" width="1024" height="1024"/>' for i in range(5)))),
    "texture_side": ("out_of_range", wrap("", '<texture name="t" type="2d" builtin="flat" width="99999" height="1"/>')),
    "class_attr": ("unknown_attribute", wrap('<geom class="roller" type="sphere" size="1"/>')),
    "solref_attr": ("unknown_attribute", wrap('<geom solref="-1 -1" type="sphere" size="1"/>')),
    "no_glass": ("glass_required", '<mujoco><worldbody><geom type="sphere" size="1"/></worldbody></mujoco>'),
    "glass_off_plane": ("glass_not_at_plane", '<mujoco><worldbody><geom name="glass" type="box" size="30 0.05 80" pos="1.2 0.5 80"/></worldbody></mujoco>'),
    "glass_rotated": ("glass_required", '<mujoco><worldbody><geom name="glass" type="box" size="30 0.05 80" pos="1.2 0.05 80" euler="10 0 0"/></worldbody></mujoco>'),
    "glass_small": ("glass_too_small", '<mujoco><worldbody><geom name="glass" type="box" size="0.5 0.05 0.5" pos="1.2 0.05 137"/></worldbody></mujoco>'),
    "not_xml": ("not_xml", "<mujoco><worldbody>"),
}
# These pass the static gate. The sandboxed worker must reject them after compile.
LATE = {
    "start_blocked": ("start_blocked", wrap('<geom name="block" type="box" size="1 0.1 1" pos="0.15 -0.1 138.33" conaffinity="1"/>')),
    "walled_in": ("no_reachable_surface", wrap('<geom name="w1" type="box" size="0.05 0.1 80" pos="0.7 -0.1 80" conaffinity="1"/>'
                                               '<geom name="w2" type="box" size="30 0.1 0.05" pos="1.2 -0.1 137.6" conaffinity="1"/>')),
    "stuck_in_solid": ("no_glass_left", wrap('<geom name="slab" type="box" size="30 5 80" pos="1.2 -5 80" conaffinity="1"/>')),
    "bad_size_compile": ("compile_failed", wrap('<geom name="f" type="capsule" size="0.1" fromto="1 1 1 1 1 1"/>')),
}
failures = []


def expect(name, ok, detail=""):
    print(("PASS" if ok else "FAIL"), name, detail)
    if not ok:
        failures.append(name)


def main():
    for name, (code, text) in HOSTILE.items():
        try:
            G.check(text)
            expect(f"hostile {name}", False, "accepted")
        except G.Reject as e:
            expect(f"hostile {name}", e.code == code, f"-> {e.code}: {e.plain}")
    expect("no compile during the static gate", "mujoco" not in sys.modules)

    expect("prompt numbers match nominal.json", _prompt_matches())
    root = HERE.parent / "runs" / "generator" / "check"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    for name, (code, text) in LATE.items():
        r = H.full_gate(text, root / name)
        expect(f"late {name}", (not r["ok"]) and r["code"] == code, f"-> {r['stage']} {r['code']}: {r['plain']}")
    # A real limit: the same valid scene with a wall limit too short to import MuJoCo.
    valid = (HERE / "fixtures" / "valid_scene.xml").read_text()
    tight = {**H.CHECK, "wall_s": 0.1}
    r = H.full_gate(valid, root / "tight", tight)
    expect("wall limit kills the worker", r["code"] == "limit_wall_time", r["code"])
    code, why = H.run_worker(["probe", os.path.expanduser("~/.zshrc")], root / "probe", H.CHECK)
    got = json.loads((root / "probe" / "report.json").read_text())["probe"] if code == 0 else f"exit {code}"
    expect("sandbox blocks a home file", got == "denied", str(got))

    r = H.full_gate(valid, root / "valid")
    expect("valid scene passes every check", r["ok"], f"{r['stage']} {r['code']} share={r.get('reachable_share')} drift={r.get('settle_drift_m')} ke={r.get('peak_kinetic_j')}")
    if r["ok"] and "--no-trial" not in sys.argv:
        t = H.run_trial(root / "valid" / "canonical.xml", 1000, root / "valid_trial")
        print(json.dumps(t))
        expect("valid scene runs a trial", t["status"] == "ran")
        expect("the trial replays with a match", t.get("replay_match") is True)
        scene = root / "valid_trial" / "scene.xml"
        scene.write_text(scene.read_text().replace('pos="0.75 ', 'pos="0.80 '))
        H.run_worker(["replay", "."], root / "valid_trial", H.TRIAL)
        tampered = json.loads((root / "valid_trial" / "replay.json").read_text())["match"]
        expect("a changed scene fails the replay", tampered is False)
    shutil.rmtree(root / "tight", ignore_errors=True)
    print(f"{'ALL PASS' if not failures else 'FAILED: ' + ', '.join(failures)} ({len(HOSTILE)} hostile, {len(LATE)} late)")
    sys.exit(1 if failures else 0)


def _prompt_matches():
    w = json.loads((HERE.parent / "highrise" / "worlds" / "nominal.json").read_text())
    a = P.AREA
    top = 160.0 - w["drop_below_roof_m"]
    return abs(a["z1"] - top) < 1e-9 and abs(a["z0"] - (top - w["area_height_m"])) < 1e-9 and abs(a["x1"] - w["area_width_m"]) < 1e-9


if __name__ == "__main__":
    main()
