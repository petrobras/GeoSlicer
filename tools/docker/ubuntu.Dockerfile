FROM nvidia/cuda:11.2.2-cudnn8-devel-ubuntu20.04 as base

# Read arguments related to OCI credentials
ENV OCI_CONFIG_FILE /root/.oci/config

ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT 300
# Avoid a setuptools incompatibility https://github.com/numpy/numpy/issues/22623
ENV SETUPTOOLS_USE_DISTUTILS=stdlib

# Define image time zone
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

#  Install linux environment requirements
RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y libxkbcommon-x11-0 xvfb x11-utils '^libxcb.*-dev' libdbus-1-dev make automake gcc g++ subversion git libssl-dev libcurl4-openssl-dev gcc-7 cmake ninja-build software-properties-common && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get upgrade -y && \
    add-apt-repository ppa:alex-p/tesseract-ocr-devel && \
    add-apt-repository universe && \
    apt-get update && \
    apt-get install -y -qq --no-install-recommends language-pack-en tesseract-ocr libtesseract-dev libfuse2

# Config git
RUN git config --global --add safe.directory /slicerltrace

# Set home directory allow access to "user" folder
WORKDIR /slicerltrace

# Install python 3.9
RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y software-properties-common && \
    add-apt-repository 'ppa:deadsnakes/ppa' && \
    apt-get install -y python3.9 && \
    apt install -y python3.9-dev python3-pip

# Use python3.9 as python
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.9 10
RUN update-alternatives --install /usr/bin/pip pip /usr/bin/pip3 10

# Update pip
RUN python -m pip install --upgrade pip==22.3

# Install 7z
RUN apt install -y p7zip-full p7zip-rar 

# Install dependencies for GUI display
RUN apt-get update \
  && apt-get install -y -qq --no-install-recommends libglu1-mesa libpulse-dev libnss3 libxdamage-dev libxcursor-dev libasound2 libglvnd0 libgl1 libglx0 libegl1 libxext6 libx11-6 \
  && rm -rf /var/lib/apt/lists/*

# Environment variables for the nvidia-container-runtime.
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES graphics,utility,compute

# Workaround for gcc binary issue
RUN mkdir -p /opt/rh/devtoolset-7/root/usr/bin/ && \
    ln -sf $(which gcc) /opt/rh/devtoolset-7/root/usr/bin/gcc

# Install LTrace libraries dependencies
COPY ./src/ltrace/requirements.txt ./src/ltrace/requirements.txt
RUN python -m pip install -r ./src/ltrace/requirements.txt 

# Install MicrotomRemote dependencies
COPY ./src/modules/MicrotomRemote/Libs/microtom/requirements.txt ./src/modules/MicrotomRemote/Libs/microtom/requirements.txt
RUN python -m pip install -r ./src/modules/MicrotomRemote/Libs/microtom/requirements.txt

# Install deployment tools dependencies
COPY ./tools/deploy/requirements.txt ./tools/deploy/requirements.txt
RUN python -m pip install -r ./tools/deploy/requirements.txt

# Install pipeline tools dependencies
COPY ./tools/pipeline/requirements.txt ./tools/pipeline/requirements.txt
RUN python -m pip install -r ./tools/pipeline/requirements.txt

# Install test environment libraries
COPY ./tests/unit/requirements.txt ./tests/unit/requirements.txt
RUN python -m pip install -r ./tests/unit/requirements.txt

# Install ltrace module required libraries
COPY ./src/ltrace/requirements.txt ./src/ltrace/requirements.txt
RUN python -m pip install -r ./src/ltrace/requirements.txt

FROM base as image-dev
# As development image: Mount repository to avoid copying and keep container running forever
CMD ["sh", "-c", "tail -f /dev/null"]

FROM base as image-prod
# As production image: Copy all context and install packages
RUN apt update && \
    DEBIAN_FRONTEND=noninteractive apt install -y intel-mkl    

COPY . .

RUN git submodule update --init --recursive

# Install ltrace as package
RUN python -m pip install -e ./src/ltrace

# Install Geoslicer modules as package
RUN python -m pip install -e ./src/modules

# Install porespy package
RUN python -m pip install -e ./src/submodules/porespy

# Install BIAEP package
RUN python -m pip install -e ./src/submodules/biaep

CMD ["sh", "-c", "tail -f /dev/null"]
