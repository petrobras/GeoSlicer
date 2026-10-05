#!/bin/bash
# Boots the single-node cluster: munge -> mariadb -> slurmdbd -> slurmctld ->
# slurmd -> sshd, then (optionally) an NFS server. Runs as PID 1 and forwards
# signals so `podman stop` is clean.
# -E (errtrace) matters: without it the ERR trap below is not inherited by
# shell functions, so a failing service kills PID 1 with no diagnosis at all.
set -Eeuo pipefail

log() { printf '[slurmlab] %s\n' "$*"; }
die() {
    printf '[slurmlab] ERROR: %s\n' "$*" >&2
    # Go through the same reporting path as an unexpected failure: an explicit
    # exit does not fire the ERR trap, so without this the daemon logs -- where
    # slurm actually writes its fatal errors -- were never shown.
    on_error 1
}

CURRENT_STEP="startup"
step() { CURRENT_STEP="$1"; log "--- $1"; }

dump_logs() {
    for f in /var/log/munge/munged.log /var/log/mariadb.log \
             /var/log/slurm/slurmdbd.log /var/log/slurm/slurmctld.log \
             /var/log/slurm/slurmd.log /var/log/ganesha.log; do
        [ -s "$f" ] || continue
        printf '\n===== %s (last 40 lines) =====\n' "$f"
        tail -40 "$f"
    done

    if command -v slurmd >/dev/null 2>&1; then
        printf '\n===== slurmd -C (the hardware slurmd actually detects) =====\n'
        slurmd -C 2>&1 | head -5 || true
    fi
    if [ -r /etc/slurm/slurm.conf ]; then
        printf '\n===== what slurm.conf declares =====\n'
        grep -E '^(NodeName|PartitionName|SelectType|SlurmdParameters)' /etc/slurm/slurm.conf || true
    fi
}

on_error() {
    local rc=$1
    printf '\n[slurmlab] FAILED during: %s (exit %s)\n' "$CURRENT_STEP" "$rc" >&2
    dump_logs >&2
    if [ "${SLURMLAB_DEBUG_HOLD:-0}" = 1 ]; then
        # Keep the container alive so `podman exec -it <name> bash` can be used
        # to poke at the half-started cluster.
        log "SLURMLAB_DEBUG_HOLD=1: holding the container open for inspection"
        sleep infinity
    fi
    exit "$rc"
}
trap 'on_error $?' ERR

NODE_NAME="$(hostname -s)"
NODE_CPUS="$(nproc)"
# Slurm drains a node whose RealMemory exceeds what it can see, so stay under.
mem_total_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
NODE_MEMORY="$(( mem_total_kb / 1024 - 512 ))"
[ "$NODE_MEMORY" -lt 512 ] && NODE_MEMORY=512
export NODE_NAME NODE_CPUS NODE_MEMORY
export CLUSTER_NAME="${CLUSTER_NAME:-atena}"

: "${NFS_SERVER:=off}"                # off | kernel | ganesha
# Which GeoSlicer versions get a stub launcher. The client asks for
# /atena/users/dibi/containers/geoslicer/<version>/scripts/rps.sh, where
# <version> comes from its own build metadata, so it cannot be derived here:
# add yours with `make-geoslicer-stub <version>` or via this variable.
: "${GEOSLICER_VERSIONS:=2.9.0}"

start_daemon() {
    local name="$1"; shift
    local out=""
    log "starting ${name}"
    if ! out="$("$@" 2>&1)"; then
        if [ -n "$out" ]; then printf '%s\n' "$out" >&2; fi
        die "${name} failed to start"
    fi
    # An `[ -n ... ] && printf` tail would make this function return non-zero
    # whenever the daemon was quiet, which set -e reads as a failed start.
    if [ -n "$out" ]; then printf '%s\n' "$out"; fi
    return 0
}

wait_for() {
    local what="$1" tries="$2"; shift 2
    for _ in $(seq 1 "$tries"); do
        if "$@" >/dev/null 2>&1; then return 0; fi
        sleep 1
    done
    die "timed out waiting for ${what} after ${tries}s"
}

start_munge() {
    log "starting munge"
    install -d -o munge -g munge -m 0755 /run/munge
    runuser -u munge -- munged --force
    wait_for munge 20 munge -n
}

start_mariadb() {
    log "starting mariadb"
    install -d -o mysql -g mysql -m 0755 /run/mysqld
    mariadbd --user=mysql --datadir=/var/lib/mysql \
        --socket=/run/mysqld/mysqld.sock \
        --bind-address=127.0.0.1 >/var/log/mariadb.log 2>&1 &
    wait_for mariadb 60 mariadb --socket=/run/mysqld/mysqld.sock -e 'SELECT 1'
}

render_slurm_conf() {
    # Pass 1: a node line built from what the shell can see. Enough for slurmd
    # to run `-C`, which is the only thing that knows the real topology.
    NODE_LINE="NodeName=${NODE_NAME} CPUs=${NODE_CPUS} RealMemory=${NODE_MEMORY} State=UNKNOWN"
    export NODE_LINE
    envsubst '${CLUSTER_NAME} ${NODE_NAME} ${NODE_LINE}' \
        < /etc/slurm/slurm.conf.tmpl > /etc/slurm/slurm.conf

    # Pass 2: replace it with slurmd's own detection, so socket/core/thread
    # counts match and slurmd stops logging "Node configuration differs from
    # hardware". RealMemory is pulled back a little: a node claiming more than
    # it has gets drained.
    local detected
    detected="$(slurmd -C 2>/dev/null | head -1 || true)"
    case "$detected" in
    NodeName=*)
        NODE_LINE="$(printf '%s' "$detected" \
            | sed -e "s/RealMemory=[0-9]*/RealMemory=${NODE_MEMORY}/" \
                  -e "s/ Gres=[^ ]*//") State=UNKNOWN"
        export NODE_LINE
        envsubst '${CLUSTER_NAME} ${NODE_NAME} ${NODE_LINE}' \
            < /etc/slurm/slurm.conf.tmpl > /etc/slurm/slurm.conf
        ;;
    *)
        log "slurmd -C gave nothing usable; keeping the computed node line"
        ;;
    esac

    log "cluster ${CLUSTER_NAME}, node: ${NODE_LINE}"
}

start_slurm() {
    start_daemon slurmdbd slurmdbd
    # slurmctld's accounting writes go nowhere if dbd is not listening yet.
    wait_for slurmdbd 30 bash -c 'exec 3<>/dev/tcp/127.0.0.1/6819'

    # Idempotent; slurmctld self-registers too, but doing it here means the
    # very first sacct call already has a cluster to look at.
    sacctmgr -i add cluster "${CLUSTER_NAME}" >/dev/null 2>&1 || true

    start_daemon slurmctld slurmctld
    start_daemon slurmd slurmd

    wait_for slurmctld 30 scontrol ping

    # Only nudge a node that is actually down or drained: asking slurm to RESUME
    # an already-IDLE node is rejected and logged as an error.
    if scontrol show node "${NODE_NAME}" 2>/dev/null | grep -qE 'State=[^ ]*(DOWN|DRAIN)'; then
        log "node ${NODE_NAME} is down/drained; resuming it"
        scontrol update NodeName="${NODE_NAME}" State=RESUME >/dev/null 2>&1 || true
    fi
}

start_sshd() {
    install -d -m 0755 /run/sshd
    local ak="/home/${SSH_USER}/.ssh/authorized_keys"
    if [ -f "$ak" ]; then
        # A read-only mounted key file cannot be chowned; sshd still reads it.
        chown "${SSH_USER}" "$ak" 2>/dev/null || true
        chmod 600 "$ak" 2>/dev/null || true
        log "authorized_keys present for ${SSH_USER}"
    fi
    # OpenSSH refuses to start unless argv[0] is absolute ("sshd requires
    # execution with an absolute path"), so this one cannot go through PATH.
    start_daemon sshd "$(command -v sshd)" -e
}

start_nfs() {
    case "$NFS_SERVER" in
    off)
        log "NFS disabled; the bind mounts are the sharing mechanism"
        ;;
    kernel)
        log "starting kernel NFS server (needs --privileged)"
        rpcbind || die "rpcbind failed: the kernel NFS server needs --privileged"
        rpc.nfsd 8 || die "rpc.nfsd failed: needs --privileged and nfsd available on the host kernel"
        exportfs -ra
        rpc.mountd
        exportfs -v
        ;;
    ganesha)
        # Userspace NFSv4 on port 2049: no --privileged, no portmapper.
        log "starting nfs-ganesha (userspace NFSv4) on port 2049"
        mkdir -p /var/run/ganesha /var/lib/nfs/ganesha
        ganesha.nfsd -f /etc/ganesha/ganesha.conf -N NIV_EVENT \
            -L /var/log/ganesha.log -p /run/ganesha.pid \
            || die "ganesha.nfsd failed to start; see /var/log/ganesha.log"
        log "mount with: mount -t nfs4 -o port=2049 <host>:/nethome /nethome"
        ;;
    *)
        die "NFS_SERVER must be off, kernel or ganesha (got '${NFS_SERVER}')"
        ;;
    esac
}

prepare_shared_tree() {
    mkdir -p "$JOBS_DIR" "$MICROTOM_JOBS_DIR" "$GEOSLICER_CONTAINERS_DIR"
    # GeoSlicer runs `chmod -R 777` on its own job dir; these are the parents it
    # has to be able to create that dir in.
    chmod 777 "$JOBS_DIR" "$MICROTOM_JOBS_DIR" 2>/dev/null || true

    # Stub the GeoSlicer CLI launcher, so jobs can be submitted before anyone
    # mounts a real deployment here.
    #
    # Only the names in GEOSLICER_VERSIONS are stubbed, never whatever
    # directories happen to be mounted: this path is often pointed at a folder
    # holding unrelated things (a source checkout, other builds), and creating
    # scripts/ and images/ inside those would be writing into someone's repo.
    IFS=',' read -r -a wanted <<< "${GEOSLICER_VERSIONS}"
    for v in "${wanted[@]}"; do
        [ -n "$v" ] || continue
        make-geoslicer-stub "$v" || log "could not stub version '$v'"
    done
}

report() {
    cat <<EOF
[slurmlab] ---------------------------------------------------------------
[slurmlab]  ssh user:   ${SSH_USER}
[slurmlab]  partitions: default, cpu, gpu
[slurmlab]  job dirs:   ${JOBS_DIR}
[slurmlab]              ${MICROTOM_JOBS_DIR}
[slurmlab]  geoslicer:  ${GEOSLICER_CONTAINERS_DIR}
[slurmlab]              $(ls -1 "$GEOSLICER_CONTAINERS_DIR" 2>/dev/null | tr '\n' ' ')
[slurmlab]  simulators: $(ls -1 /usr/local/bin/microtom_* 2>/dev/null | xargs -n1 basename | tr '\n' ' ')
[slurmlab]  flow (OPM): $(command -v flow || echo 'not installed')
[slurmlab]  LBPM:       $(ls /opt/lbpm/bin 2>/dev/null | head -4 | tr '\n' ' ')
[slurmlab] ---------------------------------------------------------------
EOF
    sinfo || true
}

shutdown_all() {
    log "shutting down"
    pkill -TERM sshd 2>/dev/null || true
    pkill -TERM slurmd 2>/dev/null || true
    pkill -TERM slurmctld 2>/dev/null || true
    pkill -TERM slurmdbd 2>/dev/null || true
    pkill -TERM ganesha.nfsd 2>/dev/null || true
    mariadb-admin --socket=/run/mysqld/mysqld.sock shutdown 2>/dev/null || true
    pkill -TERM munged 2>/dev/null || true
    exit 0
}

case "${1:-run}" in
run)
    trap shutdown_all TERM INT
    step 'munge'; start_munge
    step 'mariadb'; start_mariadb
    step 'slurm.conf'; render_slurm_conf
    step 'slurm daemons'; start_slurm
    step 'shared tree'; prepare_shared_tree
    step 'sshd'; start_sshd
    step 'nfs'; start_nfs
    report
    log "ready"
    # Nothing above holds the container open, so idle on the logs while keeping
    # signal handling in this shell.
    tail -F /var/log/slurm/slurmctld.log /var/log/slurm/slurmd.log 2>/dev/null &
    wait $!
    ;;
shell)
    exec /bin/bash
    ;;
*)
    exec "$@"
    ;;
esac
