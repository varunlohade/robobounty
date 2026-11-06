"""Static gate for LLM-written scene MJCF. Runs before any compile and never imports MuJoCo.

check(text) returns canonical XML rebuilt from the checked tree, so nothing the gate did not read reaches MuJoCo.
Every Reject carries a fixed plain reason. A name from the file appears in a reason only if it fits SAFE_TOKEN.
"""
import math
import re
from xml.parsers import expat
from xml.sax.saxutils import quoteattr

MAX_BYTES = 256 * 1024
MAX_ELEMENTS = 900
MAX_DEPTH = 7  # mujoco > worldbody > body x4 > geom
MAX_GEOMS = 600
MAX_SOLID_GEOMS = 300
MAX_BODIES = 64
MAX_LIGHTS = 8
MAX_CAMERAS = 8
MAX_MATERIALS = 64
MAX_TEXTURES = 8
MAX_TEXTURE_SIDE = 1024
MAX_TEXTURE_PIXELS = 4_000_000
MAX_POS_M = 2000.0
MAX_SIZE_M = 500.0

# The glass face must cover the assigned area with this much to spare. See prompt.py for the frame.
GLASS_COVER = {"x0": -0.5, "x1": 2.9, "z0": 134.7, "z1": 138.7}
GLASS_FLAT_TOLERANCE_M = 1e-4

FORBIDDEN = {"include", "plugin", "extension", "custom", "mesh", "hfield", "skin", "flexcomp", "flex", "composite", "replicate",
             "frame", "attach", "model", "site", "joint", "freejoint", "inertial", "option", "compiler", "size", "default",
             "visual", "statistic", "tendon", "actuator", "sensor", "equality", "contact", "keyframe", "deformable"}
SAFE_TOKEN = re.compile(r"[a-z][a-z_]{0,23}\Z")
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,47}\Z")
NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d{1,3})?\Z")
RESERVED_NAME = re.compile(r"(robot|chassis|roller|drive|tether|anchor|base_)")
RESERVED_BY_TAG = {"material": {"alu", "cream", "burgundy", "rubber"}}


class Reject(Exception):
    def __init__(self, code, plain):
        super().__init__(code)
        self.code, self.plain = code, plain


def _token(s):
    return s if SAFE_TOKEN.match(s) else "another name"


def _nums(value, what):
    parts = value.split()
    for p in parts:
        if not NUMBER.match(p):
            raise Reject("bad_number", f"{what} must hold plain finite numbers: no NaN, no infinity, no text.")
    out = [float(p) for p in parts]
    if not all(math.isfinite(v) for v in out):
        raise Reject("bad_number", f"{what} must hold plain finite numbers: no NaN, no infinity, no text.")
    return out


def vec(lengths, lo, hi):
    def check(value, what):
        v = _nums(value, what)
        if len(v) not in lengths:
            raise Reject("bad_vector", f"{what} needs {' or '.join(map(str, lengths))} numbers.")
        if any(x < lo or x > hi for x in v):
            raise Reject("out_of_range", f"{what} must stay between {lo} and {hi}.")
        return value
    return check


def enum(*allowed):
    def check(value, what):
        if value not in allowed:
            raise Reject("bad_enum", f"{what} must be one of: {', '.join(allowed)}.")
        return value
    return check


def name(value, what):
    if not NAME.match(value):
        raise Reject("bad_name", f"{what} must be a plain name of letters, digits and underscores, starting with a letter, at most 48 characters.")
    return value


POS = vec((3,), -MAX_POS_M, MAX_POS_M)
QUAT = vec((4,), -1.0, 1.0)
EULER = vec((3,), -360.0, 360.0)
RGB = vec((3,), 0.0, 1.0)
RGBA = vec((4,), 0.0, 1.0)
UNIT = vec((1,), 0.0, 1.0)
BOOL = enum("true", "false")

ATTRS = {
    "mujoco": {"model": name},
    "asset": {},
    "worldbody": {},
    "texture": {"name": name, "type": enum("2d", "skybox"), "builtin": enum("gradient", "checker", "flat"), "rgb1": RGB, "rgb2": RGB,
                "mark": enum("none", "edge", "cross", "random"), "markrgb": RGB, "random": UNIT,
                "width": vec((1,), 1, MAX_TEXTURE_SIDE), "height": vec((1,), 1, MAX_TEXTURE_SIDE)},
    "material": {"name": name, "rgba": RGBA, "specular": UNIT, "shininess": UNIT, "reflectance": UNIT, "emission": vec((1,), 0.0, 2.0),
                 "texture": name, "texrepeat": vec((2,), 0.01, 1000.0), "texuniform": BOOL},
    "body": {"name": name, "pos": POS, "quat": QUAT, "euler": EULER},
    "geom": {"name": name, "type": enum("box", "sphere", "capsule", "cylinder", "ellipsoid", "plane"), "size": vec((1, 2, 3), 0.0, MAX_SIZE_M),
             "pos": POS, "quat": QUAT, "euler": EULER, "fromto": vec((6,), -MAX_POS_M, MAX_POS_M), "rgba": RGBA, "material": name,
             "contype": enum("0", "1"), "conaffinity": enum("0", "1"), "friction": vec((1, 2, 3), 0.0, 2.0), "group": enum("0", "1", "2")},
    "light": {"name": name, "pos": POS, "dir": vec((3,), -1.0, 1.0), "directional": BOOL, "castshadow": BOOL, "active": BOOL, "diffuse": RGB,
              "ambient": RGB, "specular": RGB, "cutoff": vec((1,), 0.0, 90.0), "exponent": vec((1,), 0.0, 128.0)},
    "camera": {"name": name, "pos": POS, "quat": QUAT, "euler": EULER, "xyaxes": vec((6,), -1.0, 1.0), "fovy": vec((1,), 1.0, 170.0)},
}
CHILDREN = {
    "mujoco": {"asset", "worldbody"},
    "asset": {"texture", "material"},
    "worldbody": {"body", "geom", "light", "camera"},
    "body": {"body", "geom", "light", "camera"},
}
FILE_ATTRS = {"file", "fileright", "fileleft", "fileup", "filedown", "filefront", "fileback", "meshdir", "texturedir", "assetdir", "plugin"}
SIZE_LENGTHS = {"box": 3, "sphere": 1, "ellipsoid": 3, "plane": 3}


class Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs, [], parent

    def walk(self):
        stack = [self]
        while stack:
            n = stack.pop()
            yield n
            stack.extend(reversed(n.kids))


def _parse(text):
    """Strict streaming parse. No DTD, no entity, no instruction. It stops at the first cap, before it holds the rest."""
    if isinstance(text, bytes):
        if len(text) > MAX_BYTES:
            raise Reject("file_too_large", f"The file is over the {MAX_BYTES // 1024} KB limit.")
        try:
            text = text.decode("utf-8")
        except UnicodeDecodeError as e:
            raise Reject("not_utf8", "The file must be UTF-8 text.") from e
    if not isinstance(text, str):
        raise Reject("not_text", "The file must be UTF-8 text.")
    if len(text.encode("utf-8", "surrogatepass")) > MAX_BYTES:
        raise Reject("file_too_large", f"The file is over the {MAX_BYTES // 1024} KB limit.")
    if "\x00" in text:
        raise Reject("not_text", "The file must be UTF-8 text.")
    head = text.lstrip()
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper or "<!ELEMENT" in upper or "<!ATTLIST" in upper or "<!NOTATION" in upper:
        raise Reject("dtd_forbidden", "DTD and entity declarations are not allowed.")
    if "<![CDATA[" in upper:
        raise Reject("cdata_forbidden", "CDATA sections are not allowed.")
    if head.startswith("<?xml"):
        end = head.find("?>")
        if end < 0 or not re.fullmatch(r"""<\?xml\s+version=["']1\.0["'](\s+encoding=["']utf-8["'])?\s*\?>""", head[:end + 2], re.I):
            raise Reject("bad_declaration", "The XML declaration may only state version 1.0 and UTF-8.")
        head = head[end + 2:]
    if "<?" in head:
        raise Reject("instruction_forbidden", "Processing instructions are not allowed.")

    state = {"count": 0, "depth": 0, "root": None, "node": None}

    def start(tag, attrs):
        state["count"] += 1
        state["depth"] += 1
        if state["count"] > MAX_ELEMENTS:
            raise Reject("too_many_elements", f"The file has more than {MAX_ELEMENTS} elements.")
        if state["depth"] > MAX_DEPTH:
            raise Reject("too_deep", f"Elements nest deeper than {MAX_DEPTH} levels.")
        node = Node(tag, attrs, state["node"])
        if state["node"] is None:
            state["root"] = node
        else:
            state["node"].kids.append(node)
        state["node"] = node

    def end(_tag):
        state["depth"] -= 1
        state["node"] = state["node"].parent

    def chars(data):
        if data.strip():
            raise Reject("text_forbidden", "Elements may not hold text. Use attributes only.")

    def deny_dtd(*_a):
        raise Reject("dtd_forbidden", "DTD and entity declarations are not allowed.")

    p = expat.ParserCreate("utf-8")
    p.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    p.StartDoctypeDeclHandler = deny_dtd
    p.EntityDeclHandler = deny_dtd
    p.ExternalEntityRefHandler = deny_dtd
    p.UnparsedEntityDeclHandler = deny_dtd
    p.NotationDeclHandler = deny_dtd
    p.StartElementHandler = start
    p.EndElementHandler = end
    p.CharacterDataHandler = chars
    try:
        p.Parse(head.encode("utf-8", "strict"), True)
    except expat.ExpatError as e:
        raise Reject("not_xml", "The file is not well-formed XML.") from e
    except UnicodeEncodeError as e:
        raise Reject("not_text", "The file must be UTF-8 text.") from e
    if state["root"] is None:
        raise Reject("not_xml", "The file is not well-formed XML.")
    return state["root"]


def _check_node(node):
    tag = node.tag
    if tag in FORBIDDEN:
        raise Reject("forbidden_element", f"The element {tag} is not allowed.")
    if tag not in ATTRS:
        raise Reject("unknown_element", f"The element {_token(tag)} is not on the allowlist.")
    specs = ATTRS[tag]
    for key, value in node.attrs.items():
        if key.lower() in FILE_ATTRS:
            raise Reject("file_reference", f"The {tag} element may not refer to a file or plugin. Use builtin textures and primitive geoms.")
        if key not in specs:
            raise Reject("unknown_attribute", f"The attribute {_token(key)} is not allowed on {tag}.")
        specs[key](value, f"{tag} attribute {key}")
    for kid in node.kids:
        if kid.tag in ATTRS and kid.tag not in CHILDREN.get(tag, ()):
            raise Reject("misplaced_element", f"The element {kid.tag} may not sit inside {tag}.")


def _check_geom(g):
    a = g.attrs
    kind = a.get("type", "sphere")
    if "fromto" in a:
        if kind not in ("capsule", "cylinder", "box", "ellipsoid"):
            raise Reject("bad_geom", f"A {kind} geom may not use fromto.")
        if "size" not in a or ("pos" in a or "quat" in a or "euler" in a):
            raise Reject("bad_geom", "A fromto geom needs size, and may not also set pos, quat or euler.")
        return
    if "size" not in a:
        raise Reject("bad_geom", "Every geom needs a size.")
    size = [float(v) for v in a["size"].split()]
    want = SIZE_LENGTHS.get(kind, 2)
    if len(size) != want:
        raise Reject("bad_geom", f"A {kind} geom needs {want} size numbers.")
    if kind == "plane":
        if a.get("conaffinity") == "1" or a.get("contype") == "1":
            raise Reject("bad_geom", "A plane geom may only be visual. Use a box for anything solid.")
    elif any(v <= 0 for v in size):
        raise Reject("bad_geom", "Every geom size must be above zero.")
    if "quat" in a and all(float(v) == 0 for v in a["quat"].split()):
        raise Reject("bad_geom", "A quat may not be all zeros.")


def _check_glass(glass, worldbody):
    if len(glass) != 1:
        raise Reject("glass_required", 'The scene needs exactly one geom named "glass".')
    g = glass[0]
    if g.parent is not worldbody:
        raise Reject("glass_required", 'The geom "glass" must sit directly inside worldbody.')
    a = g.attrs
    if a.get("type") != "box" or "pos" not in a or "size" not in a or {"quat", "euler", "fromto"} & set(a):
        raise Reject("glass_required", 'The geom "glass" must be an unrotated box with pos and size.')
    px, py, pz = (float(v) for v in a["pos"].split())
    sx, sy, sz = (float(v) for v in a["size"].split())
    if abs(py - sy) > GLASS_FLAT_TOLERANCE_M:
        raise Reject("glass_not_at_plane", 'The front face of "glass" must lie on y = 0, so pos y must equal size y.')
    c = GLASS_COVER
    if px - sx > c["x0"] or px + sx < c["x1"] or pz - sz > c["z0"] or pz + sz < c["z1"]:
        raise Reject("glass_too_small", f'"glass" must cover x {c["x0"]} to {c["x1"]} and z {c["z0"]} to {c["z1"]}.')


def _serialise(node, out, indent=0):
    attrs = "".join(f" {k}={quoteattr(v)}" for k, v in node.attrs.items())
    pad = "  " * indent
    if node.kids:
        out.append(f"{pad}<{node.tag}{attrs}>")
        for k in node.kids:
            _serialise(k, out, indent + 1)
        out.append(f"{pad}</{node.tag}>")
    else:
        out.append(f"{pad}<{node.tag}{attrs}/>")


def check(text):
    """Returns canonical XML, or raises Reject."""
    root = _parse(text)
    if root.tag != "mujoco":
        raise Reject("bad_root", "The root element must be mujoco.")
    counts = {}
    names = {}
    nodes = list(root.walk())
    for n in nodes:
        _check_node(n)
        counts[n.tag] = counts.get(n.tag, 0) + 1
        nm = n.attrs.get("name")
        if nm is not None and n.tag != "mujoco":
            if RESERVED_NAME.match(nm) or nm in RESERVED_BY_TAG.get(n.tag, ()):
                raise Reject("reserved_name", f"A {n.tag} uses a name reserved for the robot or the base scene.")
            seen = names.setdefault(n.tag, set())
            if nm in seen:
                raise Reject("repeated_name", f"Two {n.tag} elements share one name.")
            seen.add(nm)
    if counts.get("asset", 0) > 1 or counts.get("worldbody", 0) != 1:
        raise Reject("bad_sections", "The file needs one worldbody and at most one asset section.")
    for tag, cap in (("geom", MAX_GEOMS), ("body", MAX_BODIES), ("light", MAX_LIGHTS), ("camera", MAX_CAMERAS),
                     ("material", MAX_MATERIALS), ("texture", MAX_TEXTURES)):
        if counts.get(tag, 0) > cap:
            raise Reject("too_many", f"The file has more than {cap} {tag} elements.")
    geoms = [n for n in nodes if n.tag == "geom"]
    if sum(1 for g in geoms if g.attrs.get("conaffinity") == "1") > MAX_SOLID_GEOMS:
        raise Reject("too_many", f"The file has more than {MAX_SOLID_GEOMS} solid geoms.")
    for g in geoms:
        _check_geom(g)
    pixels = 0
    for t in (n for n in nodes if n.tag == "texture"):
        if "builtin" not in t.attrs or "name" not in t.attrs and t.attrs.get("type") != "skybox":
            raise Reject("bad_texture", "A texture needs a name and a builtin kind.")
        w, h = float(t.attrs.get("width", 64)), float(t.attrs.get("height", 64))
        pixels += w * h * (6 if t.attrs.get("type") == "skybox" else 1)
    if pixels > MAX_TEXTURE_PIXELS:
        raise Reject("texture_too_large", f"Textures hold more than {MAX_TEXTURE_PIXELS} pixels in total.")
    textures = names.get("texture", set())
    materials = names.get("material", set())
    for n in nodes:
        if n.tag == "material" and "name" not in n.attrs:
            raise Reject("bad_material", "A material needs a name.")
        if n.tag == "material" and "texture" in n.attrs and n.attrs["texture"] not in textures:
            raise Reject("unknown_reference", "A material names a texture that the file does not define.")
        if n.tag == "geom" and "material" in n.attrs and n.attrs["material"] not in materials:
            raise Reject("unknown_reference", "A geom names a material that the file does not define.")
    worldbody = next(k for k in root.kids if k.tag == "worldbody")
    _check_glass([g for g in geoms if g.attrs.get("name") == "glass"], worldbody)
    out = []
    _serialise(root, out)
    return "\n".join(out) + "\n"
