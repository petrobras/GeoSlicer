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

# Config git
RUN git config --global --add safe.directory '*'
