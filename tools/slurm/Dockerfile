# syntax=docker/dockerfile:1.7
#
# A single-node SLURM cluster that behaves like the client cluster from
# GeoSlicer's point of view: you reach it over SSH, it answers sbatch/sacct/
# scancel/squeue, and the job directories it writes into are shared with the
# workstation (bind mount by default, NFS optionally).
#
# Everything lives in the container's own layer, so a container is disposable:
# stop it and every job, database row and job directory inside it is gone. Only
# the bind-mounted data folder survives.
#
# Build:
#   podman build -t slurmlab tools/slurm
#   podman build -t slurmlab --build-arg WITH_LBPM=on tools/slurm      # slow, see README
#
# See tools/slurm/README.md for the run command and the GeoSlicer host setup.

# trixie, not bookworm: bookworm has slurm 22.05, whose slurmd initialises the
# cgroup plugin unconditionally and then needs dbus/systemd and a delegated
# cpuset controller -- neither of which exists in a rootless container.
# CgroupPlugin=disabled, which sidesteps that entirely, arrived in slurm 23.02.
# trixie ships 24.11.
ARG DEBIAN_RELEASE=trixie
# LBPM has no distro package, so it has to be compiled: off by default because
# that build dominates the image build time. 'on' selects the builder stage.
ARG WITH_LBPM=off

########################################################################
# LBPM: 'lbpm-on' compiles it, 'lbpm-off' is an empty stand-in. The
# ARG in the FROM below picks one, which is how a Dockerfile does a
# conditional COPY.
########################################################################
FROM debian:${DEBIAN_RELEASE}-slim AS lbpm-off
RUN mkdir -p /opt/lbpm

FROM debian:${DEBIAN_RELEASE}-slim AS lbpm-on
ARG LBPM_REF=master
ARG LBPM_JOBS=
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates \
        libopenmpi-dev openmpi-bin \
        libhdf5-dev libsilo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${LBPM_REF}" https://github.com/OPM/LBPM.git /src/LBPM
# Serial HDF5 on purpose: Debian's libsiloh5 links against the serial build, so
# pairing it with the openmpi HDF5 would give two HDF5s in one binary.
RUN mkdir -p /build/LBPM && cd /build/LBPM && cmake \
        -D CMAKE_BUILD_TYPE=Release \
        -D CMAKE_C_COMPILER=mpicc \
        -D CMAKE_CXX_COMPILER=mpicxx \
        -D CMAKE_CXX_STANDARD=14 \
        -D MPIEXEC=mpirun \
        -D USE_EXT_MPI_FOR_SERIAL_TESTS=TRUE \
        -D USE_CUDA=0 \
        -D USE_HIP=0 \
        -D USE_TIMER=0 \
        -D USE_NETCDF=0 \
        -D USE_SILO=1 \
        -D HDF5_DIRECTORY=/usr/lib/x86_64-linux-gnu/hdf5/serial \
        -D SILO_DIRECTORY=/usr \
        -D SILO_LIB=/usr/lib/x86_64-linux-gnu/libsiloh5.so \
        -D LBPM_INSTALL_DIR=/opt/lbpm \
        /src/LBPM \
    && make -j"${LBPM_JOBS:-$(nproc)}" \
    && make install
RUN test -d /opt/lbpm || (echo "LBPM install dir missing" >&2; exit 1)

FROM lbpm-${WITH_LBPM} AS lbpm

########################################################################
# Runtime
########################################################################
FROM debian:${DEBIAN_RELEASE}-slim AS runtime

# The account GeoSlicer logs in as. The UID/GID matter for the bind mount: give
# them your own ids (see run.sh) or the job directories come out unwritable.
ARG SSH_USER=drp
ARG SSH_UID=1000
ARG SSH_GID=1000
ARG SSH_PASSWORD=geoslicer
# What gets mounted at /atena/users/dibi/containers/geoslicer at run time.
# Recorded in the image so run.sh can default to it.
ARG GEOSLICER_HOST_DIR=/workspace/bugfix-PL-3267
# Cluster name: microtom names its output files "<cluster>_<jobid>.nc" and the
# GeoSlicer side rebuilds that path, so this has to match what it expects.
ARG CLUSTER_NAME=atena
# OPM Flow: 'on' only works on a base whose archive actually carries it.
# Debian has no OPM package (the project's own repo is RPM-only) and the sole
# apt source is Ubuntu jammy/universe, where it is named libopm-simulators-bin.
# Hence off by default -- see README.
ARG WITH_OPM=off
ARG OPM_PACKAGE=libopm-simulators-bin

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    SSH_USER=${SSH_USER} \
    CLUSTER_NAME=${CLUSTER_NAME} \
    GEOSLICER_HOST_DIR=${GEOSLICER_HOST_DIR} \
    GEOSLICER_CONTAINERS_DIR=/atena/users/dibi/containers/geoslicer \
    JOBS_DIR=/nethome/drp/servicos/LTRACE/GEOSLICER/jobs \
    MICROTOM_JOBS_DIR=/nethome/drp/microtom/geoslicer/remote/jobs

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates procps less vim-tiny curl \
        openssh-server \
        munge \
        slurm-wlm slurm-wlm-basic-plugins slurmdbd slurm-client \
        mariadb-server mariadb-client \
        nfs-kernel-server nfs-common rpcbind \
        nfs-ganesha nfs-ganesha-vfs \
        python3 python3-numpy python3-xarray python3-netcdf4 python3-h5netcdf \
        gettext-base \
    && rm -rf /var/lib/apt/lists/*

# OPM Flow (the 'flow' binary), when the base archive has it.
RUN set -eu; \
    if [ "$WITH_OPM" != "on" ]; then \
        echo "OPM not installed (WITH_OPM=$WITH_OPM)"; \
    else \
        apt-get update; \
        if ! apt-cache show "$OPM_PACKAGE" >/dev/null 2>&1; then \
            echo "ERROR: '$OPM_PACKAGE' is not in this base image's archive." >&2; \
            echo "       Debian ships no OPM package. Either build on an Ubuntu" >&2; \
            echo "       jammy base (--build-arg OPM_PACKAGE=libopm-simulators-bin)" >&2; \
            echo "       or leave WITH_OPM=off and build OPM yourself." >&2; \
            exit 1; \
        fi; \
        apt-get install -y --no-install-recommends "$OPM_PACKAGE"; \
        rm -rf /var/lib/apt/lists/*; \
        command -v flow >/dev/null \
            || echo "WARNING: '$OPM_PACKAGE' installed but 'flow' is not on PATH"; \
    fi

COPY --from=lbpm /opt/lbpm /opt/lbpm
ENV PATH=/opt/lbpm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# MPI in a container has no business probing InfiniBand or using shared memory
# across a namespace boundary.
ENV OMPI_MCA_btl=self,tcp \
    OMPI_MCA_plm_rsh_agent=/bin/false \
    OMPI_ALLOW_RUN_AS_ROOT=1 \
    OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1

# --- login account -----------------------------------------------------
RUN groupadd -g "${SSH_GID}" "${SSH_USER}" 2>/dev/null || true \
 && useradd -m -u "${SSH_UID}" -g "${SSH_GID}" -s /bin/bash "${SSH_USER}" \
 && echo "${SSH_USER}:${SSH_PASSWORD}" | chpasswd \
 && mkdir -p /home/"${SSH_USER}"/.ssh \
 && chmod 700 /home/"${SSH_USER}"/.ssh \
 && chown -R "${SSH_UID}:${SSH_GID}" /home/"${SSH_USER}"/.ssh

# Host keys are baked in on purpose. GeoSlicer calls load_system_host_keys(), so
# a key that changed between runs would trip paramiko's BadHostKeyException on a
# stale known_hosts entry. Fine for a disposable test cluster, never for a real one.
RUN ssh-keygen -A \
 && mkdir -p /run/sshd
RUN mkdir -p /etc/ssh/sshd_config.d \
 && grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config \
    || sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
COPY conf/sshd_slurmlab.conf /etc/ssh/sshd_config.d/00-slurmlab.conf

# exec_command runs a non-interactive shell, which sources no profile, so the
# PATH the client sees comes from here.
RUN printf 'PATH="/opt/lbpm/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"\n' > /etc/environment

# --- munge -------------------------------------------------------------
# Debian's postinst already generates the key with `mungekey -c`, so normally
# there is nothing to do here; generate one only if that did not happen.
# (create-munge-key is a Red Hat script and does not exist on Debian, where the
# tool is /usr/sbin/mungekey.)
RUN set -eux; \
    if [ ! -s /etc/munge/munge.key ]; then \
        /usr/sbin/mungekey --create --force --keyfile=/etc/munge/munge.key; \
    fi; \
    chown munge:munge /etc/munge /etc/munge/munge.key; \
    chmod 0700 /etc/munge; \
    chmod 0400 /etc/munge/munge.key; \
    install -d -o munge -g munge -m 0700 /var/log/munge; \
    install -d -o munge -g munge -m 0711 /var/lib/munge

# --- slurm dirs --------------------------------------------------------
# /var/lib/slurm/{slurmctld,slurmd} and /var/log/slurm ship with the Debian
# packages already owned by slurm:slurm; slurm.conf points at those rather than
# at hand-made /var/spool directories.
RUN install -d -o slurm -g slurm -m 0755 /var/lib/slurm /var/lib/slurm/slurmctld /var/log/slurm \
 && install -d -m 0755 /var/lib/slurm/slurmd \
 && install -d -m 0755 /etc/slurm
COPY conf/slurm.conf.tmpl /etc/slurm/slurm.conf.tmpl
COPY conf/slurmdbd.conf /etc/slurm/slurmdbd.conf
COPY conf/cgroup.conf /etc/slurm/cgroup.conf
RUN chown slurm:slurm /etc/slurm/slurmdbd.conf && chmod 600 /etc/slurm/slurmdbd.conf

# --- accounting database ----------------------------------------------
# Initialised here rather than on boot: sacct needs slurmdbd, slurmdbd needs a
# populated MariaDB, and doing that at build keeps container start to seconds.
RUN set -eux; \
    mkdir -p /run/mysqld; \
    chown mysql:mysql /run/mysqld; \
    mariadb-install-db --user=mysql --datadir=/var/lib/mysql >/dev/null; \
    /usr/sbin/mariadbd --user=mysql --datadir=/var/lib/mysql \
        --socket=/run/mysqld/mysqld.sock >/tmp/mariadb-init.log 2>&1 & \
    for _ in $(seq 1 60); do \
        mariadb --socket=/run/mysqld/mysqld.sock -e 'SELECT 1' >/dev/null 2>&1 && break; \
        sleep 1; \
    done; \
    mariadb --socket=/run/mysqld/mysqld.sock -e " \
        CREATE DATABASE IF NOT EXISTS slurm_acct_db; \
        CREATE USER IF NOT EXISTS 'slurm'@'localhost' IDENTIFIED BY 'slurm'; \
        GRANT ALL ON slurm_acct_db.* TO 'slurm'@'localhost'; \
        FLUSH PRIVILEGES;"; \
    mariadb-admin --socket=/run/mysqld/mysqld.sock shutdown

# --- shared trees ------------------------------------------------------
# These paths are hardcoded on the GeoSlicer side, so they exist whether or not
# anything is mounted over them.
RUN mkdir -p "${JOBS_DIR}" "${MICROTOM_JOBS_DIR}" "${GEOSLICER_CONTAINERS_DIR}" /nethome/drp \
 && chmod -R 777 /nethome /atena
COPY conf/mariadb-slurm.cnf /etc/mysql/conf.d/slurm.cnf
COPY conf/exports /etc/exports
COPY conf/ganesha.conf /etc/ganesha/ganesha.conf

# --- cluster-side commands --------------------------------------------
COPY bin/ /usr/local/bin/
RUN chmod 0755 /usr/local/bin/* \
 && for sim in psd hpsd micp drainage_incompressible imbibition_compressible \
               imbibition_incompressible stokes_kabs stokes_kabs_rev \
               darcy_kabs_foam krel; do \
        ln -sf /usr/local/bin/microtom-sim "/usr/local/bin/microtom_${sim}"; \
    done

COPY entrypoint.sh /usr/local/sbin/entrypoint.sh
RUN chmod 0755 /usr/local/sbin/entrypoint.sh

# Everything the entrypoint and the generated job scripts call must resolve now,
# so a missing tool fails the build here with the full list instead of one
# surprise per rebuild. slurmctld and slurmd are update-alternatives symlinks
# created by the packages' postinst, which makes them worth asserting.
RUN set -eu; \
    missing=""; \
    for cmd in munged mungekey mariadbd mariadb mariadb-admin mariadb-install-db \
               slurmctld slurmd slurmdbd sacct sacctmgr sbatch scancel scontrol \
               sinfo squeue sshd ssh-keygen envsubst pkill runuser install \
               python3 ganesha.nfsd rpcbind exportfs rpc.nfsd \
               microtom-sim microtom-worker make-geoslicer-stub rps-stub.sh \
               slurmlab-info slurmlab-selftest microtom_psd microtom_krel; do \
        command -v "$cmd" >/dev/null 2>&1 || missing="$missing $cmd"; \
    done; \
    if [ -n "$missing" ]; then \
        echo "ERROR: these commands are not on PATH:$missing" >&2; \
        exit 1; \
    fi; \
    python3 -c 'import numpy, xarray, h5netcdf'; \
    echo "all required commands present"

EXPOSE 22 2049
ENTRYPOINT ["/usr/local/sbin/entrypoint.sh"]
CMD ["run"]
