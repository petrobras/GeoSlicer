#!/bin/bash
# Builds (if needed) and starts the test cluster with podman.
#
#   ./run.sh                       start on ssh port 2222
#   ./run.sh --port 2200           different port
#   ./run.sh --data ~/slurmlab     where the shared job tree lives on this host
#   ./run.sh --geoslicer DIR       what to mount at /atena/users/dibi/containers/geoslicer
#   ./run.sh --ssh-key ~/.ssh/id_rsa.pub    log in with a key instead of a password
#   ./run.sh --network container:NAME      share another container's network, so a
#                                          GeoSlicer running in NAME reaches the
#                                          cluster at localhost:22
#   ./run.sh --network geoslicer-net       join a podman network; reachable as
#                                          host 'slurmlab', port 22
#   ./run.sh --nfs ganesha         also export the trees over userspace NFSv4
#   ./run.sh --build-arg WITH_LBPM=on       rebuild with LBPM (slow)
#   ./run.sh stop | logs | shell | info | selftest
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${ENGINE:-podman}"
IMAGE="${IMAGE:-slurmlab}"
NAME="${NAME:-slurmlab}"
PORT=2222
NFS_PORT=2049
DATA_DIR="${SLURMLAB_DATA:-$HERE/.data}"
GEOSLICER_DIR=""
SSH_KEY=""
NETWORK=""
NFS_SERVER=off
FORCE_BUILD=0
declare -a BUILD_ARGS=()

command -v "$ENGINE" >/dev/null 2>&1 || { echo "$ENGINE not found (set ENGINE=docker to use docker)" >&2; exit 1; }

action=start
while [ $# -gt 0 ]; do
    case "$1" in
        start|stop|logs|shell|info|build|selftest) action="$1"; shift ;;
        --port)      PORT="$2"; shift 2 ;;
        --nfs-port)  NFS_PORT="$2"; shift 2 ;;
        --data)      DATA_DIR="$2"; shift 2 ;;
        --geoslicer) GEOSLICER_DIR="$2"; shift 2 ;;
        --ssh-key)   SSH_KEY="$2"; shift 2 ;;
        --network)   NETWORK="$2"; shift 2 ;;
        --nfs)       NFS_SERVER="$2"; shift 2 ;;
        --build)     FORCE_BUILD=1; shift ;;
        --build-arg) BUILD_ARGS+=(--build-arg "$2"); FORCE_BUILD=1; shift 2 ;;
        # Print the comment header, however long it happens to be, rather
        # than a line range that drifts every time the header changes.
        -h|--help)   awk 'NR>1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

case "$action" in
stop)
    "$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
    echo "stopped and removed $NAME"
    exit 0
    ;;
logs)  exec "$ENGINE" logs -f "$NAME" ;;
shell) exec "$ENGINE" exec -it "$NAME" /bin/bash ;;
info)     exec "$ENGINE" exec "$NAME" slurmlab-info ;;
selftest) exec "$ENGINE" exec "$NAME" slurmlab-selftest ;;
esac

build() {
    echo "==> building $IMAGE"
    # The UID/GID of whoever runs this, so files the cluster writes into the
    # bind mount stay editable from the host. Running as root is the exception:
    # useradd cannot create an account with uid 0.
    local uid gid
    uid="$(id -u)"; gid="$(id -g)"
    if [ "$uid" = 0 ]; then uid=1000; gid=1000; fi
    # ${arr[@]+"${arr[@]}"} rather than "${arr[@]:-}": the latter expands an
    # empty array to one empty-string argument, which the engine then reads as a
    # second positional argument next to the build context.
    "$ENGINE" build \
        --build-arg "SSH_UID=${uid}" \
        --build-arg "SSH_GID=${gid}" \
        ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} \
        -t "$IMAGE" "$HERE"
    touch "$HERE/.build-stamp"
}

# A stamp file rather than the image's creation timestamp: no engine-specific
# date format to parse, and it works the same under docker.
STAMP="$HERE/.build-stamp"

sources_changed() {
    [ -f "$STAMP" ] || return 0
    # Anything in the build context that ends up inside the image.
    local newer
    newer="$(find "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$HERE/conf" "$HERE/bin" \
        -newer "$STAMP" -print -quit 2>/dev/null)"
    [ -n "$newer" ]
}

if [ "$FORCE_BUILD" = 1 ]; then
    build
elif ! "$ENGINE" image exists "$IMAGE" 2>/dev/null; then
    build
elif sources_changed; then
    # Without this, editing entrypoint.sh or conf/ and re-running would start
    # the previous image and look like the edit did nothing.
    echo "==> build context changed since the last build; rebuilding"
    build
fi
[ "$action" = build ] && exit 0

# Read the build-time default for the GeoSlicer directory out of the image.
# Missing or unreadable is fine -- the container falls back to its own stub tree
# -- so this must not be allowed to abort the script under set -e/pipefail.
image_env() {
    "$ENGINE" image inspect "$IMAGE" \
        --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | sed -n "s/^$1=//p" | head -1
}

if [ -z "$GEOSLICER_DIR" ]; then
    GEOSLICER_DIR="$(image_env GEOSLICER_HOST_DIR || true)"
    # That default is baked in at build time and is only right on the machine it
    # was built for. If it does not resolve here, try the directory holding this
    # checkout, which is the layout it was standing in for.
    if [ ! -d "$GEOSLICER_DIR" ]; then
        candidate="$(cd "$HERE/../.." && cd .. && pwd)"
        if [ -d "$candidate" ]; then
            echo "==> baked-in ${GEOSLICER_DIR:-<unset>} not present; using ${candidate}"
            GEOSLICER_DIR="$candidate"
        fi
    fi
fi

mkdir -p "$DATA_DIR/nethome/drp/servicos/LTRACE/GEOSLICER/jobs" \
         "$DATA_DIR/nethome/drp/microtom/geoslicer/remote/jobs" \
         "$DATA_DIR/atena/users/dibi/containers/geoslicer"

"$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true

# Joining an existing namespace means the cluster has no ports of its own to
# publish and no hostname to set -- both belong to whoever owns the namespace,
# and podman rejects them here. Everything is then reached on port 22 directly.
PUBLISH=1
case "$NETWORK" in
    container:*|host|ns:*) PUBLISH=0 ;;
esac

declare -a opts=(
    -d --name "$NAME"
    -v "$DATA_DIR/nethome:/nethome:z"
    -v "$DATA_DIR/atena:/atena:z"
    -e "NFS_SERVER=${NFS_SERVER}"
    -e "SLURMLAB_DEBUG_HOLD=${SLURMLAB_DEBUG_HOLD:-0}"
)

if [ -n "$NETWORK" ]; then
    opts+=(--network "$NETWORK")
fi

if [ "$PUBLISH" = 1 ]; then
    opts+=(--hostname slurmlab -p "${PORT}:22")
fi

# Deliberately NOT --userns=keep-id. That maps your host uid to the *same* uid
# inside the container, which leaves the container with no root at all -- and
# every service here (munged, mariadbd, slurmd, sshd) needs it. The default
# rootless mapping already makes container-uid-0 your host user, so the files
# these services write into the bind mount come out owned by you.
#
# Files created by the *login* user (drp, uid 1000 in the container) land under
# a subuid instead. Everything is chmod 777, so that stays readable and
# writable; if you ever need to reclaim ownership on the host, use
#   podman unshare chown -R 0:0 <path>

# Mounted read-write, not read-only: make-geoslicer-stub has to be able to drop
# a scripts/rps.sh next to a real deployment. It only ever creates directories
# named after GEOSLICER_VERSIONS, never touching what is already there.
if [ -n "$GEOSLICER_DIR" ] && [ -d "$GEOSLICER_DIR" ]; then
    echo "==> mounting $GEOSLICER_DIR at /atena/users/dibi/containers/geoslicer"
    opts+=(-v "${GEOSLICER_DIR}:/atena/users/dibi/containers/geoslicer:z")
elif [ -n "$GEOSLICER_DIR" ]; then
    echo "==> $GEOSLICER_DIR does not exist; using the container's own stub tree instead"
fi

if [ -n "$SSH_KEY" ]; then
    [ -f "$SSH_KEY" ] || { echo "no such key: $SSH_KEY" >&2; exit 1; }
    user="$(image_env SSH_USER || true)"
    opts+=(-v "${SSH_KEY}:/home/${user:-drp}/.ssh/authorized_keys:ro,z")
fi

if [ "$PUBLISH" = 1 ]; then
    case "$NFS_SERVER" in
        kernel) opts+=(--privileged -p "${NFS_PORT}:2049" -p 111:111) ;;
        ganesha) opts+=(-p "${NFS_PORT}:2049") ;;
    esac
elif [ "$NFS_SERVER" = kernel ]; then
    opts+=(--privileged)
fi

"$ENGINE" run "${opts[@]}" "$IMAGE"

echo "==> waiting for slurm"
ready=0
for _ in $(seq 1 90); do
    state="$("$ENGINE" inspect -f '{{.State.Status}}' "$NAME" 2>/dev/null || echo gone)"
    if [ "$state" != running ]; then
        # The entrypoint died. Its own output is the only useful diagnosis, so
        # show it rather than printing a "cluster up" banner over a corpse.
        echo "==> container is '${state}', not running. Last output:" >&2
        "$ENGINE" logs "$NAME" 2>&1 | tail -60 >&2
        cat >&2 <<EOF

==> startup failed
    Full log:   $0 logs
    To keep a failing container open for inspection, start it with
    SLURMLAB_DEBUG_HOLD=1 and then: $ENGINE exec -it $NAME bash
EOF
        exit 1
    fi
    if "$ENGINE" exec "$NAME" sinfo >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done

if [ "$ready" != 1 ]; then
    echo "==> slurm did not become ready in time. Last output:" >&2
    "$ENGINE" logs "$NAME" 2>&1 | tail -60 >&2
    exit 1
fi

"$ENGINE" exec "$NAME" slurmlab-info || true

ssh_user="$("$ENGINE" exec "$NAME" printenv SSH_USER 2>/dev/null || true)"
ssh_user="${ssh_user:-drp}"

if [ "$PUBLISH" = 1 ]; then
    reach="ssh -p ${PORT} ${ssh_user}@127.0.0.1        (address 127.0.0.1, port ${PORT})"
else
    # Sharing a namespace: nothing is published, and the cluster answers on 22
    # wherever that namespace is -- which is where GeoSlicer has to be too.
    reach="ssh ${ssh_user}@localhost        from inside ${NETWORK#container:} (address localhost, port 22)"
fi

cat <<EOF

==> cluster up
    ssh:            ${reach}
    shared data:    ${DATA_DIR}
    logs:           $0 logs
    stop:           $0 stop

    For the microtom flow, the workstation needs the same absolute paths.
    Either point the host's "Mounted path" at
        ${DATA_DIR}/nethome/drp/servicos/LTRACE/GEOSLICER/jobs
    or bind the trees into place (needs root, once per boot):
        sudo mkdir -p /nethome /atena
        sudo mount --bind ${DATA_DIR}/nethome /nethome
        sudo mount --bind ${DATA_DIR}/atena   /atena
    See tools/slurm/README.md.
EOF
