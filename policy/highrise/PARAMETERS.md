# High-rise window robot: parameters and simplifications

A simulated robot built for a hackathon, in the family of Ecovacs WINBOT and HOBOT, scaled up as a fictional product. No home model is sold for this job, as far as we found. **Nothing here is calibrated to a real robot.** "ASSUMPTION" means no source backs the value. Research notes: `docs/research/facade-robots.md`.

## Robot

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Body side | 0.36 | m | ASSUMPTION: scaled from WINBOT W2, 0.27 m per [digitec listing](https://www.digitec.ch/en/s1/product/ecovacs-w2-window-cleaners-42863683) |
| Body height | 0.08 | m | Same listing gives 77 mm for W2; kept close |
| Body mass | 4.0 | kg | ASSUMPTION: W2 is 1.5-1.6 kg per listings; scaled by area plus a larger battery. Changed from 5.0 so the nominal world has grip margin, see "Changes" |
| Ride clearance | 0.02 | m | ASSUMPTION: no source |
| Track roller radius, position | 0.035, x 0.12, y 0.15 | m | ASSUMPTION: four rollers stand in for two tracks |
| Drive torque limit per roller | 1.5 | N m | ASSUMPTION. Raised from 0.9, see "Changes" |
| Drive servo gain | 20 | N m s/rad | ASSUMPTION: stands in for a stiff geared drive |
| Cleaning pads | 3 pads, total `pad_force_n`, reach 6 mm, friction 0.25 | | ASSUMPTION: spring model, not contact |
| Sealed area | 0.09 | m2 | ASSUMPTION: 0.30 x 0.30 m. Research notes also label the W2 sealed area as an assumption |

## Suction

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Peak impeller pressure `suction_pa` | 2800 nominal | Pa | [W2 Pro retailer listing](https://www.inserv.lv/en/products/186584/window-cleaning-robot-with-2800-pa-suction-power-and-automatic-safety-system-white-ecovacs-winbot-w2-pro), a listing and not a lab test |
| Adhesion law | force = pressure difference x sealed area | | Physics. Falling below a pressure threshold is described in [this review](https://www.mdpi.com/2218-6581/5/3/14). Notes say to check this is the cited review |
| Fan curve | dP = Pm (1 - (Q/Qm)^2), Pm and Qm scale with speed | | Fan affinity form, curve shape ASSUMPTION |
| Maximum flow | 0.03 | m3/s | ASSUMPTION. Raised from 0.02, see "Changes". No W2 flow value found |
| Orifice leak law | Q = Cd A sqrt(2 dP / rho) | | Physics |
| Discharge coefficient Cd | 0.6 | | About 0.6 for a sharp edge, [orifice plate reference](https://www.wikipedia.org/wiki/Orifice_plate). A skirt gap is not a sharp plate, so this is an approximation |
| Baseline skirt leak `seal_leak_mm2` | 200 nominal | mm2 | ASSUMPTION |
| Skirt lift before leak | 0.010 | m | ASSUMPTION |
| Open gap past the glass edge | 0.05 | m | ASSUMPTION: along skirt perimeter that has left the glass |
| Lip bridges a joint up to | 0.006 | m | ASSUMPTION |
| Joint crossing leak | 2 crossings x (3 (h - lip)^2 + gap x 5 mm) | m2 | ASSUMPTION: geometric guess |
| Impeller lag, chamber lag | 0.4, 0.05 | s | ASSUMPTION |
| Impeller efficiency, shaft loss | 0.35, 25 | -, W | ASSUMPTION. The result is about 86 W at full speed, near the [96 W W2 listing](https://aio.lv/en/product--ecovacs-w2--10850355.md) |
| Pressure from motor current | invert the fan curve | | Method from [SUTD 2019 paper](https://repository.sutd.edu.sg/esploro/outputs/conferenceProceeding/Design-of-an-Adhesion-Aware-Façade-Cleaning/9912443509846), read in summary only. Our curve and numbers are ASSUMPTION |
| Current noise | 0.15 | A | ASSUMPTION |

## Friction

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Rubber on dry glass | 0.75 | | ASSUMPTION: no measured value found. [This study](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4904280/) measures rubber on dry and wet glass, but its values are in figures we did not read, and it shows dwell time matters |
| Rubber on wet glass | 0.30 | | ASSUMPTION: same. Research notes list wet glass friction as not found |
| `wetness` mix | linear between the two | | ASSUMPTION |
| Coulomb friction | MuJoCo elliptic cone, noslip 3 | | Numerical setting |

## Wind

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Force law | 0.5 rho Cd A v^2 | | Physics |
| Air density | per world, 1.221 at nominal | kg/m3 | Moist ideal gas mix at 101325 Pa, textbook. Height and pressure change not modelled |
| Body drag Cd | 1.2 | | ASSUMPTION: bluff body, wall effects not modelled |
| Outward load coefficient | 0.9 on 0.13 m2, on total wind speed | | ASSUMPTION: no source found. The one outward wind load. See note below |
| Wall-normal wind | clamped at 0 | | Physics: air cannot blow out of a solid wall. A `wind_dir_deg` pointing away from the wall keeps only its along-wall part |
| Tether drag | 1.2 on 6 mm line, half the load reaches the robot | | ASSUMPTION |
| Turbulence, gust shape | 18% sum of sines, 1-cos | | ASSUMPTION |
| Wind pause in the controller | 10, resume 7 | m/s | Unvalidated vendor blog figure in research notes, about 10 m/s. Not a validated limit |

Note on suction load: the wall's static pressure acts on the back of the robot and on the skirt reference alike, so it does not simply add to the load. We model only an outward load from flow around the body. The size is a guess.

## Temperature, humidity, dust

Field names: `temperature_c`, `humidity_pct`, `dust_gm2`. Each changes the physics in code. Airborne sand stays **not tested**: it has no model.

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Air density | (p - e) / (287.05 T) + e / (461.5 T) | kg/m3 | Ideal gas mix, textbook. Used in wind, line drag and leak flow |
| Saturation pressure | 610.94 exp(17.625 t / (t + 243.04)) | Pa | [Alduchov and Eskridge 1996](https://www.osti.gov/biblio/548871). Citation from SCENARIO-GAPS.md, coefficients not checked against the paper |
| Suction with density | suction_pa x rho / 1.225 | Pa | [Fan affinity laws](https://www.engineeringtoolbox.com/amp/fan-affinity-laws-d_196.html) |
| Battery resistance | R25 exp(2000 (1/T - 1/298.15)) | ohm | ASSUMPTION: form has [preprint support for LiFePO4](https://www.preprints.org/manuscript/202510.1447) only. B not measured |
| Battery capacity | Ah25 x clamp(1 + 0.008 (T - 298.15), 0.5, 1) | Ah | ASSUMPTION |
| Skirt stiffening | compliance and lip x clamp(1 + 0.02 t, 0.5, 1) below 0 C | | ASSUMPTION: no data found |
| Condensation | wetness = max(wetness, clamp((dew - glass) / 3, 0, 1)) | | ASSUMPTION: ramp |
| Glass below air | 3 | C | ASSUMPTION: fixed offset, no sun or night-sky model |
| Dust seal leak | 2 per g/m2 | mm2 | ASSUMPTION: linear, not measured |
| Dust friction | mu + (0.40 - mu)(1 - exp(-dust / 5)) | | ASSUMPTION: form and values |
| Impeller clogging | Qmax x (1 - m / 200 g), floor 5% | | ASSUMPTION |
| Dust reaching impeller | 10% of swept load over the body width | | ASSUMPTION |
| Dust sensor noise | noise x (1 + 0.02 dust), nose dropout + 0.002 per g/m2 | | ASSUMPTION |

## Tether

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Line weight | 0.03 | kg/m | ASSUMPTION |
| Line stiffness EA | 2e5 | N | ASSUMPTION: k = EA/L |
| Damping ratio | 0.2 | | ASSUMPTION |
| Load limit in judge | 1000 | N | ASSUMPTION. Applies only while on the glass, because physics ends at a detach |
| Sag and wave motion | none | | Simplification: straight massless constraint plus a lumped weight |

## Battery

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Capacity | 6 | Ah | ASSUMPTION: W2 is 2600 mAh per listing; scaled up |
| Open-circuit voltage | 12.4 to 16.4 | V | ASSUMPTION: linear with charge |
| Internal resistance | 0.2 | ohm | ASSUMPTION |
| Full-speed voltage | 14 | V | ASSUMPTION: below this the impeller slows |

## Dirt and judge

| Value | Number | Unit | Source or label |
|---|---|---|---|
| Clean rate | 0.25 per N per s | | ASSUMPTION |
| Cell, threshold | 0.05 m, 0.10 | | ASSUMPTION |
| Coverage required | 0.90 | | ASSUMPTION: chosen before the campaign |
| Slide limit, gap for detach | 0.30, 0.03 | m | ASSUMPTION |
| Time limit | 600 | s | ASSUMPTION |
| Hold at the time limit | stationary on glass at least 30 s, with no safety rule fired | s | ASSUMPTION |
| `wind_hold` | no 30 s calm spell below 7 m/s in the final hold | | ASSUMPTION: not a failure, not a pass |
| `battery_stop` | a calm spell, and half or more of the hold below 12.8 V | | ASSUMPTION: not a safety failure, not a pass |
| `stalled` | neither reason | | ASSUMPTION: a failure. Includes the controller stuck in phase None, `controller.py:213,264`, a real finding left in place |
| False done gap | reported minus true coverage above 0.10 | | ASSUMPTION: same as the 10% coverage tolerance, and chosen knowing nominal gaps reach 0.08. Sensitivity in each table |
| Sanity limits | 2 cm inside glass, 30 m/s, 10 kN, 0.5 m tether stretch, MuJoCo bad-acceleration warning | | Numerical limits: the trial is thrown out and counted separately |

## Sensors

Nose height noise 1 mm, 3% lost readings, heading from gravity 0.005 rad, tension 2 N, roof wind 0.3 m/s: all ASSUMPTION. The dropout echoes the [reported trouble](https://www.therobotreport.com/skyline-robotics-ozmo-automates-skyscraper-window-cleaning/) with sensing on glass, in a different robot.

## Simplifications

- Four spheres stand in for two rubber tracks. Track lugs and deformation are absent.
- Skirt, seal and flow are algebraic models around MuJoCo, updated at 100 Hz. No fluid simulation.
- Adhesion always acts along the glass normal, at the centre of mass.
- Joints are rounded caps. Real capped mullions stand far prouder, and this robot could not cross them. Flush glazing is the implied building.
- Glass stays one flat rectangle. Wind has no change with height. Wind on the wall is uniform.
- `sun_level` changes the picture only.
- Physics ends at a detach, or when the body centre leaves the glass. There is no model of the fall or the tether catch, so no number comes from them. The tether limit is checked only while the robot is on the glass.
- Adhesion, wind and line loads act at the centre of mass. Adhesion acts along a line through it, so it adds no moment.
- The world is deterministic given world, seed and actions. Replay across machines is unknown.

## Changes made after seeing results

The first group came from debugging the nominal world, before the first formal campaign.

- Body mass 5 to 4 kg, nominal pad force 40 to 25 N, nominal wetness 0.3 to 0.2: at the first values gravity used about 65% of track grip, and a 90 degree pivot slid about 0.25 m.
- Drive torque limit 0.9 to 1.5 N m: pivots stalled on one track.
- Maximum flow 0.02 to 0.03 m3/s: the operating point sat near the peak of the power curve, where the current estimate has no meaning.
- Nominal world: `mullion_offset_m` and `drop_below_roof_m` moved so no joint sits under a lane turn. A pivot on a joint slides further, which remains a real weakness in varied worlds.
- Controller constants `PIVOT_SAG_M_PER_RAD` and `LANE_OVERRUN_M` set from the nominal world.
- Airborne sand, rain, wind by height, salt, ice and snow have no physics here.
- Campaign `all` ranges narrowed (wetness to 0.6, joint depth to 12 mm, joint gap to 8 mm, suction from 2200 Pa, leak to 350 mm2, battery from 0.25, dirt to 1.0), because the wider ranges gave 0 passes of 40.
- A slide counts per event and only on the glass, not as a running total.

Made after seeing the first formal campaigns (seeds 11, 12, 21, 22), which are withdrawn:

- First results led to dropping the old `all` range table in favour of `worlds/moderate_ranges.json`. Those ranges were fixed before the runs that use them, but after seeing the earlier `all` runs, so they are not blind to that experience.
- Fresh audit fixes: outward wind clamped; one outward load coefficient; safe hold split from `time_limit`; `false_done` based on reported minus true coverage; physics ends at detach; pad torque taken about the centre of mass; sanity limits added. The audit is in `docs/security/SIM-AUDIT-2026-11-06.md`.
- The wind pause stays in the controller at 10 m/s. Changing it per world would need a controller edit, and `controller.py` is frozen at af0424f.
- `controller.py` constants `PIVOT_SAG_M_PER_RAD` and `LANE_OVERRUN_M` were set from the nominal world, before af0424f, and were not reset for later physics changes.
- The nominal control therefore proves little by itself. `worlds/benign.json` is a second control, written by hand and not used for tuning.

- `worlds/moderate_ranges.json` came after seeing the earlier `all` runs. It was committed before the runs that use it, but it is not blind.
- Frozen sim and judge at 6fbbb8d. Later, after seeing those results, `safe_hold` was split into `wind_hold`, `battery_stop` and `stalled`, because most moderate holds happened at low wind and were not safe holds. Physics did not change, and runs were re-scored from stored logs.
