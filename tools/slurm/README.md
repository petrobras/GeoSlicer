# SLURM test cluster

A single-node SLURM cluster in a container, meant to look like the client
cluster from GeoSlicer's side: you reach it over SSH, it answers `sbatch`,
`sacct`, `scancel` and `squeue`, and the job directories it writes into are
shared with your workstation. It exists to exercise the Job Monitor and the
remote handlers without booking time on the real cluster.

It is **not** a faithful HPC environment. One node, no cgroup enforcement, no
real compute, and — unless you mount a real GeoSlicer deployment into it —
synthetic simulation results.

Built on Debian **trixie** for its Slurm 24.11. Bookworm's 22.05 cannot run
here: its slurmd initialises the cgroup plugin unconditionally, then needs a
dbus/systemd session and a delegated `cpuset` controller that a rootless
container does not have. `CgroupPlugin=disabled` (slurm ≥ 23.02) is what makes
this work at all.

## Quick start

Command cheat sheet, including the raw podman equivalents: [COMMANDS.md](COMMANDS.md).

```bash
cd tools/slurm
./run.sh                       # builds the image if needed, then starts it
./run.sh info                  # sinfo / squeue / sacct + what got installed
./run.sh logs                  # follow slurmctld and slurmd
./run.sh stop                  # remove the container (and everything in it)
```

Then in GeoSlicer, add an SSH host:

| Field | Value |
|---|---|
| Server | `127.0.0.1` |
| Port | `2222` (`./run.sh --port N` to change) |
| Username | `drp` |
| Password | `geoslicer` |
| CPU / GPU partition | `cpu` / `gpu` |
| Command setup | leave empty |

Use `127.0.0.1`, not `localhost`. Paramiko takes the first address
`getaddrinfo` returns and does not fall back to the next one the way the `ssh`
binary does, so on a machine that resolves `localhost` to `::1` first it only
ever tries IPv6 — and the port is published on `0.0.0.0`. The symptom is
`NoValidConnectionsError` while `ssh -p 2222 drp@localhost` works fine.

To use a key instead of the password: `./run.sh --ssh-key ~/.ssh/id_rsa.pub`.

### When GeoSlicer itself runs in a container

A published port lands in the *host's* network namespace. A GeoSlicer running
in its own container does not share that namespace, so `127.0.0.1:2222` is its
own empty loopback and the host's bridge gateway is usually unroutable — the
same `NoValidConnectionsError`, or a timeout.

Under podman's default rootless mode (pasta) the host is reachable from inside
the container at **`169.254.1.2`**, so the published port needs no changes at
all — point the account at `169.254.1.2:2222`. Note that pasta copies the
host's interface name, address and routes into the container, so the container
appears to have the host's LAN IP while having its own namespace; connecting to
that address loops back inside the container rather than reaching the host,
which is what makes this confusing. Confirm with:

```bash
# from inside the GeoSlicer container
python3 -c "import socket; s=socket.create_connection(('169.254.1.2',2222),3); print(s.recv(64))"
# -> b'SSH-2.0-OpenSSH_10.0p2 Debian-7+deb13u4\r\n'
```

If that address does not answer (older podman, slirp4netns, or docker), put the
two in one namespace instead:

```bash
# the cluster joins the container GeoSlicer runs in; reachable at localhost:22
./run.sh --network container:<geoslicer-container>

# or both on one podman network; reachable at slurmlab:22
podman network create geoslicer-net
podman network connect geoslicer-net <geoslicer-container>
./run.sh --network geoslicer-net
```

Nothing is published in either case (podman rejects `-p` when the namespace
belongs to someone else), so the account's **Port** is `22`, and the **Server**
is `localhost` for `container:` or `slurmlab` for a shared network.

The widget pre-fills both partition fields with `default`; replace that with
`cpu`. Slurm cannot have a partition called "default" — `PartitionName=DEFAULT`
is a reserved keyword that sets defaults for the partition lines after it — so
this cluster offers `cpu` (the default partition) and `gpu`. In practice the
remote handlers never pass a partition to `sbatch` anyway, so the fields are
mostly cosmetic; the stubs submit to `cpu` unless `SLURMLAB_PARTITION` says
otherwise.

## Sharing the job directories

The remote handlers write results into the cluster filesystem and then read them
back **through the local filesystem** — that is the NFS mount on the real
cluster. So the two sides have to agree on paths:

| Path | Used by |
|---|---|
| `/nethome/drp/servicos/LTRACE/GEOSLICER/jobs` | Pore Network handlers, PUC model, `SshHost.get_mounted_path()` |
| `/nethome/drp/microtom/geoslicer/remote/jobs` | MicroTom (`OneResultSlurmHandler`) |
| `/atena/users/dibi/containers/geoslicer` | the GeoSlicer CLI launcher (`rps.sh`) |

`run.sh` bind-mounts a host folder (default `tools/slurm/.data`) onto those
paths inside the container. That is the sharing mechanism, and it is enough on
its own for the handlers that honour the host's **Mounted path** setting: point
it at `<data>/nethome/drp/servicos/LTRACE/GEOSLICER/jobs`.

MicroTom is the exception, and it needs **two** things, not either/or:

```bash
sudo ./mount-host-paths.sh          # 1. same absolute paths on this machine
GEOSLICER_MODE=Remote /path/to/GeoSlicer   # 2. and a POSIX local path
```

`OneResultSlurmHandler` hardcodes its local directory. Without
`GEOSLICER_MODE=Remote` it is the Windows UNC string
`\\dfs.petrobras.biz\...`, which on Linux is a *relative* path whose first
component is a directory name full of backslashes; `write_raw_file` then calls
`os.mkdir` on it, fails on the missing parents, and `deploy()` swallows the
traceback — the remote job directory gets created and **nothing is ever
submitted**. With the variable set the path becomes
`/nethome/drp/microtom/geoslicer/remote/jobs`, which is why the bind mount has
to be there too.

The symptom is a job that stays put with an empty slurm queue and one stray
directory under `/nethome/drp/microtom/geoslicer/remote/jobs`.

### Real NFS instead of a bind mount

If you specifically want to exercise the NFS path:

```bash
./run.sh --nfs ganesha   # nfs-ganesha, userspace NFSv4, works rootless
./run.sh --nfs kernel    # in-kernel nfsd, adds --privileged
```

Then, on the workstation:

```bash
sudo mount -t nfs4 -o port=2049 localhost:/nethome /nethome
```

Ganesha is configured for NFSv4 only (`conf/ganesha.conf`): v3 would need
rpcbind and NLM, which a rootless container cannot provide, while v4 needs
nothing but port 2049.

The bind mount is the default because it needs no privileges and no host kernel
support, and the handlers cannot tell the difference.

## The GeoSlicer CLI launcher

Handlers that go through `get_python_cmd` (Pore Network extractor and
simulation, PUC model) run:

```
/atena/users/dibi/containers/geoslicer/<version>/scripts/rps.sh --sif .../geoslicer-cli.sif --cli '...'
```

`<version>` comes from GeoSlicer's own build metadata, so the container cannot
guess it. It stubs `2.9.0` by default; add yours with:

```bash
podman exec slurmlab make-geoslicer-stub 2.9.0-my-build
# or start with: -e GEOSLICER_VERSIONS=a,b,c
```

Find the string GeoSlicer will ask for by checking `GEOSLICER_VERSION` in
`.../qt-scripted-modules/Resources/json/GeoSlicer.json` of your deployment (a
dev build falls back to a hash-and-date string).

The stub submits a real slurm job and prints `job_id = N`, which is all the
handler reads. If you bind a directory containing a genuine
`<version>/scripts/rps.sh` and a real `.sif`, that is used instead and the CLI
runs for real under Apptainer. `--geoslicer DIR` sets what gets mounted there;
its build-time default is baked in via `--build-arg GEOSLICER_HOST_DIR=...`
(currently `/workspace/bugfix-PL-3267`).

Stubs are only ever created for the names in `GEOSLICER_VERSIONS`, never for
directories that happen to be mounted — otherwise pointing this at a folder
holding a source checkout would write `scripts/` into it.

## Simulators

`microtom_psd`, `microtom_hpsd`, `microtom_micp`,
`microtom_drainage_incompressible`, `microtom_imbibition_compressible`,
`microtom_imbibition_incompressible`, `microtom_stokes_kabs`,
`microtom_stokes_kabs_rev`, `microtom_darcy_kabs_foam`, `microtom_krel`.

These are stubs (`bin/microtom-sim`), because the real cluster-side microtom CLI
is not in this repository — the vendored copy under
`src/modules/MicrotomRemote/Libs/microtom` has its `cli_cluster` module stripped.
Each one submits a slurm job, sleeps, and writes result files in the layout the
collectors expect, so the whole round trip works: the job goes
PENDING → RUNNING → COMPLETED and **Open** loads real volumes and tables.

The numbers are synthetic but derived from your actual input volume (porosity is
measured from the voxels, permeability follows from it), so different inputs give
different results.

`SLURMLAB_JOB_SECONDS` controls how long a job runs — raise it when you want a
job that sticks around long enough to cancel:

```bash
podman exec -e SLURMLAB_JOB_SECONDS=600 slurmlab true   # affects new sessions
# or set it on the host entry's "Command setup": export SLURMLAB_JOB_SECONDS=600
```

## OPM and LBPM

Both are **off by default**, and neither is as easy as it first looked.

**OPM Flow has no Debian package.** The project's own repository at
`opm-project.org/package` is RPM-only, and the sole apt source is Ubuntu
jammy/universe, where it is named `libopm-simulators-bin` rather than
`opm-simulators-bin`. On this Debian base, `WITH_OPM=on` therefore fails fast
with an explanation instead of a bare apt error. To actually get `flow`, either
rebuild on an Ubuntu jammy base, or install it yourself into a running
container.

**LBPM has no package either** and must be compiled, which dominates the build:

```bash
./run.sh --build-arg WITH_LBPM=on
```

That clones `OPM/LBPM` and builds it against OpenMPI, serial HDF5 and Silo
(no CUDA, no TimerUtility), installing into `/opt/lbpm`. Expect tens of minutes
and a much larger image.

**This is the one part I could not verify** — there is no container engine in
the environment I wrote it in, so the LBPM stage has never been run. The cmake
flags follow LBPM's own `sample_scripts/configure_desktop`, but treat the first
build as something to debug rather than something that works. Nothing in the
GeoSlicer codebase calls LBPM today, so it is there for you to drive by hand.

## Statelessness

Everything the cluster produces — slurm's state, the accounting database, job
directories inside the container — lives in the container's own layer.
`./run.sh stop` removes it and the next start is clean. The only thing that
survives is the bind-mounted data folder.

Startup is a few seconds because MariaDB is initialised at **build** time, not
boot: `sacct` needs slurmdbd, and slurmdbd needs a populated database.

SSH host keys are baked into the image on purpose. GeoSlicer calls paramiko's
`load_system_host_keys()`, so keys that changed on every start would trip
`BadHostKeyException` against a stale `known_hosts`. Fine for a disposable test
cluster; never do this for anything real.

## Layout

```
Dockerfile          image: slurm + munge + mariadb + sshd + nfs + stubs
mount-host-paths.sh bind /nethome and /atena on the workstation (needs root)
entrypoint.sh       boots the services in dependency order, PID 1
run.sh              podman/docker convenience wrapper
conf/               slurm.conf template, cgroup, slurmdbd, mariadb, sshd,
                    exports, ganesha
bin/microtom-sim    the microtom_<sim> commands (submits + prints job_id)
bin/microtom-worker writes the result files the collectors read back
bin/rps-stub.sh     stands in for the cluster's GeoSlicer CLI launcher
bin/make-geoslicer-stub   installs that launcher for a given version
bin/slurmlab-info   health check
```

## Known limits

- **One node.** Handlers that ask for many slurm jobs get them queued, not
  parallelised. `slurm_jobs > 1` works but runs sequentially.
- **`krel` results do not load on Linux.** `KrelCompiler.sim_pattern` is
  `r"\\sim(\d+)\\"` — a Windows path pattern — so it never matches a POSIX path
  and the results are silently skipped. The stub still writes the `sim1`/`sim2`
  layout, so this is testable once that regex is fixed.
- **`get_python_cmd` handlers produce no results** unless you mount a real
  `.sif`. The job completes; there is nothing for **Open** to load.
- **MicroTom needs `GEOSLICER_MODE=Remote` plus the host bind mounts** (see
  above). Nothing warns you if they are missing: the job simply never leaves
  the client.
- **No GPU.** The `gpu` partition exists so a GPU request is schedulable, but
  no GRES is configured: if `slurmd -C` detects a card on your workstation, the
  `Gres=` it reports is stripped from the node line, because nothing here sets
  `GresTypes` or ships a `gres.conf`.
- **The LBPM stage is unverified** (see above), and its cmake flags were
  written against bookworm's library paths. They still resolve on trixie
  (`libsiloh5.so`, serial HDF5), but the build itself has never been run.
- **Neither NFS mode is verified.** The bind mount is the tested path; the
  ganesha and kernel modes were written from their documented configuration.

## What was verified, and how

No container engine was available where this was written, so the image itself
has never been built. What *was* checked, by running the scripts against the
client's own code:

- `bin/microtom-sim`'s stdout parses correctly through
  `ltrace.readers.microtom.utils.parse_command_stdout` for the psd, stokes_kabs,
  darcy_kabs_foam and krel paths: integer `job_id`, `final_results` resolving to
  the right local path through `truncate_relative_path_on`, empty stderr (a
  non-empty stderr fails the job in `OneResultSlurmHandler.start`), and the
  `job_id` file that the darcy_kabs_foam path reads back.
- `bin/rps-stub.sh` driven by the command that `get_python_cmd` /
  `get_job_cmd` actually build, with the handlers' own
  `JOB_ID_PATTERN` scraping the id back out.
- `conf/slurm.conf.tmpl` renders with every placeholder filled, and the
  `RealMemory` calculation stays under the host's `MemTotal` (Slurm drains a
  node that claims more memory than it can see).
- `make-geoslicer-stub` is idempotent and never overwrites an existing
  `rps.sh`.
- All shell scripts pass `bash -n`; `microtom-worker` compiles.

Every apt package the Dockerfile installs was checked against the real
`bookworm/main` Packages index, after an earlier check against
`packages.debian.org` proved unreliable — it returns HTTP 200 for pages of
packages that are not in this suite, which is how `unfs3` and
`opm-simulators-bin` got in and broke the build.

Every binary the entrypoint and the generated job scripts invoke was then
checked against the file lists of the debs being installed. That caught
`create-munge-key` (a Red Hat script; Debian's tool is `mungekey`) and
confirmed that `slurmctld` and `slurmd` exist only as update-alternatives
symlinks created by the packages' postinst. The Dockerfile now ends with a
build-time assertion over that whole list, so a missing tool fails the build
with the full set named rather than one surprise per rebuild.

Untested: the rest of the Dockerfile build, service startup, and everything that
needs real slurm (`sacct` output shape, cancellation, the NFS modes).
