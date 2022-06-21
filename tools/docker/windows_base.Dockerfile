FROM gru.ocir.io/grrjnyzvhu1t/geoslicer/windows:latest as base

# Change shell to powershell as default shell for the followings commands
SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'Continue'; $verbosePreference='Continue';"]

ENV OCI_CONFIG_FILE="C:\\Users\\ContainerAdministrator\\.oci\\config"
ENV PYTHONUNBUFFERED 1
ENV PIP_DEFAULT_TIMEOUT 300
# Avoid a setuptools incompatibility https://github.com/numpy/numpy/issues/22623
ENV SETUPTOOLS_USE_DISTUTILS=stdlib

# Set your PowerShell execution policy
RUN Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force

# Install python 3.9
RUN choco install python --version=3.9.13 -y

# Update pip
RUN python -m pip install --upgrade pip==22.3

WORKDIR /slicerltrace

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

# Config git
RUN git config --global --add safe.directory C:/slicerltrace
