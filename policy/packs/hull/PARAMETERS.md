# Hull crawler parameters

Every value below is an ASSUMPTION unless its row names a source. No value comes from a real ship, a real crawler or a measurement. "Source: none" means a reasoned guess. Nothing here claims real cleaning performance.

## Scope

- Adhesion is flat only. The physics plate is the plane z = 0, facing down. The bilge curve in the film is scenery, and the robot never reaches it in the nominal run. A curved hull needs a surface query, which this pack does not have.
- Fluid: MuJoCo's inertia-box fluid model with density, viscosity and `wind` as the current. No waves, no flow field, no boundary layer on the hull and no flow shadow. No added mass.
- Magnet: a force per wheel along the hull normal. It is not a field solution.
- Fouling: a grid of two levels. It is not a biology or a material-removal model. Removal rates were chosen so that one pass cleans most of a disc's width.
- A camera or lamp on the robot has no effect on physics. The waste plume in the film is visual only.

## World values

| Value | Number | Label | Source or reason |
|---|---|---|---|
| Water density | 1025 kg/m3 | ASSUMPTION | Common textbook figure for surface seawater |
| Water viscosity | 0.00108 Pa s | ASSUMPTION | Common textbook figure for seawater near 20 C |
| Current | 0.5 m/s, across the lanes | ASSUMPTION | Source: none. A calm-berth guess |
| Weld bead height | 6 mm | ASSUMPTION | Source: none. A proud butt weld |
| Weld bead section | 40 mm radius arc | ASSUMPTION | Source: none. A smooth capsule, so rolling contact stays analytic |
| Plate | seams at x = 1.6, 4.0, 6.4 m and y = 1.0 m | ASSUMPTION | Source: none. A 2.4 m plate spacing |
| Starting fouling | slime 0.75, barnacle 0.4, mean | ASSUMPTION | Source: none. Pattern from the seed, more barnacles near beads |
| Patch | 5.0 x 2.4 m | ASSUMPTION | Chosen so that a run takes minutes |

## Robot values

| Value | Number | Label | Source or reason |
|---|---|---|---|
| Mass | 25.0 kg | Given in the brief | |
| Size | about 0.64 x 0.53 m | Given in the brief, about 0.6 m | |
| Displaced volume | 13.5 L, so 136 N of buoyancy | ASSUMPTION | Source: none. Net weight in water about 110 N |
| Wheels | 65 mm radius, 50 mm wide | ASSUMPTION | Source: none |
| Layout | front pair driven, rear pair on swivels | ASSUMPTION | Our first four-wheel skid steer scrubbed sideways on a pivot and drifted about 1 m, so the rear became swivels |
| Magnet force | 380 N per driven wheel, 133 N per rear wheel, at zero gap | ASSUMPTION | Source: none. The rear is weaker so that the driven pair can pull it over a bead |
| Air-gap falloff | F = F0 / (1 + gap / 8 mm)^2 | ASSUMPTION | Source: none. The form is a common simple fit, not a field solution |
| Fouling in the gap | 1 mm at full slime, 5 mm at full barnacle | ASSUMPTION | Source: none |
| Friction, wheel on steel | paint 0.55, slime 0.25, barnacle 0.40 | ASSUMPTION | Source: none. Read per wheel from the cell under it |
| Wheel drive | velocity servo, 30 N m limit | ASSUMPTION | Source: none |
| Brush discs | two, 125 mm radius, 180 rpm, counter-rotating | ASSUMPTION | Source: none |
| Bristle spring | 4000 N/m, 12 mm nominal, so about 48 N per disc | ASSUMPTION | Source: none |
| Bristle drag | 0.25 of the preload, against travel | ASSUMPTION | Source: none |
| Disc load torque | 0.4 N m plus up to 1.8 N m with fouling | ASSUMPTION | Source: none. Sets the recorded speed droop |
| Slime removal | 8 per second, exponential, at full contact | ASSUMPTION | Source: none |
| Barnacle removal | 3 levels per second, linear, at full contact | ASSUMPTION | Source: none |
| Clean level | 0.15 on both layers | ASSUMPTION | Our threshold |
| Tether | 16 mm, 6 m exposed, Cd 1.2, 8 N preload | ASSUMPTION | Source: none |
| Position fix | 5 Hz, 2 cm noise | ASSUMPTION | Source: none. The fixing method is left open |
| Heading noise | 0.3 degrees | ASSUMPTION | Source: none |

## Judge thresholds

Ours, not from any standard: coverage 90%, wheel slip 25% at the 95th percentile on straight runs, lane error 0.15 m, all wheels 40 mm off the plate for 0.2 s means detached, no travel for 10 s with turning wheels means stuck.

## Known simplifications

- Disc friction on the plate gives no net side force, since the discs turn in opposite directions and the model drops any imbalance.
- Brush contact is not a collision. Bristle tips are a plane, and each grid cell compares that plane with the steel.
- The magnet sees the flat plate, not the bead.
- After a detach the robot falls through open water with fluid drag only.

Run the checks from `policy/`: `nice -n 10 .venv/bin/python -m packs.hull.check_pack`. It writes `out/nominal.npz`, which git ignores because the same seed rebuilds it exactly, and `out/results.json`.
