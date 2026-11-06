"""The default plant: one hall, one inspection route, and the worlds the check runs. Calls only: every part goes through the typed world functions.

Solid things on the walkway are in the physics. Everything in HALL is picture only, marked so by its function.
"""
ROUTE = {"waypoints": [{"x": 5.0, "y": 0.0}, {"x": 5.0, "y": 4.0}, {"x": 11.0, "y": 4.0}], "time_limit_s": 30.0}
WALKWAY = (
    ("add_grating", {"name": "floor_grating", "x": 5.0, "y": 1.0, "yaw_deg": 90.0, "length": 2.0, "width": 3.2}),
    ("add_ramp", {"name": "cable_ramp", "x": 7.0, "y": 4.0, "length": 1.5, "width": 3.2, "height": 0.15, "landing": 0.5}),
)
_W, _E, _S, _N = -5.0, 17.0, -10.0, 10.0
_WALKWAY_EDGES = (
    ((-3.0, -1.7), (6.7, -1.7)), ((6.7, -1.7), (6.7, 2.3)), ((6.7, 2.3), (14.0, 2.3)),
    ((-3.0, 1.7), (3.3, 1.7)), ((3.3, 1.7), (3.3, 5.7)), ((3.3, 5.7), (14.0, 5.7)),
)
HALL = (
    *(("add_wall", {"name": f"wall_{i}", "x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1], "height": 8.0}) for i, (a, b) in enumerate((((_W, _N), (_E, _N)), ((_E, _S), (_E, _N)), ((_W, _S), (_W, _N)), ((_W, _S), (_E, _S))))),
    *(("add_column", {"name": f"col_n{i}", "x": _W + 2.0 + i * 5.0, "y": _N - 0.35, "height": 8.0}) for i in range(5)),
    *(("add_column", {"name": f"col_e{i}", "x": _E - 0.35, "y": _S + 2.0 + i * 5.0, "height": 8.0}) for i in range(4)),
    *(("add_beam", {"name": f"beam_{i}", "x0": _W + 2.0 + i * 5.0, "y0": _S, "x1": _W + 2.0 + i * 5.0, "y1": _N, "height": 7.6}) for i in range(5)),
    *(("add_light", {"name": f"light_{i}", "x": x, "y": y, "height": 5.8}) for i, (x, y) in enumerate(((0.0, -2.0), (0.0, 5.0), (7.0, -2.0), (7.0, 5.0), (13.0, -2.0), (13.0, 5.0)))),
    *(("add_railing", {"name": f"rail_{i}", "x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1]}) for i, (a, b) in enumerate(_WALKWAY_EDGES)),
    *(("add_floor_line", {"name": f"line_{i}", "x0": a[0], "y0": a[1] + (0.15 if a[1] == b[1] and a[1] < 2 and i < 3 else -0.15 if a[1] == b[1] else 0.0), "x1": b[0], "y1": b[1] + (0.15 if a[1] == b[1] and a[1] < 2 and i < 3 else -0.15 if a[1] == b[1] else 0.0)}) for i, (a, b) in enumerate(_WALKWAY_EDGES)),
    ("add_tank", {"name": "vessel_a", "x": 8.5, "y": 7.6, "radius": 1.3, "height": 5.2}),
    ("add_tank", {"name": "vessel_b", "x": 12.2, "y": 7.6, "radius": 1.3, "height": 5.2}),
    ("add_tank", {"name": "vessel_c", "x": 0.5, "y": 6.8, "radius": 1.0, "height": 4.2}),
    ("add_pipe_rack", {"name": "rack_south", "x0": _W, "y0": -2.6, "x1": _E, "y1": -2.6, "height": 4.2}),
    ("add_pipe_rack", {"name": "rack_north", "x0": _W, "y0": 8.6, "x1": _E, "y1": 8.6, "height": 5.6}),
    ("add_pump", {"name": "pump_a", "x": 9.0, "y": 0.6}),
    ("add_pump", {"name": "pump_b", "x": 12.4, "y": 0.6}),
    ("add_gauge", {"name": "gauge_a", "x": 7.1, "y": -1.2}),
    ("add_gauge", {"name": "gauge_b", "x": 3.0, "y": 4.2}),
    ("add_gauge", {"name": "gauge_c", "x": 11.0, "y": 6.0}),
)
PLANT = (("set_route", ROUTE), *WALKWAY, *HALL)
LOW_PIPE = {"name": "low_pipe", "x": 2.5, "y": 0.0, "length": 3.2, "radius": 0.07, "clearance": 0.04}
TRAY = {"name": "dropped_tray", "x": 2.5, "y": 0.0, "length": 2.8, "width": 0.35, "height": 0.08, "yaw_deg": 12.0}
VALVE = {"name": "valve", "x": 2.8, "y": 0.0, "size": 0.09}
LEAK = {"name": "leak", "x": 3.0, "y": 0.0, "sx": 2.4, "sy": 2.6, "friction": 0.05}
STEEP = {"name": "steep_crossover", "x": 1.5, "y": 0.0, "width": 3.2, "depth": 0.3, "rise": 0.2, "count": 3}
GENTLE = {"name": "low_crossover", "x": 1.5, "y": 0.0, "width": 3.2, "depth": 0.35, "rise": 0.05, "count": 2}
CABINET = {"name": "cabinet", "x": 13.0, "y": -1.6, "sx": 0.6, "sy": 0.4, "sz": 1.9}
WORLDS = {
    "plant": PLANT,
    "low_pipe": (*PLANT, ("add_pipe", LOW_PIPE)),
    "dropped_tray": (*PLANT, ("add_cable_tray", TRAY)),
    "valve": (*PLANT, ("add_valve", VALVE)),
    "leak_walkway": (*PLANT, ("add_wet_patch", LEAK)),
    "leak_corner": (*PLANT, ("add_wet_patch", {**LEAK, "name": "leak_corner", "x": 5.0, "y": -0.3, "sx": 3.0})),
    "wet_floor": (*PLANT, ("set_floor", {"friction": 0.05})),
    "steep_crossover": (*PLANT, ("add_steps", STEEP)),
    "low_crossover": (*PLANT, ("add_steps", GENTLE)),
    "clear_cabinet": (*PLANT, ("add_box", CABINET)),
    "conduit_4cm": (*PLANT, ("add_pipe", {**LOW_PIPE, "name": "conduit", "radius": 0.02, "clearance": 0.0})),
    "payload_10kg": (*PLANT, ("set_payload", {"mass_kg": 10.0})),
    "payload_35kg": (*PLANT, ("set_payload", {"mass_kg": 35.0})),
    "gravity_3_71": (*PLANT, ("set_gravity", {"g": 3.71})),
}
