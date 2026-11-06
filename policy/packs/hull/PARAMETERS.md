# Hull crawler parameters

Every value below is an ASSUMPTION unless its row names a source. No value comes from a real ship, a real crawler or a measurement. "Source: none" means a reasoned guess. Nothing here claims real cleaning performance.

## Scope

- Adhesion is flat only. The physics plate is the plane z = 0, facing down. The bilge curve in the film is scenery, and the robot never reaches it in the nominal run. A curved hull needs a surface query, which this pack does not have.
- Fluid: MuJoCo's inertia-box fluid model with density, viscosity and `wind` as the current. No waves, no flow field, no boundary layer on the hull and no flow shadow. No added mass.
- Magnet: a force per wheel along the hull normal. It is not a field solution.
- Fouling: a grid of two levels. It is not a biology or a material-removal model. Removal rates were chosen so that one pass cleans most of a disc's width.
- The camera, lamps, hoses, filter and shroud have no effect on physics, except as part of the chassis mass. The waste plume in the film is visual only.

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
| Size | about 0.62 x 0.56 m | Given in the brief, about 0.6 m | |
| Displaced volume | 13.5 L, so 136 N of buoyancy | ASSUMPTION | Source: none. Net weight in water about 110 N |
| Tracks | two, 0.35 m between end contact points, gauge 0.42 m, shoes 90 mm wide | ASSUMPTION | Source: none. The owner asked for a conveyor-style machine |
| Track model | seven sprung capsule rollers per side, 30 mm radius, all driven at the track's speed | ASSUMPTION | The belt itself is not simulated. Its contact is these seven points |
| Point spring | 20000 N/m, 300 N s/m, 20 mm travel | ASSUMPTION | Source: none. Stands for belt and bogie give, and sets bead crossing |
| Magnet force | 700 N per track at zero gap, shared equally along its seven points | ASSUMPTION | Source: none |
| Air-gap falloff | per point, F = F0 / (1 + gap / 8 mm)^2 | ASSUMPTION | Source: none. The form is a common simple fit, not a field solution |
| Fouling in the gap | 1 mm at full slime, 5 mm at full barnacle | ASSUMPTION | Source: none |
| Friction, shoe on steel | paint 0.55, slime 0.25, barnacle 0.40 | ASSUMPTION | Source: none. Read per point from the cell under it |
| Track drive | velocity servo per point, 8 N m limit at 30 mm radius | ASSUMPTION | Source: none |
| Skid steer | the difference of the two track speeds. Pivots scrub, and the judge reports what they cost | ASSUMPTION | Model result, not a measurement |
| Roller brush drum | axis across the robot, 70 mm tip radius, 0.46 m wide, 300 rpm | ASSUMPTION | Source: none |
| Bristle spring | 8000 N/m over the drum's width, 12 mm nominal, about 96 N | ASSUMPTION | Source: none |
| Bristle drag | 0.25 of the preload, against the rim's direction | ASSUMPTION | Source: none |
| Drum load torque | 1.0 N m plus up to 3.0 N m with fouling, plus the drag at the rim | ASSUMPTION | Source: none. Sets the recorded speed droop |
| Slime removal | 16 per second, exponential, at full contact | ASSUMPTION | Source: none |
| Barnacle removal | 7 levels per second, linear, at full contact | ASSUMPTION | Source: none |
| Clean level | 0.15 on both layers | ASSUMPTION | Our threshold |
| Tether | 16 mm, 6 m exposed, Cd 1.2, 8 N preload | ASSUMPTION | Source: none |
| Position fix | 5 Hz, 2 cm noise | ASSUMPTION | Source: none. The fixing method is left open |
| Heading noise | 0.3 degrees | ASSUMPTION | Source: none |
| Controller | lanes 0.40 m apart at 0.25 m/s, pivot at 0.35 rad/s command | ASSUMPTION | Source: none |

## Judge thresholds

Ours, not from any standard: coverage 90%, track slip 25% at the 95th percentile on straight runs, lane error 0.15 m, all contact points 40 mm off the plate for 0.2 s means detached, no travel for 10 s with turning tracks means stuck.

## Known simplifications

- The drum's torque reaction and rim drag act on the robot, but the drum does not collide. Bristle tips are a circle, and each grid cell inside the drum's rectangle compares that circle with the steel.
- A track's seven points share one speed command, each with its own servo. They do not share belt tension.
- The magnet sees the flat plate, not the bead.
- Bead climbing comes from capsule contact with the bead's arc. Its size is a smooth stand-in for a real weld.
- After a detach the robot falls through open water with fluid drag only.

Run the checks from `policy/`: `nice -n 10 .venv/bin/python -m packs.hull.check_pack`. It writes `out/nominal.npz`, which git ignores because the same seed rebuilds it exactly, and `out/results.json`.
