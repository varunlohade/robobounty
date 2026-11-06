# Inspection render on a rented RTX 4090

The same command runs on the Mac and on the rented machine. Only `--device` changes. This file has no secrets: use your own SSH key.

Not yet run on a real NVIDIA machine. The commands use the same Blender version as the Mac, 5.2.3 LTS.

## 1. Copy the code and the records from the Mac

Records (`*.npz`) are not in git, so copy them with `rsync`. Run this from the repo root.

```
HOST=user@your-rented-ip
PORT=22
rsync -az --relative -e "ssh -p $PORT" policy/render/ policy/packs/inspection/out/ public/robots/anymal_c/ design/render/_cache/tex/ "$HOST:robobounty/"
ssh -p "$PORT" "$HOST"
```

## 2. Set up the machine, once

Container rentals often log in as root. Drop `sudo` there.

```
nvidia-smi
sudo apt-get update
sudo apt-get install -y ffmpeg xz-utils python3-venv libgl1 libxi6 libxxf86vm1 libxfixes3 libxrender1 libsm6 libxkbcommon0
cd ~
curl -LO https://download.blender.org/release/Blender5.2/blender-5.2.3-linux-x64.tar.xz
tar xf blender-5.2.3-linux-x64.tar.xz
export BLENDER=$HOME/blender-5.2.3-linux-x64/blender
python3 -m venv ~/v
~/v/bin/pip install numpy opencv-python-headless pillow
cd ~/robobounty
~/v/bin/python policy/render/inspection_assets.py
```

`inspection_assets.py` skips maps that the `rsync` already copied. The first render bakes the AgX table and compiles nothing on NVIDIA.

## 3. Test with one still

```
tmux new -s render
export BLENDER=$HOME/blender-5.2.3-linux-x64/blender
~/v/bin/python policy/render/inspection.py still --shot plant --device optix --res 1280x720 --samples 32 --name gpu_test
```

The log must show `render devices: OPTIX` and the card's name. If OptiX fails in a container, check `ldconfig -p | grep optix`. If that is empty, use `--device cuda`.

## 4. Run the set

```
for s in plant low_pipe leak_corner dropped_tray; do
  ~/v/bin/python policy/render/inspection.py still --shot $s --device optix --res 2560x1440 --samples 1024
done
~/v/bin/python policy/render/inspection.py clip --shot plant_route --device optix --samples 256
~/v/bin/python policy/render/inspection.py clip --shot fall --device optix --samples 256
~/v/bin/python policy/render/inspection_check.py --shot plant_route --work design/render/inspection/_work/clip_plant_route --device optix --blender "$BLENDER"
~/v/bin/python policy/render/inspection_check.py --shot fall --work design/render/inspection/_work/clip_fall --device optix --blender "$BLENDER"
```

A stopped clip restarts from its last finished frame when you run the same command again.

## 5. Bring the results back

Run this on the Mac.

```
rsync -az -e "ssh -p $PORT" --exclude _work "$HOST:robobounty/design/render/inspection/" design/render/inspection/
```

Delete the rented machine when you finish. It holds your records.
