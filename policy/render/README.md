# Film renders of recorded runs

`--look v2` is the close, photographic look (`scene_v2.py`, `post_v2.py`). `--look v1` is the older wide look. Both read the same recording.

```
policy/.venv/bin/python policy/render/assets.py     # CC0 maps, once
policy/.venv/bin/python policy/render/render.py still --look v2 --trial design/render/_runs/t0014 --res 2560x1440 --samples 400 --name still_v2
policy/.venv/bin/python policy/render/render.py clip  --look v2 --trial design/render/_runs/t0010 --shot close_slip --samples 56 --name clip_slip_v2
policy/.venv/bin/python policy/render/render.py clip  --look v2 --trial design/render/_runs/t0014 --shot close_pass --samples 56 --name clip_pass_v2
policy/.venv/bin/python policy/render/check.py --trial design/render/_runs/t0010 --work design/render/_work/clip_slip_v2 --all
```

Art in v2, all visual only, nothing feeds back to physics:

- The wall ends at the mullion at x = -2.25 m, so the frame shows air past the corner. The sim's wall is only a plane.
- The tether's and the white body's mirror images are left out of the glass, because they read as a second tether and a second plate.
- The dark bumper and microfibre fringe are a design choice from the concept frames. The fringe does not change the recorded pad path.
- The edge of the film may wander by up to 1.75 cm, which is under half a recorded 5 cm cell. Wipe marks, water spots and dust come from CC0 maps and noise.
- Offices behind the glass, the sun, the sky and the city are invented. Street trees are off. The camera follows a smoothed copy of the recorded path and writes nothing back.
- Dry glass. No droplets: nothing here claims rain.

This folder turns one exported run into a Blender Cycles still or clip.

```
policy/.venv/bin/python policy/render/render.py still --trial nominal-seed1
policy/.venv/bin/python policy/render/render.py clip  --trial nominal-seed1 --samples 64
policy/.venv/bin/python policy/render/check.py --trial nominal-seed1 --work design/render/_work/clip
```

`--trial` takes a folder under `public/trials/` or a path with the same format. Export a new run with
`policy/app_export.py`, then pass its folder. Output goes to `design/render/`, which git ignores.

## Set-up

- `brew install --cask blender`. Blender runs headless at `nice 15` on the Metal GPU.
- The sky map is CC0 from Poly Haven. Download it once:
  `curl -o design/render/_cache/hdri/overcast_soil_puresky.exr https://dl.polyhaven.org/file/ph-assets/HDRIs/exr/4k/overcast_soil_puresky_4k.exr`
- The first render compiles Metal kernels and takes about 3 minutes extra.

## What comes from the recording

- Robot position and orientation: `qpos.json`, applied unchanged. Between 20 Hz samples the pose is interpolated.
- Dirt: `dirt.bin`, one grid per second, blended between seconds and smoothed to texture size.
- Sizes and positions: the 0.36 m body, ride height, mullions, transoms, tower width and roof anchor.
- `check.py` compares the logged poses, dirt texture and copied constants against the sources.

## What is art

Sky, city, haze, glass and film look, camera, depth of field, grain and colour. The tower above and below the
sim's glass repeats the sim's grid. None of this feeds back into physics.

Departures from the sim's visual model, all visual only:

- The body has an inset panel and a tether boot. The MJCF's burgundy band and metal cap are left out.
- The visible tether starts at the tip of the boot, 2 to 3 cm out from the recorded tether point, to clear the rim.
- A flush dark frit band around each pane makes the 5 mm joint read heavier. The joint geometry stays as recorded.
- The white body does not appear in reflections, because it read as a second plate. The dark skirt does.
- The export zeroes the dirt cells at joints, so the texture fills them from neighbours.
- Film outside the assigned area has no record. It is drawn at the run's mean start level.
- Procedural speckle varies the film look inside what the grid allows. It does not move a clean edge.

Do not use this pipeline on frames after a detach until the post-detach motion fix lands.
