#!/bin/bash
# Stand-in for lbpm_color_simulator, for tests: writes the same output shape at a fraction of the cost.
#
# Reads Analysis/visualization_interval and Color/timestepMax from the configuration it is given, then emits
# one vis<timestep>/ folder per interval plus a growing timelog.csv, so the whole pipeline — progress
# polling, folder monitoring, 4D playback, report building — can be exercised without LBPM installed.
set -e
CONFIG="${1:-waterflow.db}"
read_value() { grep -E "^[[:space:]]*$1[[:space:]]*=" "$CONFIG" | head -1 | sed -E 's/.*=[[:space:]]*//; s/[;].*//; s#//.*##' | tr -d ' '; }

INTERVAL=$(read_value visualization_interval); INTERVAL=${INTERVAL:-1000}
TOTAL=$(read_value timestepMax); TOTAL=${TOTAL:-5000}
DELAY=${FAKE_LBPM_DELAY:-0.1}

NX=$(read_value N | cut -d, -f1); NY=$(read_value N | cut -d, -f2); NZ=$(read_value N | cut -d, -f3)
if [ -n "$NX" ] && [ -n "$NY" ] && [ -n "$NZ" ]; then
    VOXELS=$((NX * NY * NZ))
else
    VOXELS=""
fi

echo "fake lbpm: interval=$INTERVAL total=$TOTAL voxels=${VOXELS:-unknown}"
printf 'sw krw krn krwf krnf vw vn force pw pn wet peff\n' > timelog.csv
printf 'time rn rw Vwc Vwd Vnc Vnd pwc pnc Ai Xnc Xwc\n' > subphase.csv

STEP=$INTERVAL
SW=100
while [ "$STEP" -le "$TOTAL" ]; do
    mkdir -p "vis$STEP"
    printf 'fake frame %s\n' "$STEP" > "vis$STEP/summary.xmf"
    # An 8-bit full-domain snapshot per frame, as LBPM writes with save_8bit_raw: this is what makes the
    # frames loadable as a time sequence while the run is still going.
    if [ -n "$VOXELS" ]; then
        head -c "$VOXELS" /dev/zero | tr '\0' "$(printf '\\%03o' $(( (STEP / INTERVAL) % 3 + 1 )))" \
            > "vis$STEP/id_t$STEP.raw"
    fi
    printf '0.%s 0.5 0.4 0.5 0.4 1e-6 1e-7 0 0.33 0.34 0 -1.5\n' "$SW" >> timelog.csv
    printf '%s 1 1 1000 10 500 5 0.33 0.34 4200 -1 1\n' "$STEP" >> subphase.csv
    echo "wrote vis$STEP"
    SW=$((SW - 5))
    STEP=$((STEP + INTERVAL))
    sleep "$DELAY"
done
echo "fake lbpm finished"
