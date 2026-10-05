# Build and run — quick reference

Command cheat sheet for the SLURM test cluster. See [README.md](README.md) for
how it works, how the paths are shared, and what its limits are.

## The short way

`run.sh` builds on first use and then starts the container:

```bash
cd /workspace/bugfix-PL-3267/slicerltrace/tools/slurm
./run.sh
```

That's it. Useful follow-ups:

```bash
./run.sh info     # nodes, partitions, queue + why any job is pending
./run.sh selftest # submit a 5s job and follow it to COMPLETED
./run.sh logs     # follow slurmctld and slurmd
./run.sh shell    # bash inside the container
./run.sh stop     # remove it (and everything in it)
./run.sh --build  # force a rebuild
```

`run.sh` rebuilds on its own whenever anything in the build context changes
(`Dockerfile`, `entrypoint.sh`, `conf/`, `bin/`), so editing one of those and
re-running does the right thing. `--build` is only needed to force a rebuild
after changing a `--build-arg`.

### When startup fails

```bash
./run.sh logs                        # what the entrypoint printed
SLURMLAB_DEBUG_HOLD=1 ./run.sh       # keep a failing container alive
podman exec -it slurmlab bash        # then poke at it
```

The entrypoint names the phase it died in and dumps the tail of the munge,
mariadb, slurm and ganesha logs, plus `slurmd -C` next to the node line
`slurm.conf` declares.

## The explicit podman commands

If you'd rather drive it yourself:

```bash
cd /workspace/bugfix-PL-3267/slicerltrace

# build
podman build \
  --build-arg SSH_UID=$(id -u) \
  --build-arg SSH_GID=$(id -g) \
  -t slurmlab tools/slurm

# the shared tree has to exist before it is bind-mounted
DATA=$PWD/tools/slurm/.data
mkdir -p "$DATA/nethome/drp/servicos/LTRACE/GEOSLICER/jobs" \
         "$DATA/nethome/drp/microtom/geoslicer/remote/jobs" \
         "$DATA/atena/users/dibi/containers/geoslicer"

# run
podman run -d --name slurmlab \
  --hostname slurmlab \
  -p 2222:22 \
  -v "$DATA/nethome:/nethome:z" \
  -v "$DATA/atena:/atena:z" \
  -v /workspace/bugfix-PL-3267:/atena/users/dibi/containers/geoslicer:z \
  -e NFS_SERVER=off \
  slurmlab

podman logs -f slurmlab          # watch it come up
podman exec slurmlab slurmlab-info
```

Notes on those flags:

- `SSH_UID` / `SSH_GID` are what keep the job directories editable from the host.
- There is deliberately **no** `--userns=keep-id`: it would map your host uid to
  the same uid inside the container, leaving no root for munged/mariadbd/slurmd/
  sshd to run as. The default rootless mapping makes container-uid-0 your host
  user, which is what makes the bind mount come out owned by you.
- `:z` is the SELinux relabel, and is harmless where SELinux isn't enforcing.

## Variants

```bash
# LBPM compiled in — slow, and unverified
./run.sh --build-arg WITH_LBPM=on

# real NFS instead of the bind mount
./run.sh --nfs ganesha    # nfs-ganesha, userspace NFSv4, rootless
./run.sh --nfs kernel     # in-kernel nfsd, adds --privileged

# other knobs
./run.sh --port 2200 --data ~/slurmlab --ssh-key ~/.ssh/id_rsa.pub
```

## Before the MicroTom flow works

```bash
sudo ./mount-host-paths.sh                  # /nethome and /atena on this machine
GEOSLICER_MODE=Remote /path/to/GeoSlicer    # or MicroTom never submits anything
```

Both are required, not either/or — see the sharing section of the README.

## Connecting

```bash
ssh -p 2222 drp@localhost        # password: geoslicer
```

And in GeoSlicer:

| Field | Value |
|---|---|
| Server | `localhost` |
| Port | `2222` |
| Username | `drp` |
| Password | `geoslicer` |
| CPU partition | `cpu` |
| GPU partition | `gpu` |
| Command setup | *(leave empty)* |

OPM Flow is off by default and cannot be switched on against a Debian base —
there is no Debian package for it. See the OPM section of the README.

## Caveat

None of these commands have actually been run: there is no container engine in
the environment they were written in. If the build trips on something, the apt
package names and the MariaDB bootstrap step are where to look first.
