#!/bin/bash
# Restarts the text-to-3D service after a pod start. A stop wipes the container disk, so everything lives in /workspace except the system libraries below.
cd /workspace/t3d || exit 1
export DEBIAN_FRONTEND=noninteractive
python3 -c "import ctypes; ctypes.CDLL('libGL.so.1'); ctypes.CDLL('libEGL.so.1'); ctypes.CDLL('libXrender.so.1'); ctypes.CDLL('libSM.so.6')" 2>/dev/null || { apt-get update -qq; apt-get install -y -qq libgl1 libegl1 libglib2.0-0 libxrender1 libsm6 libxext6 libxi6 libxxf86vm1 libxfixes3 libxkbcommon0 >/dev/null; }
pkill -f /workspace/t3d/svc/ 2>/dev/null
sleep 1
nohup /workspace/t3d/venv-img/bin/python /workspace/t3d/svc/service.py >> /workspace/t3d/service.log 2>&1 < /dev/null &
echo "service started on 127.0.0.1:18765, pid $!"
