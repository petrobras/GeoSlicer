FROM gru.ocir.io/grrjnyzvhu1t/geoslicer/windows:2.9.0 as base

ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

RUN choco install opencv --version=4.11.0 -y
RUN choco install procdump --version=11.1.0 -y --ignore-checksums

SHELL ["cmd", "/S", "/C"]

# Install CUDA 12.1
RUN echo Downloading CUDA 12.1... && \
    C:\Windows\System32\curl.exe -fSLo "%TEMP%\cuda_installer.exe" "https://developer.download.nvidia.com/compute/cuda/12.1.0/local_installers/cuda_12.1.0_531.14_windows.exe" && \
    start /wait "" "%TEMP%\cuda_installer.exe" -s -n -f && \
    del /F /Q "%TEMP%\cuda_installer.exe"

# Add CUDA to PATH and set system environment variables
ENV CUDA_PATH="C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.1"
ENV CUDA_PATH_V12_1="C:\\Program Files\\NVIDIA GPU Computing Toolkit\\CUDA\\v12.1"
RUN setx /M PATH "%PATH%;C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\bin;C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\libnvvp"

# --- Install cuDNN 8.9.7.29 (CUDA 12 Version) ---
RUN echo Downloading cuDNN... && \
    C:\Windows\System32\curl.exe -fSLo "%TEMP%\cudnn.zip" "https://grrjnyzvhu1t.objectstorage.sa-saopaulo-1.oci.customer-oci.com/p/2yPniAebLCGRlvAu8SRHL7NOXS1aaabV-WlpVfldLU0WZ1j3zwLFzZs4Op0VJ1K9/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/requirements/cudnn-windows-x86_64-8.9.7.29_cuda12-archive.zip" && \
    7z.exe x "%TEMP%\cudnn.zip" -o"%TEMP%\cudnn" -y && \
    xcopy.exe /E /I /Y "%TEMP%\cudnn\cudnn-windows-x86_64-8.9.7.29_cuda12-archive\bin\*" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\bin" && \
    xcopy.exe /E /I /Y "%TEMP%\cudnn\cudnn-windows-x86_64-8.9.7.29_cuda12-archive\include\*" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\include" && \
    xcopy.exe /E /I /Y "%TEMP%\cudnn\cudnn-windows-x86_64-8.9.7.29_cuda12-archive\lib\x64\*" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\lib\x64" && \
    rd /S /Q "%TEMP%\cudnn" && \
    del /F /Q "%TEMP%\cudnn.zip"

# Enable long path
SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

RUN Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Force
RUN New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force

WORKDIR /slicerltrace

# UV and Python dependencies
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_INSTALL_DIR="C:\\uv"
ENV UV_NO_MODIFY_PATH="1"
RUN [System.Environment]::SetEnvironmentVariable('PATH', ($env:PATH + ';C:\uv'), 'Machine')
RUN pip install uv==0.11.11

# Copy ONLY the workspace-defining metadata files (all pyproject.toml / setup.py files)
COPY ./pyproject.toml ./
COPY uv.lock ./
COPY ./src/commons/pyproject.toml ./src/commons/
COPY ./tools/pyproject.toml ./tools/
COPY ./src/modules/pyproject.toml ./src/modules/
COPY ./src/third-parties/porespy/pyproject.toml ./src/third-parties/porespy/pyproject.toml
COPY ./src/third-parties/porespy/README.md ./src/third-parties/porespy/README.md
COPY ./src/third-parties/py_pore_flow/pyproject.toml ./src/third-parties/py_pore_flow/pyproject.toml
COPY ./src/third-parties/pyflowsolver/requirements.txt ./src/third-parties/pyflowsolver/requirements.txt
COPY ./src/third-parties/pnflow/python/setup.py ./src/third-parties/pnflow/python/setup.py

RUN uv python install 3.12
RUN uv export --all-groups --frozen --no-emit-workspace --no-hashes --output-file requirements-raw.txt ; \
    (Get-Content requirements-raw.txt) -notmatch 'commons|pnflow|porespy|py-pore-flow|pyflowsolver|modules|tools' | Out-File -Encoding ascii requirements-pypi.txt ; \
    uv pip install -r requirements-pypi.txt ; \
    Remove-Item requirements-raw.txt, requirements-pypi.txt


# Config git
RUN git config --global core.longpaths true
RUN git config --global --add safe.directory '*'

SHELL ["cmd", "/S", "/C"]
CMD ["cmd", "/c", "ping", "-t", "localhost", ">", "NUL"]