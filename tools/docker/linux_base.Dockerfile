FROM gru.ocir.io/grrjnyzvhu1t/geoslicer/linux:latest as base

# Set OCI credentials file path
ENV OCI_CONFIG_FILE /root/.oci/config
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT 300
ENV SETUPTOOLS_USE_DISTUTILS=stdlib

#Environment variables for the nvidia-container-runtime.
ENV NVIDIA_VISIBLE_DEVICES all
ENV NVIDIA_DRIVER_CAPABILITIES graphics,utility,compute

# Define image time zone
ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install linux environment requirements
RUN yum -y update && \
    yum -y install libxkbcommon-x11-0 xorg-x11-server-Xvfb xorg-x11-utils libxcb libxcb-devel libdbus-devel make automake gcc gcc-c++ subversion git git-lfs openssl-devel libcurl-devel gcc7 cmake ninja-build epel-release && \
    rm -rf /var/cache/yum/*

RUN yum -y install tesseract-ocr tesseract-ocr-devel fuse-libs

# Config git
RUN git config --global --add safe.directory /slicerltrace

# Install python 3.9
RUN yum -y update && \
    yum -y install python39 python39-devel python3-pip

# Update pip
RUN python3 -m pip install --upgrade pip==22.3

# Install 7z
RUN wget https://www.mirrorservice.org/sites/dl.fedoraproject.org/pub/epel/7/x86_64/Packages/p/p7zip-16.02-20.el7.x86_64.rpm && \
    rpm -U --quiet p7zip-16.02-20.el7.x86_64.rpm && \
    rm p7zip-16.02-20.el7.x86_64.rpm 

RUN wget https://www.mirrorservice.org/sites/dl.fedoraproject.org/pub/epel/7/x86_64/Packages/p/p7zip-plugins-16.02-20.el7.x86_64.rpm && \
    rpm -U --quiet p7zip-plugins-16.02-20.el7.x86_64.rpm && \
    rm p7zip-plugins-16.02-20.el7.x86_64.rpm

# Install libcurl
RUN wget https://curl.haxx.se/download/curl-8.4.0.tar.gz && \
    tar -xzvf curl-8.4.0.tar.gz && \
    rm curl-8.4.0.tar.gz && \
    cd curl-8.4.0 && \
    ./configure --prefix=/usr/local --with-ssl && \
    make && \
    make install && \
    ldconfig && \
    rm -rf curl-8.4.0 

WORKDIR /slicerltrace

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
