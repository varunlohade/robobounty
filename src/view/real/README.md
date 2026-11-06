# The realistic simulation view

`src/app/view.ts` draws one recorded run with these modules. All of it runs in the browser with three.js.

| What | Where | Source |
|---|---|---|
| Sky | `public/assets/sky/overcast_soil_top.jpg` | Top half of the CC0 Poly Haven HDRI "Overcast Soil (Pure Sky)", gamma coded to 8 bits. 4096 x 1024, 0.1 MB. |
| Light probe | `view.ts`, `buildEnv` | The sky and the city, baked once at load. |
| City | `city.ts` | Built from a fixed seed at load, in one draw call. Invented. It follows `policy/render/city.py`. |
| Glass | `facade.ts` | A planar reflection pass, per-pane tilt, grime baked on the GPU, the recorded dirt grid. |
| Joints | `facade.ts` | Extruded brushed metal. Positions from the MJCF. |
| Robot | `robot.ts` | Lofted geometry at the sim's sizes. It follows `policy/render/scene.py`. |
| Lens | `post.ts` | Depth of field, ACES, sRGB, film grain. |

## What comes from the recording

- Robot position and orientation: MuJoCo's `xpos` and `xmat` for the `robot` body, unchanged.
- Tether: the recorded anchor point. The robot end leaves from the boot tip, 2 to 3 cm from the recorded tether point.
- Dirt: `dirt.bin`, one grid per second, blended between seconds. A smooth lookup rounds the 5 cm cells. It does not move a clean edge.
- Pane lines, joint heights, the ledge and scene elements: the MJCF.
- Water drops: how many show follows the world's `wetness`. Where each one sits is art.

`src/app/tools/check_view_pose.mjs` checks the drawn pose and the drawn clean share against the recording.

## What is art

Sky, city, haze, glass tint, drops, film speckle, depth of field, grain and the camera. Departures from the MJCF, all visual only:

- A joint is drawn 8 cm wide. The MJCF's capsule stands 4 cm wide at glass level. Its height off the glass is the recorded one.
- The robot's four rollers and burgundy band are replaced by tracks, a shell and a panel.
- The microfibre fringe shows about 1 cm past the pad bar.
- Glass outside the assigned area has no record. It carries the run's mean start level of film.
- The camera follows the robot with a lag. It stops 1.5 m past the assigned area, so a falling robot leaves the frame. The red path stays.

## Quality

`view.ts` picks `high` on a real GPU and `low` on a software renderer. `?quality=high|medium|low` forces one. It drops one step when frames stay over 36 ms.

- `high`: up to 2x pixels, 4x MSAA, half-float colour, mirror at half size, depth of field, grain.
- `medium`: 1x pixels, no depth of field.
- `low`: 1x pixels, no mirror pass, a smaller city, no post pass.
