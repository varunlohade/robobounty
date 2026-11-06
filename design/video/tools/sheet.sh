#!/bin/sh
# Contact sheet: one frame every 10 s of the draft, from 4 s on.
cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
i=0; t=4
while [ $t -lt 239 ]; do nice -n 15 ffmpeg -y -loglevel error -ss $t -i draft.mp4 -frames:v 1 -vf scale=480:-1 "$tmp/$(printf %03d $i).jpg"; i=$((i+1)); t=$((t+10)); done
nice -n 15 ffmpeg -y -loglevel error -framerate 1 -i "$tmp/%03d.jpg" -vf "tile=5x5:padding=6:color=0x444444" -frames:v 1 contact-sheet.png
rm -rf "$tmp"
