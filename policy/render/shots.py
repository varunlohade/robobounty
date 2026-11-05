"""Art direction in one place: camera moves, sky gain, film opacity, haze. None of this touches physics."""
import numpy as np

HAZE = (0.46, 0.50, 0.51)
SKY_GAIN = 0.9
SKY_ROTATE_DEG = 40.0
GLASS_COAT = 0.30
FILM_OPACITY = 0.8

DECK_CENTER = (-120.0, -560.0, 80.0)
DECK_SCALE = (900.0, 520.0, 36.0)
DECK_NOISE = 3.2
DECK_DENSITY = 0.005

# Positions are offsets from the robot at the shot's start time, so a new run keeps the framing.
SHOTS = {
    # Wall on the right, receding left; open air and the city on the left.
    "side": {
        "t": 13.0, "seconds": 9.0, "still_t": 22.0,
        "pos": ((1.70, -1.22, 0.50), (1.53, -1.29, 0.55)),
        "target": ((-1.05, -0.26, 0.00), (-1.2, -0.29, 0.02)),
        "lens": (28.0, 28.0), "fstop": 1.7, "roll": 0.0,
    },
    # Above and out from the wall, looking down the facade: the wiped lane leads to the robot, then the drop.
    "drop": {
        "t": 22.0, "seconds": 10.0,
        "pos": ((0.95, -1.55, 2.35), (0.80, -1.60, 2.25)),
        "target": ((-1.05, 0.0, -2.9), (-1.05, 0.0, -2.9)),
        "lens": (24.0, 24.0), "fstop": 3.2, "roll": 0.0,
    },
}


def camera_at(shot, u, robot_start, robot_end):
    """Camera at u in 0..1 along the move. The rig glides at constant speed from the robot's start
    position to its end position, as a crane would. It reads the robot's pose and never writes it."""
    e = u * u * (3 - 2 * u)
    lerp = lambda pair: np.array(pair[0], float) * (1 - e) + np.array(pair[1], float) * e
    base = robot_start * (1 - u) + robot_end * u
    pos = base + lerp(shot["pos"])
    tgt = base + lerp(shot["target"])
    lens = shot["lens"][0] * (1 - e) + shot["lens"][1] * e
    # Focus sits on the wall at the robot's own position in this frame's rig plane.
    return {"pos": tuple(pos), "target": tuple(tgt), "lens": lens, "fstop": shot["fstop"],
            "focus": tuple(base), "roll": shot.get("roll", 0.0)}
