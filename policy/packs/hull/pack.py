"""The hull pack's interface: a magnetic crawler cleaning the flat bottom of a ship, on MuJoCo. Import this file and nothing else from the pack.

Four parts: model (model.py), controller (controller.py), judge (judge.py), world functions (world.py). sim.py is the run loop.
packs/README.md describes the contract. Simulated: every value is an assumption, see PARAMETERS.md. Nothing is checked against a real ship or robot.
"""
import pathlib

from .judge import judge
from .model import load_model
from .sim import NOTE as SIMULATED_NOTE
from .sim import load, replay, run
from .world import build, call, catalog, new_world, physics_hash, validate

NAME = "hull"
ROBOT = "hull_crawler"
BACKEND = "mujoco"


def controller_files():
    return [str(pathlib.Path(__file__).resolve().with_name("controller.py"))]
