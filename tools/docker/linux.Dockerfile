FROM gru.ocir.io/grrjnyzvhu1t/geoslicer/linux:2.9.0 as base

# Define image time zone
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN dnf -y update && \
    dnf -y install dnf-plugins-core epel-release && \
    dnf config-manager --set-enabled powertools && \
    dnf -y install \
    xorg-x11-server-Xvfb xorg-x11-utils xorg-x11-xauth libxcb libxcb-devel \
    make automake gcc gcc-c++ subversion git git-lfs openssl-devel libcurl-devel cmake ninja-build gdb \
    libxslt-devel libxml2-devel man-pages man-db man \
    mesa-dri-drivers mesa-libGLU mesa-libGL mesa-libEGL mesa-libgbm \
    libX11 libXext libXrender libXrandr libXcursor libXi libXinerama freetype fontconfig \
    fuse-libs wget p7zip p7zip-plugins \
    tesseract tesseract-devel && \
    dnf clean all

# Install libcurl 8.4.0 from source
RUN wget https://curl.haxx.se/download/curl-8.4.0.tar.gz && \
    tar -xzvf curl-8.4.0.tar.gz && \
    rm curl-8.4.0.tar.gz && \
    cd curl-8.4.0 && \
    ./configure --prefix=/usr/local --with-ssl && \
    make && \
    make install && \
    ldconfig && \
    cd .. && rm -rf curl-8.4.0 

#  Install CUDA 12.1.0 for RHEL 8 (Compatible with Alma 8)
RUN wget https://developer.download.nvidia.com/compute/cuda/12.1.0/local_installers/cuda-repo-rhel8-12-1-local-12.1.0_530.30.02-1.x86_64.rpm && \
    rpm -i cuda-repo-rhel8-12-1-local-12.1.0_530.30.02-1.x86_64.rpm && \
    dnf clean all && \
    dnf -y install cuda-toolkit-12-1 && \
    rm cuda-repo-rhel8-12-1-local-12.1.0_530.30.02-1.x86_64.rpm

# Install cuDNN 8.9.7.29 for RHEL 8
RUN wget https://grrjnyzvhu1t.objectstorage.sa-saopaulo-1.oci.customer-oci.com/p/qCyipzKnYiXmiPxqdr52J2M-VfNthmtdp-jSRh6-vuAAjKbbBpqYgpKJhpN_xStZ/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/requirements/cudnn-local-repo-rhel8-8.9.7.29-1.0-1.x86_64.rpm && \
    rpm -i cudnn-local-repo-rhel8-8.9.7.29-1.0-1.x86_64.rpm && \
    dnf clean all && \
    dnf -y install libcudnn8 libcudnn8-devel && \
    rm -f cudnn-local-repo-rhel8-8.9.7.29-1.0-1.x86_64.rpm

# Export CUDA env vars
ENV PATH=/usr/local/cuda-12.1/bin:$PATH
ENV LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH


# Environment configuration
ARG USER_ID=1000
ARG GROUP_ID=1000

# Create non-root group and user
RUN groupadd -g ${GROUP_ID} sliceruser && \
    useradd -o -u ${USER_ID} -g sliceruser -m sliceruser -s /bin/bash

RUN mkdir -p /slicerltrace && chown -R sliceruser:sliceruser /slicerltrace

ENV OCI_CONFIG_FILE /home/sliceruser/.oci/config
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT 300
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES graphics,utility,compute
ENV PATH="/home/sliceruser/.local/bin:${PATH}"

RUN dnf module reset nodejs -y && dnf module enable nodejs:20 -y && dnf install -y nodejs

USER sliceruser

# UV and Python dependencies
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /slicerltrace

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /bin/

# Copy ONLY the workspace-defining metadata files (all pyproject.toml / setup.py files)
COPY --chown=sliceruser:sliceruser ./pyproject.toml ./
COPY --chown=sliceruser:sliceruser uv.lock ./
COPY --chown=sliceruser:sliceruser ./src/commons/pyproject.toml ./src/commons/
COPY --chown=sliceruser:sliceruser ./tools/pyproject.toml ./tools/
COPY --chown=sliceruser:sliceruser ./src/modules/pyproject.toml ./src/modules/
COPY --chown=sliceruser:sliceruser ./src/third-parties/porespy/pyproject.toml ./src/third-parties/porespy/pyproject.toml
COPY --chown=sliceruser:sliceruser ./src/third-parties/porespy/README.md ./src/third-parties/porespy/README.md
COPY --chown=sliceruser:sliceruser ./src/third-parties/py_pore_flow/pyproject.toml ./src/third-parties/py_pore_flow/pyproject.toml
COPY --chown=sliceruser:sliceruser ./src/third-parties/pyflowsolver/requirements.txt ./src/third-parties/pyflowsolver/requirements.txt
COPY --chown=sliceruser:sliceruser ./src/third-parties/pnflow/python/setup.py ./src/third-parties/pnflow/python/setup.py

ENV VIRTUAL_ENV=/home/sliceruser/.venv
ENV UV_PROJECT_ENVIRONMENT="/home/sliceruser/.venv"
ENV PATH="/home/sliceruser/.venv/bin:$PATH"

RUN uv python install 3.12
RUN uv venv /home/sliceruser/.venv
RUN uv export --all-groups --frozen --no-emit-workspace --no-hashes > requirements-raw.txt && \  
    grep -v -E "commons|pnflow|porespy|py-pore-flow|pyflowsolver|modules|tools" requirements-raw.txt > requirements-pypi.txt && \
    uv pip install -r requirements-pypi.txt


RUN ulimit -c unlimited
RUN git config --global --add safe.directory /slicerltrace
ENV COVERAGE_FILE=/home/sliceruser/.coverage

CMD ["sh", "-c", "tail -f /dev/null"]