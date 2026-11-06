#!/bin/bash
# Opens the SSH tunnel to the text-to-3D service on the pod. A pod stop changes the address, so pass the current one from the Runpod console or the get-pod tool: gpu_tunnel.sh <host> <port>
set -e
[ $# -eq 2 ] || { echo "usage: gpu_tunnel.sh <host> <port>"; exit 2; }
exec ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 127.0.0.1:18765:127.0.0.1:18765 -p "$2" "root@$1"
