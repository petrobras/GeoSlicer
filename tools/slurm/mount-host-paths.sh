#!/bin/bash
# Makes the cluster's job trees reachable at the SAME absolute paths on this
# workstation, which is what the real cluster's NFS mount does.
#
# This is not optional for the MicroTom flow. OneResultSlurmHandler writes the
# input volume to a hardcoded local path and reads results back from it; with
# GEOSLICER_MODE=Remote that path is /nethome/drp/microtom/geoslicer/remote/jobs,
# so it has to exist here and be the same data the container sees.
#
#   sudo ./mount-host-paths.sh                 # bind the default .data tree
#   sudo ./mount-host-paths.sh --data DIR      # a different data dir
#   sudo ./mount-host-paths.sh --umount        # undo
#
# Bind mounts do not survive a reboot; re-run after one.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SLURMLAB_DATA:-$HERE/.data}"
ACTION=mount

while [ $# -gt 0 ]; do
    case "$1" in
        --data)   DATA_DIR="$2"; shift 2 ;;
        --umount|--unmount) ACTION=umount; shift ;;
        -h|--help) awk 'NR>1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

[ "$(id -u)" = 0 ] || { echo "needs root: sudo $0 $*" >&2; exit 1; }

for pair in "nethome:/nethome" "atena:/atena"; do
    src="$DATA_DIR/${pair%%:*}"
    dst="${pair##*:}"

    if [ "$ACTION" = umount ]; then
        if mountpoint -q "$dst"; then
            umount "$dst" && echo "unmounted $dst"
        else
            echo "$dst is not a mount point; nothing to do"
        fi
        continue
    fi

    [ -d "$src" ] || { echo "missing $src -- start the container once first (./run.sh)" >&2; exit 1; }

    if mountpoint -q "$dst"; then
        echo "$dst is already a mount point; leaving it alone"
        continue
    fi

    mkdir -p "$dst"
    mount --bind "$src" "$dst"
    echo "bound $src -> $dst"
done

[ "$ACTION" = umount ] && exit 0

echo
echo "GeoSlicer also needs GEOSLICER_MODE=Remote, or MicroTom builds a Windows"
echo "UNC path for its local directory and never submits the job:"
echo
echo "    GEOSLICER_MODE=Remote /path/to/GeoSlicer"
echo
echo "current contents:"
for d in /nethome/drp/microtom/geoslicer/remote/jobs \
         /nethome/drp/servicos/LTRACE/GEOSLICER/jobs \
         /atena/users/dibi/containers/geoslicer; do
    printf '  %-52s ' "$d"
    if [ -d "$d" ]; then echo "$(find "$d" -maxdepth 1 -mindepth 1 2>/dev/null | wc -l) entries"; else echo MISSING; fi
done
