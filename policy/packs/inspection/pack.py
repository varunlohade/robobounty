"""The inspection pack's interface: a four-legged ANYmal C walking a plant route, on Newton. Import this file and nothing else from the pack.

Four parts: model (model.py), controller (controller.py), judge (judge.py), world functions (world.py). sim.py is the run loop.
packs/README.md describes the contract. Simulated: the policy is upstream's and unchecked against a real robot.
"""
import pathlib

from .judge import judge
from .model import load_model
from .sim import NOTE as SIMULATED_NOTE
from .sim import load, replay, run
from .world import build, call, catalog, new_world, physics_hash, primitives, validate

NAME = "inspection"
ROBOT = "anymal_c"
BACKEND = "newton"


def controller_files():
    return [str(pathlib.Path(__file__).resolve().with_name("controller.py"))]
