"""Physics for one trial on a v5 world: MuJoCo plus the suction, wind, battery and dirt models around it. A copy of policy/highrise/sim.py.

MuJoCo handles rollers, friction, pads, joints and the tether. This file computes the forces it
cannot: adhesion from the impeller and skirt leak, wind, and tether line load.
Same world, seed and actions give the same states. Every number has a row in policy/highrise/PARAMETERS.md.
Differences from the old sim: the model comes from compile5, and every physics object goes through the same
solid, vent and patch code, so a solid near the glass affects leak, nose and dirt cells. The old world-level
ledge had no leak and a dirt mask half a cell wider. A solid whose inner face clears the lip gives no leak.
"""
import hashlib
import json
import math

import mujoco
import numpy as np

import compile5 as C
import scene5 as E
import world5 as W

CONTROL_HZ = 20
DT_CONTROL = 1.0 / CONTROL_HZ
SUBSTEPS_PER_SAMPLE = 5  # 2 ms physics, 10 ms per adhesion update and force sample
SAMPLES_PER_CONTROL = 5
DT_SAMPLE = DT_CONTROL / SAMPLES_PER_CONTROL

ACTION_FIELDS = ("left_speed", "right_speed", "suction", "tether_rate", "done", "reported_coverage")
ACTION_LIMITS = np.array([[-0.4, 0.4], [-0.4, 0.4], [0, 1], [-1, 1], [0, 1], [0, 1]], dtype=float)

REFERENCE_AIR_DENSITY = 1.225  # the fan curve is rated at this density
GRAVITY = 9.81

# Vacuum skirt and impeller.
SEALED_AREA_M2 = 0.30 * 0.30
PAD_Y = (-0.10, 0.0, 0.10)
PAD_REACH_M = 0.006  # pad springs compress this much when the body sits flat on the glass
SKIRT_COMPLIANCE_M = 0.010  # the skirt lip follows the glass up to this lift
LIP_CONFORM_M = 0.006  # the lip bridges a joint this high with no leak
CROSS_LEAK_SHAPE = 3.0  # leak at one skirt-joint crossing = shape * (height - conform)^2
JOINT_GROOVE_DEPTH_M = 0.005
SKIRT_HALF_M = 0.15
OFF_GLASS_GAP_M = 0.05  # open gap along skirt perimeter that has run past the glass edge
SKIRT_STIFFEN_BELOW_C = 0.0  # the skirt follows the glass less below this
SKIRT_STIFFEN_PER_C = 0.02
SKIRT_STIFFEN_FLOOR = 0.5
DUST_LEAK_M2_PER_GM2 = 2e-6
DUST_CAPTURE_FRACTION = 0.1  # share of swept dust that reaches the impeller
IMPELLER_CLOG_G = 200.0
ORIFICE_CD = 0.6
IMPELLER_FLOW_MAX_M3S = 0.03
IMPELLER_LAG_S = 0.4
CHAMBER_LAG_S = 0.05
IMPELLER_EFFICIENCY = 0.35
IMPELLER_LOSS_W = 25.0  # shaft loss at full speed, scales with speed cubed

# Battery.
BATTERY_AH = 6.0
BATTERY_V_FULL = 16.4
BATTERY_V_EMPTY = 12.4
BATTERY_R_OHM = 0.2  # at 25 C
BATTERY_R_B_K = 2000.0
BATTERY_CAPACITY_PER_K = 0.008
BATTERY_CAPACITY_FLOOR = 0.5
IMPELLER_V_FULL_SPEED = 14.0  # below this voltage the impeller cannot reach full speed
ELECTRONICS_W = 5.0
DRIVE_EFFICIENCY = 0.6

# Wind on the body and tether.
BODY_DRAG_CD = 1.2
AREA_BODY_FRONT = W.BODY_SIDE * W.BODY_SIDE
AREA_BODY_SIDE = W.BODY_SIDE * W.BODY_HEIGHT
OUTWARD_LOAD_COEF = 0.9  # outward load on the body from flow past it, on the total wind speed
TETHER_DIAMETER_M = 0.006
TETHER_CD = 1.2
TETHER_KG_PER_M = 0.03
TETHER_EA_N = 2.0e5
TETHER_SHARE_ON_ROBOT = 0.5
TURBULENCE_FRACTION = 0.18

TETHER_DAMPING_RATIO = 0.2
TETHER_MIN_M = 0.5
TETHER_MAX_M = 120.0
TETHER_ACCEL = 1.0

# Cleaning pads.
PAD_FRICTION = 0.25
PAD_FRICTION_SMOOTH_MS = 0.02

# Dirt.
DIRT_CELL_M = E.DIRT_CELL_M
PAD_HALF_WIDTH = 0.05
PAD_HALF_HEIGHT = 0.04
PAD_MIN_N = 2.0
CLEAN_RATE = 0.25  # dirt level removed per second per newton above the minimum, per pad
CLEAN_THRESHOLD = 0.10

# Sensors.
CURRENT_NOISE_A = 0.15
TENSION_NOISE_N = 2.0
ANEMOMETER_NOISE_MS = 0.3
IMU_HEADING_NOISE_RAD = 0.005
NOSE_NOISE_M = 0.001
NOSE_DROPOUT = 0.03  # share of nose-sensor readings lost on clear glass
NOSE_X = 0.24
NOSE_Y = 0.12
DUST_NOISE_PER_GM2 = 0.02
DUST_DROPOUT_PER_GM2 = 0.002
SLIP_FLOOR_MS = 0.02

# Numerical sanity. Past any of these the state is not physics, so the trial is thrown out.
SANE_INSIDE_GLASS_M = 0.02
SANE_SPEED_MS = 30.0
SANE_TENSION_N = 10000.0
SANE_TETHER_STRETCH_M = 0.5
PIVOT_TRACK_DIFF_MS = 0.04


def check_action(a):
    """Strict check. np.clip keeps NaN, so reject first and never clamp."""
    a = np.asarray(a, dtype=float)
    if a.shape != (len(ACTION_FIELDS),) or not np.all(np.isfinite(a)):
        return None
    if np.any(a < ACTION_LIMITS[:, 0]) or np.any(a > ACTION_LIMITS[:, 1]):
        return None
    return a


def versions():
    return {"mujoco": mujoco.__version__, "numpy": np.__version__}


def impeller_pressure(p_max, flow_max, area_m2, rho):
    """Steady pressure where the fan curve meets the leak: dP = Pm(1-(Q/Qm)^2), Q = Cd A sqrt(2 dP / rho)."""
    if p_max <= 0:
        return 0.0, 0.0
    k = 2 * ORIFICE_CD ** 2 * area_m2 ** 2 / rho
    dp = p_max / (1 + k * p_max / flow_max ** 2)
    return dp, ORIFICE_CD * area_m2 * math.sqrt(2 * dp / rho)


class Wind:
    """Steady wind, seeded turbulence and 1-cos gusts. Depends only on world, seed and time."""

    def __init__(self, world, seed):
        rng = np.random.default_rng([seed, 11])
        wind = world["wind"]
        self.steady = wind["steady_ms"]
        self.dir0 = math.radians(wind["dir_deg"])
        self.peak = wind["gust_ms"]
        self.duration = wind["gust_duration_s"]
        self.gusts = []
        for k in range(wind["gust_count"]):
            jitter = float(rng.uniform(-0.15, 0.15)) * wind["gust_period_s"]
            self.gusts.append(wind["gust_start_s"] + k * wind["gust_period_s"] + jitter)
        self.freq = rng.uniform(0.05, 0.5, 6)
        self.phase = rng.uniform(0, 2 * math.pi, 6)
        self.dir_phase = float(rng.uniform(0, 2 * math.pi))

    def speed_dir(self, t):
        base = self.steady
        for g0 in self.gusts:
            if g0 <= t <= g0 + self.duration:
                shape = 0.5 * (1 - math.cos(2 * math.pi * (t - g0) / self.duration))
                base = max(base, self.steady + max(0.0, self.peak - self.steady) * shape)
        turb = float(np.sum(np.sin(2 * math.pi * self.freq * t + self.phase))) / 2.45
        return max(0.0, base * (1 + TURBULENCE_FRACTION * turb)), self.dir0 + 0.15 * math.sin(0.13 * t + self.dir_phase)


class Sim:
    def __init__(self, world, seed):
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
            raise ValueError("seed must be an integer in [0, 2^31)")
        world = W.validate(world)
        self.world, self.seed = world, seed
        self.m = mujoco.MjModel.from_xml_string(C.compile(world)[0])
        self.d = mujoco.MjData(self.m)
        m = self.m
        nid = lambda t, n: mujoco.mj_name2id(m, t, n)
        self.robot = nid(mujoco.mjtObj.mjOBJ_BODY, "robot")
        self.tether_id = nid(mujoco.mjtObj.mjOBJ_TENDON, "tether")
        self.a_left = [nid(mujoco.mjtObj.mjOBJ_ACTUATOR, n) for n in ("drive_lf", "drive_lb")]
        self.a_right = [nid(mujoco.mjtObj.mjOBJ_ACTUATOR, n) for n in ("drive_rf", "drive_rb")]
        self.dof_left = [m.jnt_dofadr[nid(mujoco.mjtObj.mjOBJ_JOINT, n)] for n in ("drive_lf", "drive_lb")]
        self.dof_right = [m.jnt_dofadr[nid(mujoco.mjtObj.mjOBJ_JOINT, n)] for n in ("drive_rf", "drive_rb")]
        self.roller_geoms = {nid(mujoco.mjtObj.mjOBJ_GEOM, f"roller_{n}") for n in ("lf", "lb", "rf", "rb")}
        self.chassis = nid(mujoco.mjtObj.mjOBJ_GEOM, "chassis")
        self.glass = W.glass_rect(world)
        self.mullions = W.mullion_xs(world)
        self.transoms = W.transom_zs(world)
        self.joint_depth = world["panes"]["joint_depth_m"]
        self.height = max(self.joint_depth, W.MULLION_MIN_H)

        weather = world["weather"]
        robot = world["robot"]
        self.rho, _ = W.air(world)
        kelvin = weather["temperature_c"] + 273.15
        self.battery_r = BATTERY_R_OHM * math.exp(BATTERY_R_B_K * (1 / kelvin - 1 / 298.15))
        self.battery_ah = BATTERY_AH * min(1.0, max(BATTERY_CAPACITY_FLOOR, 1 + BATTERY_CAPACITY_PER_K * (kelvin - 298.15)))
        cold = weather["temperature_c"] - SKIRT_STIFFEN_BELOW_C
        stiff = min(1.0, max(SKIRT_STIFFEN_FLOOR, 1 + SKIRT_STIFFEN_PER_C * cold))
        self.skirt_compliance = SKIRT_COMPLIANCE_M * stiff
        self.lip_conform = LIP_CONFORM_M * stiff
        self.dust_leak_m2 = DUST_LEAK_M2_PER_GM2 * weather["dust_gm2"]
        self.dust_ingested_g = 0.0
        self.noise_scale = 1 + DUST_NOISE_PER_GM2 * weather["dust_gm2"]
        self.nose_dropout = min(1.0, NOSE_DROPOUT + DUST_DROPOUT_PER_GM2 * weather["dust_gm2"])
        self.diverged = False
        self.diverged_reason = None

        self.t = 0.0
        self.wind = Wind(world, seed)
        self.wind_now = (0.0, 0.0)
        self.tether_len = float(m.tendon_range[self.tether_id, 1])
        self.tether_rate = 0.0
        self.speed_cmd = 0.0
        self.impeller = 0.0
        self.dp = 0.0
        self.flow = 0.0
        self.leak_m2 = robot["seal_leak_mm2"] * 1e-6
        self.cross_leak_m2 = 0.0
        self.soc = robot["battery_start_frac"]
        self.volts = self._ocv()
        self.amps = 0.0
        self.fan_amps = 0.0
        self.base_force = np.zeros(3)
        self.sensor_rng = np.random.default_rng([seed, 23])
        self._init_dirt(world, seed)
        self._init_elements(world)

        self.tension = 0.0
        self.tension_tick = 0.0
        self.impact_tick = 0.0
        self.pad_forces = np.zeros(3)
        self.pad_xz = [(0.0, 0.0)] * 3
        self.rollers_on_glass = 0
        self.gap_center = 0.0
        self.slip_rate = 0.0
        self.encoder_left = 0.0
        self.encoder_right = 0.0

        # Seal the robot on the glass at full speed before the first tick, so it does not start falling.
        self.impeller = 1.0
        self.speed_cmd = 1.0
        mujoco.mj_forward(m, self.d)
        self._set_tether_stiffness()
        self._update_adhesion(settle=True)
        self.model_sha = self._model_sha()
        self.start_sha = self.state_sha()

    def _init_dirt(self, world, seed):
        self.area = W.area_rect(world)
        nx, nz, _, _ = E.dirt_grid(world)
        self.nx, self.nz = nx, nz
        rng = np.random.default_rng([seed, 37])
        coarse = rng.uniform(0.6, 1.4, (nz // 8 + 2, nx // 8 + 2))
        zi = np.linspace(0, coarse.shape[0] - 1.001, nz)
        xi = np.linspace(0, coarse.shape[1] - 1.001, nx)
        z0, x0 = zi.astype(int), xi.astype(int)
        fz, fx = (zi - z0)[:, None], (xi - x0)[None, :]
        patch = (coarse[z0][:, x0] * (1 - fz) * (1 - fx) + coarse[z0 + 1][:, x0] * fz * (1 - fx)
                 + coarse[z0][:, x0 + 1] * (1 - fz) * fx + coarse[z0 + 1][:, x0 + 1] * fz * fx)
        self.dirt = patch * world["area"]["dirt_level"]
        self.dirt_mask = E.clean_mask(world)

    def _init_elements(self, world):
        self.el_rects = E.rects(world)
        self.el_vents = E.regions(world, "vent", "open_frac")
        base = W.friction(world)
        self.el_patches = []
        for x0, x1, z0, z1, wet in E.regions(world, "wet_patch", "wetness"):
            weather = {**world["weather"], "wetness": max(wet, W.effective_wetness(world))}
            self.el_patches.append((x0, x1, z0, z1, W.friction({**world, "weather": weather})))
        for x0, x1, z0, z1, level in E.regions(world, "dirt_patch", "level"):
            self.el_patches.append((x0, x1, z0, z1, base + (W.MU_DUST - base) * min(1.0, level)))
        self.el_base_mu = base
        self.el_roller_ids = sorted(self.roller_geoms)
        self.el_cradle = None
        cradle = E.cradle(world)
        if cradle is not None:
            body = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_BODY, "cradle")
            self.el_cradle = (cradle, self.m.body_mocapid[body])
        _, _, cx, cz = E.dirt_grid(world)
        for x0, x1, z0, z1, level in E.regions(world, "dirt_patch", "level"):
            self.dirt[np.ix_((cz > z0) & (cz < z1), (cx > x0) & (cx < x1))] += level
        if not self.dirt_mask.any():
            raise W.WorldError("elements leave no glass to clean")
        self._update_elements()

    def _update_elements(self):
        """Moves the cradle and sets each roller's friction from the patch under it. The last matching patch wins."""
        d, m = self.d, self.m
        if self.el_cradle is not None:
            e, mocap = self.el_cradle
            d.mocap_pos[mocap, 2] = E.cradle_z(e, self.area["z1"], self.t)
        if self.el_patches:
            for g in self.el_roller_ids:
                x, _, z = d.geom_xpos[g]
                mu = self.el_base_mu
                for x0, x1, z0, z1, value in self.el_patches:
                    if x0 <= x <= x1 and z0 <= z <= z1:
                        mu = value
                m.geom_friction[g, 0] = mu

    def _element_leak(self, x, z, reach):
        """Raised elements under the skirt lip leak like a joint. An open vent under the skirt leaks through its open share."""
        leak = 0.0
        # The skirt sits inside the chassis, so a solid that stops the chassis does not foul the lip.
        reach = reach * SKIRT_HALF_M / (W.BODY_SIDE / 2)
        for x0, x1, z0, z1, h, gap in self.el_rects:
            if gap < W.RIDE_CLEARANCE and x0 < x + reach and x1 > x - reach and z0 < z + reach and z1 > z - reach:
                step = max(0.0, min(h, W.RIDE_CLEARANCE) - self.lip_conform)
                leak += 2 * CROSS_LEAK_SHAPE * step * step
        for x0, x1, z0, z1, share in self.el_vents:
            over_x = min(x1, x + reach) - max(x0, x - reach)
            over_z = min(z1, z + reach) - max(z0, z - reach)
            if over_x > 0 and over_z > 0:
                leak += over_x * over_z * share
        return leak

    def _cap_half_width(self):
        return E.cap_half_width(self.world)

    def _ocv(self):
        return BATTERY_V_EMPTY + (BATTERY_V_FULL - BATTERY_V_EMPTY) * self.soc

    def _model_sha(self):
        m = self.m
        h = hashlib.sha256()
        for arr in (m.body_mass, m.geom_size, m.geom_pos, m.geom_friction, m.geom_solref, m.tendon_solref_lim,
                    m.actuator_gainprm, m.opt.gravity):
            h.update(np.asarray(arr).tobytes())
        return h.hexdigest()

    def state_sha(self):
        d = self.d
        h = hashlib.sha256()
        for arr in (d.qpos, d.qvel, d.act, self.dirt):
            h.update(arr.tobytes())
        if self.m.nmocap:
            h.update(d.mocap_pos.tobytes())
        h.update(np.array([self.t, self.tether_len, self.dp, self.impeller, self.soc]).tobytes())
        return h.hexdigest()

    def coverage(self):
        return float(np.mean(self.dirt[self.dirt_mask] <= CLEAN_THRESHOLD))

    def body_xz(self):
        p = self.d.xpos[self.robot]
        return float(p[0]), float(p[2])

    def heading(self):
        """Heading of the body x axis in the facade plane, measured from +x towards +z."""
        r = self.d.xmat[self.robot]
        return math.atan2(r[6], r[0])

    def _corner_gaps(self):
        """Distance from the four skirt corners to the glass plane, from the body pose."""
        p = self.d.xpos[self.robot]
        r = self.d.xmat[self.robot]
        h = W.BODY_SIDE / 2
        ax, ay = r[3] * h, r[4] * h
        c = -p[1]
        return c + ax + ay, c + ax - ay, c - ax - ay, c - ax + ay

    def _off_glass_length(self):
        """Skirt perimeter past the glass edge. Over open air the skirt has nothing to seal on."""
        x, z = self.body_xz()
        h = W.BODY_SIDE / 2
        g = self.glass
        over = max(0.0, x + h - g["x1"]) + max(0.0, g["x0"] - (x - h)) + max(0.0, z + h - g["z1"]) + max(0.0, g["z0"] - (z - h))
        return min(over, W.BODY_SIDE)

    def _crossing_leak(self):
        """Leak where the skirt lip crosses a raised joint or an open sealant gap."""
        x, z = self.body_xz()
        h = self.heading()
        reach = W.BODY_SIDE / 2 * (abs(math.cos(h)) + abs(math.sin(h)))
        n = sum(1 for m in self.mullions if abs(m - x) < reach) + sum(1 for t in self.transoms if abs(t - z) < reach)
        step = max(0.0, self.joint_depth - self.lip_conform)
        per_crossing = CROSS_LEAK_SHAPE * step * step + self.world["panes"]["joint_gap_m"] * JOINT_GROOVE_DEPTH_M
        return 2 * n * per_crossing + self._element_leak(x, z, reach)

    def _update_adhesion(self, settle=False):
        gaps = self._corner_gaps() if not settle else (0, 0, 0, 0)
        side = W.BODY_SIDE
        leak = self.world["robot"]["seal_leak_mm2"] * 1e-6 + self.cross_leak_m2 + self.dust_leak_m2
        for i in range(4):
            a = max(0.0, gaps[i] - self.skirt_compliance)
            b = max(0.0, gaps[(i + 1) % 4] - self.skirt_compliance)
            leak += side * (a + b) / 2
        leak += self._off_glass_length() * OFF_GLASS_GAP_M
        self.leak_m2 = leak
        s = self.impeller
        p_max = self.world["robot"]["suction_pa"] * s * s * self.rho / REFERENCE_AIR_DENSITY
        clog = max(0.05, 1 - self.dust_ingested_g / IMPELLER_CLOG_G)
        target, flow = impeller_pressure(p_max, IMPELLER_FLOW_MAX_M3S * clog * max(s, 1e-3), leak, self.rho)
        self.flow = flow
        if settle:
            self.dp = target
        else:
            self.dp += (target - self.dp) * min(1.0, DT_SAMPLE / CHAMBER_LAG_S)

    def _update_pads(self):
        """Three spring pads behind the tracks. Force falls to zero as the body lifts by the pad reach.

        Each pad pushes the body away from the glass and drags against its motion, with a smooth
        Coulomb law. Returns the world force and the torque about the centre of mass, where MuJoCo
        applies xfrc_applied.
        """
        d = self.d
        p = d.xpos[self.robot]
        com = d.xipos[self.robot]
        r = d.xmat[self.robot]
        per_pad = self.world["robot"]["pad_force_n"] / 3
        fx = fy = fz = tx = ty = tz = 0.0
        vx, vy, vz = d.qvel[0], d.qvel[1], d.qvel[2]
        wx, wy, wz = d.qvel[3], d.qvel[4], d.qvel[5]  # body frame
        wwx = r[0] * wx + r[1] * wy + r[2] * wz
        wwy = r[3] * wx + r[4] * wy + r[5] * wz
        wwz = r[6] * wx + r[7] * wy + r[8] * wz
        for i, ly in enumerate(PAD_Y):
            ox = r[0] * W.PAD_X + r[1] * ly
            oy = r[3] * W.PAD_X + r[4] * ly
            oz = r[6] * W.PAD_X + r[7] * ly
            gap = -(p[1] + oy)
            force = per_pad * min(1.0, max(0.0, 1.0 - gap / PAD_REACH_M))
            self.pad_forces[i] = force
            self.pad_xz[i] = (p[0] + ox, p[2] + oz)
            if force <= 0.0:
                continue
            # Velocity of the pad point in the facade plane.
            px = vx + wwy * oz - wwz * oy
            pz = vz + wwx * oy - wwy * ox
            speed = math.hypot(px, pz)
            mu = PAD_FRICTION * force / max(speed, PAD_FRICTION_SMOOTH_MS)
            f = (-mu * px, -force, -mu * pz)
            fx += f[0]
            fy += f[1]
            fz += f[2]
            cx, cy, cz = p[0] + ox - com[0], p[1] + oy - com[1], p[2] + oz - com[2]
            tx += cy * f[2] - cz * f[1]
            ty += cz * f[0] - cx * f[2]
            tz += cx * f[1] - cy * f[0]
        return fx, fy, fz, tx, ty, tz

    def _apply_wind_and_line(self):
        speed, direction = self.wind.speed_dir(self.t)
        self.wind_now = (speed, direction)
        d = self.d
        wx = speed * math.cos(direction)
        # Air cannot blow out of a solid wall: only the component into the wall stays.
        wy = max(0.0, speed * math.sin(direction))
        rx, ry = wx - d.qvel[0], wy - d.qvel[1]
        drag = 0.5 * self.rho * BODY_DRAG_CD
        fx = drag * AREA_BODY_SIDE * abs(rx) * rx
        fy = drag * AREA_BODY_FRONT * abs(ry) * ry - 0.5 * self.rho * OUTWARD_LOAD_COEF * AREA_BODY_FRONT * speed * speed
        line = 0.5 * self.rho * TETHER_CD * TETHER_DIAMETER_M * self.tether_len * TETHER_SHARE_ON_ROBOT
        fx += line * abs(wx) * wx
        fy += line * abs(wy) * wy
        fz = -TETHER_KG_PER_M * self.tether_len * TETHER_SHARE_ON_ROBOT * GRAVITY
        self.base_force[:] = (fx, fy, fz)

    def _update_power(self, suction_cmd):
        speed_cap = min(1.0, self.volts / IMPELLER_V_FULL_SPEED)
        self.speed_cmd = min(suction_cmd, speed_cap)
        self.impeller += (self.speed_cmd - self.impeller) * min(1.0, DT_CONTROL / IMPELLER_LAG_S)
        fan_w = IMPELLER_LOSS_W * self.impeller ** 3 + self.dp * self.flow / IMPELLER_EFFICIENCY
        drive_w = 0.0
        d = self.d
        for ids, dofs in ((self.a_left, self.dof_left), (self.a_right, self.dof_right)):
            for a, q in zip(ids, dofs):
                drive_w += abs(d.actuator_force[a] * d.qvel[q])
        drive_w /= DRIVE_EFFICIENCY
        total = fan_w + drive_w + ELECTRONICS_W
        ocv = self._ocv()
        # V = OCV - I R with I = P / V, the higher root. Past the power limit the voltage collapses to OCV/2.
        disc = ocv * ocv - 4 * self.battery_r * total
        self.volts = (ocv + math.sqrt(disc)) / 2 if disc > 0 else ocv / 2
        self.amps = total / self.volts
        self.fan_amps = fan_w / self.volts
        self.soc = max(0.0, self.soc - self.amps * DT_CONTROL / (self.battery_ah * 3600))

    def _apply_tether(self, rate_cmd):
        step = TETHER_ACCEL * DT_CONTROL
        self.tether_rate += float(np.clip(rate_cmd - self.tether_rate, -step, step))
        self.tether_len = float(np.clip(self.tether_len + self.tether_rate * DT_CONTROL, TETHER_MIN_M, TETHER_MAX_M))
        self.m.tendon_range[self.tether_id, 1] = self.tether_len
        self._set_tether_stiffness()

    def _set_tether_stiffness(self):
        """Line stiffness EA/L, so a long line is softer. MuJoCo direct stiffness is per unit of effective mass."""
        k = TETHER_EA_N / self.tether_len / W.BODY_MASS_KG
        self.m.tendon_solref_lim[self.tether_id] = (-k, -2 * TETHER_DAMPING_RATIO * math.sqrt(k))

    def _sample_forces(self):
        d = self.d
        nefc = d.nefc
        t = 0.0
        if nefc:
            rows = np.nonzero(d.efc_type[:nefc] == mujoco.mjtConstraint.mjCNSTR_LIMIT_TENDON)[0]
            for r in rows:
                t += float(d.efc_force[r])
        self.tension = t
        if t > self.tension_tick:
            self.tension_tick = t

    def _read_contacts(self):
        d = self.d
        on_glass = 0
        for k in range(d.ncon):
            c = d.contact[k]
            if c.efc_address < 0:
                continue
            f = float(d.efc_force[c.efc_address])
            g1, g2 = int(c.geom1), int(c.geom2)
            if g1 in self.roller_geoms or g2 in self.roller_geoms:
                if f > 0.5:
                    on_glass += 1
            if g1 == self.chassis or g2 == self.chassis:
                self.impact_tick = max(self.impact_tick, f)
        self.rollers_on_glass = on_glass

    def _clean(self):
        a = self.area
        for i in range(3):
            f = self.pad_forces[i]
            if f <= PAD_MIN_N:
                continue
            x, z = self.pad_xz[i]
            ix0 = max(int((x - PAD_HALF_WIDTH - a["x0"]) / DIRT_CELL_M), 0)
            ix1 = min(int((x + PAD_HALF_WIDTH - a["x0"]) / DIRT_CELL_M) + 1, self.nx)
            iz0 = max(int((z - PAD_HALF_HEIGHT - a["z0"]) / DIRT_CELL_M), 0)
            iz1 = min(int((z + PAD_HALF_HEIGHT - a["z0"]) / DIRT_CELL_M) + 1, self.nz)
            if ix0 >= ix1 or iz0 >= iz1:
                continue
            cells = self.dirt[iz0:iz1, ix0:ix1]
            cells -= CLEAN_RATE * (f - PAD_MIN_N) * DT_CONTROL
            cells[cells < 0] = 0.0

    def _check_sane(self):
        d = self.d
        reason = None
        if d.warning[mujoco.mjtWarning.mjWARN_BADQACC].number > 0:
            reason = "bad_qacc"
        elif self.center_on_glass() and d.xpos[self.robot][1] > SANE_INSIDE_GLASS_M:
            reason = "inside_glass"
        elif math.sqrt(d.qvel[0] ** 2 + d.qvel[1] ** 2 + d.qvel[2] ** 2) > SANE_SPEED_MS:
            reason = "speed"
        elif self.tension_tick > SANE_TENSION_N:
            reason = "tension_spike"
        elif d.ten_length[self.tether_id] - self.tether_len > SANE_TETHER_STRETCH_M:
            reason = "tether_stretch"
        if reason is not None and not self.diverged:
            self.diverged = True
            self.diverged_reason = reason

    def center_on_glass(self):
        x, z = self.body_xz()
        g = self.glass
        return g["x0"] <= x <= g["x1"] and g["z0"] <= z <= g["z1"]

    def _update_slip(self):
        """Body speed over the glass that the track encoders do not account for."""
        d = self.d
        h = self.heading()
        v_enc = (self.encoder_left + self.encoder_right) / 2
        ex = d.qvel[0] - v_enc * math.cos(h)
        ez = d.qvel[2] - v_enc * math.sin(h)
        self.slip_rate = math.hypot(ex, ez)

    def step(self, action):
        """One control tick. Returns False if the action fails the strict check."""
        a = check_action(action)
        if a is None:
            return False
        d = self.d
        r = W.ROLLER_RADIUS
        for i in self.a_left:
            d.ctrl[i] = a[0] / r
        for i in self.a_right:
            d.ctrl[i] = a[1] / r
        self._update_power(a[2])
        self._apply_tether(a[3])
        self._apply_wind_and_line()
        self.cross_leak_m2 = self._crossing_leak()
        self._update_elements()
        self.tension_tick = 0.0
        self.impact_tick = 0.0
        f = d.xfrc_applied[self.robot]
        for _ in range(SAMPLES_PER_CONTROL):
            self._update_adhesion()
            pad = self._update_pads()
            f[0] = self.base_force[0] + pad[0]
            f[1] = self.base_force[1] + self.dp * SEALED_AREA_M2 + pad[1]
            f[2] = self.base_force[2] + pad[2]
            f[3:6] = pad[3:6]
            mujoco.mj_step(self.m, d, nstep=SUBSTEPS_PER_SAMPLE)
            self._sample_forces()
        self._check_sane()
        self._read_contacts()
        self._clean()
        swept = math.hypot(d.qvel[0], d.qvel[2]) * W.BODY_SIDE * DT_CONTROL * self.world["weather"]["dust_gm2"]
        self.dust_ingested_g += DUST_CAPTURE_FRACTION * swept
        self.encoder_left = r * sum(d.qvel[q] for q in self.dof_left) / 2
        self.encoder_right = r * sum(d.qvel[q] for q in self.dof_right) / 2
        self._update_slip()
        self.gap_center = float(-d.xpos[self.robot][1])
        self.t = round(self.t + DT_CONTROL, 6)
        return True

    def _nose_reading(self, sx, sz):
        """Surface height under a downward range sensor, and whether it sees glass at all."""
        g = self.glass
        if not (g["x0"] <= sx <= g["x1"] and g["z0"] <= sz <= g["z1"]):
            return 0.0, True
        R, h = W.MULLION_ROUND_R, self.height
        best = 0.0
        half = self._cap_half_width()
        for m in self.mullions:
            dist = abs(sx - m)
            if dist < half:
                best = max(best, math.sqrt(R * R - dist * dist) - (R - h))
        for t in self.transoms:
            dist = abs(sz - t)
            if dist < half:
                best = max(best, math.sqrt(R * R - dist * dist) - (R - h))
        for x0, x1, z0, z1, top, _ in self.el_rects:
            if x0 <= sx <= x1 and z0 <= sz <= z1:
                best = max(best, top)
        return best, False

    def obs(self):
        """What the robot senses. It has no absolute position, no pressure gauge and no view of the dirt."""
        r = self.sensor_rng
        h = self.heading()
        x, z = self.body_xz()
        c, s = math.cos(h), math.sin(h)
        noses = []
        for side in (1, -1):
            # Body left of heading (c, s) is (-s, c) in x-z, as seen from outside.
            sx = x + NOSE_X * c - side * NOSE_Y * s
            sz = z + NOSE_X * s + side * NOSE_Y * c
            height, off = self._nose_reading(sx, sz)
            lost = r.uniform() < self.nose_dropout
            noses.append({"valid": not lost, "off_glass": off and not lost,
                          "height": 0.0 if lost else height + float(r.normal(0, NOSE_NOISE_M * self.noise_scale))})
        speed, direction = self.wind_now
        return {
            "t": self.t,
            "encoder_left": self.encoder_left,
            "encoder_right": self.encoder_right,
            "imu_heading": h + float(r.normal(0, IMU_HEADING_NOISE_RAD)),  # from gravity, on a vertical wall
            "fan_current": max(0.0, self.fan_amps + float(r.normal(0, CURRENT_NOISE_A * self.noise_scale))),
            "battery_volts": self.volts,
            "tether_length": self.tether_len,
            "tether_tension": max(0.0, self.tension + float(r.normal(0, TENSION_NOISE_N))),
            "roof_wind": max(0.0, speed + float(r.normal(0, ANEMOMETER_NOISE_MS))),
            "nose": noses,
        }


def digest(prev, i, action, state):
    payload = json.dumps([prev, i, action, state], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
