# Compiling GeoSlicer from Source

This document provides detailed instructions on how to set up your development environment and compile GeoSlicer from the source code. Following these steps will allow you to contribute to the development of GeoSlicer, test new features, and customize the application to your needs.

## 1. Prerequisites

Before you begin, you will need to install the following tools and libraries on your system.

### Common Requirements (All Operating Systems)

-   **Python 3.12**: GeoSlicer is built on top of 3D Slicer and requires Python 3.12 for compatibility. We use [`uv`](https://docs.astral.sh/uv/) to manage the Python version and virtual environment. The `setup_dev.sh` / `setup_dev.ps1` scripts described in [Python Dependencies](#3-python-dependencies) will install `uv` and Python 3.12 for you, so no manual setup is required here.

-   **Git LFS**: This repository uses Git LFS to handle large files. You will need to install it on your system.

    ```bash
    git lfs install
    ```

-   **CUDA and cuDNN**: For GPU acceleration, you will need to install CUDA and cuDNN. Make sure you have the correct NVIDIA drivers installed for your system.

    > **NVIDIA Driver Compatibility**: For stable operation with GeoSlicer's Python environment, we recommend using **NVIDIA Driver version 576.28 or earlier**. Newer versions may exhibit stability issues with specific internal dependencies.

    1.  Download and install **CUDA 12.1.0** from the [NVIDIA archive](https://developer.nvidia.com/cuda-12-1-0-download-archive).
    2.  Ensure the `CUDA_PATH_V12_1` environment variable is set and valid (e.g. `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1`).
    3.  Download **cuDNN 8.9.7** for CUDA 12.x from the [NVIDIA developer website](https://developer.nvidia.com/rdp/cudnn-archive).
    4.  Follow the [cuDNN installation instructions](https://docs.nvidia.com/deeplearning/cudnn/installation/latest/index.html).

-   **Tesseract OCR**: Required for optical character recognition (OCR) to automatically detect scale information from images in the `ThinSectionLoader` and `CorePhotographLoader` modules. GeoSlicer uses a specific bundled version of Tesseract.

    1.  Download the appropriate binary for your operating system:
        *   **Windows**: [Tesseract-OCR.zip](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/qf5DrnmKQny4OFCSxJnt0ugFr5Fl9cw-XnDCCJi5YUSgcO_EDVG47CUvsqmnloV8/n/grrjnyzvhu1t/b/share/o/GeoSlicer/Tesseract-OCR.zip)
        *   **Linux**: [Tesseract-OCR.tar.xz](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/m1Sl39ffuHsWPIwCv929-wZJ8HS2FWS44ok45LMeGGobOKZ8SyCZhvX-0r2I1a3N/n/grrjnyzvhu1t/b/share/o/GeoSlicer/Tesseract-OCR.tar.xz) (This is a Tesseract 4.1.1 AppImage).
    2.  Place the downloaded archive in the `tools/deploy/Assets/` folder of the repository.
    3.  **Linux Users**: The Linux binary is an AppImage, which requires FUSE to run. See the [Linux-Specific Requirements](#linux-specific-requirements) section for details on installing FUSE.

    For more information about Tesseract, visit the [official Tesseract OCR GitHub page](https://github.com/tesseract-ocr/tesseract).

### Windows-Specific Requirements

-   **Visual Studio Community 2019**: Windows developers will need the C++ Build Tools, which are available in [Visual Studio Community 2019](https://visualstudio.microsoft.com/vs/older-downloads/). During the installation, make sure to select the **MSVC v142 for x64/x86 (14.29)** individual component.

### Linux-Specific Requirements

-   **FUSE**: GeoSlicer uses a pre-built binary of Tesseract OCR, which is packaged as an AppImage. To run AppImages on Linux, you will need to install the FUSE library. You can find instructions on how to install it in the [AppImage documentation](https://github.com/AppImage/AppImageKit/wiki/FUSE).


## 2. GeoSlicerBase

GeoSlicer is built on top of a modified version of 3D Slicer called **GeoSlicerBase**. You have two options for obtaining it:

-   **Download the pre-built binaries (Recommended)**: This is the easiest and fastest way to get started. You can download the pre-built binaries for your operating system from the links below:

    *   [Windows amd64](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/fTj1fha337JiQkTHVSJZzN1tNVvz7VFJ9mcfFlNpy6csjwIgIgy-KtH_h_PZoHhJ/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/base/release/win32/GeoSlicer-2.7.1-2025-08-07-win-amd64.zip)
    *   [Linux amd64](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/wxxSabOwh2b69CV3EodNcWF3srseT-R6D-5aUFTlv-KBqGNhKyF_eeV86WWhTR3O/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/base/release/linux/GeoSlicer-2.7.1-2025-08-07-linux-amd64.tar.gz)
-   **Build from source**: If you need to make changes to the base application, you can build GeoSlicerBase from the source by cloning the [geoslicerbase](https://github.com/ltracegeo/geoslicerbase) and [slicer](https://github.com/ltracegeo/Slicer) repositories.

## 3. Python Dependencies

Before deploying GeoSlicer, you need to install the required Python dependencies.

**Using `uv` (recommended):** Run the following setup scripts to configure the development environment:
- Linux/macOS: `./setup_dev.sh`
- Windows PowerShell: `./setup_dev.ps1`

These scripts install `uv` if it's not already installed, and then install the project dependencies.

**Using `pip` (alternative):** If you prefer pip, you can install the dependencies:

```bash
pip install . ".[dev]"
pip install -r requirements-dev.txt
```

## 4. Deployment

The deployment script `tools/deploy/deploy_slicer.py` is the primary tool for setting up your environment. It handles:
- **Dependency Management**: installs local packages (like `commons`) in editable mode (for dev) or as standard packages.
- **Extension Linking**: Links or copies GeoSlicer modules into the base application.
- **Asset Injection**: Configures icons, splash screens, and partner-specific code.

You can deploy GeoSlicer in two modes: **development** and **production**.

### Development Mode

This mode is ideal for developers who are actively working on the GeoSlicer codebase. It sets up a development environment where you can quickly test your changes without having to create a full production build.

To deploy in development mode, run the following command:

```bash
python ./tools/deploy/deploy_slicer.py --dev <path_to_geoslicer_base>
```

Replace `<path_to_geoslicer_base>` with the path to your GeoSlicerBase directory or archive file.

### Production Mode

This mode creates a standalone, distributable version of GeoSlicer. It packages all code, compiles Cython extensions, and optionally creates a compressed archive.

To deploy in production mode, run:

```bash
python ./tools/deploy/deploy_slicer.py --geoslicer-version <version_number> <path_to_geoslicer_base>
```

### uv alias

You can run the deploy script through the alias:

```bash
uv run deploy <arguments>
```

### Additional Deployment Options

The deployment script provides several options:

-   `--partner <name>`: Injects proprietary code from `src/partners/<name>`.
-   `--sfx`: Creates a self-extracting archive (Windows only).
-   `--fast-and-dirty`: Skips dependency installation and asset copying to speed up deployment. Useful for quick module tests.
-   `--without-porespy`: Skips the installation of the `porespy` submodule if already present in the base.
-   `--plugin-to-geolog <path>`: Integrates GeoSlicer into an existing Geolog installation.
-   `--keep-tests`: Includes test files in the production build (they are excluded by default).
-   `--disable-archiving`: Prevents the creation of a `.zip` or `.tar.gz` file after deployment.
-   `-o, --output-dir <path>`: Specifies where the deployed application should be stored.

For a full list of options, run:

```bash
python ./tools/deploy/deploy_slicer.py --help
```
