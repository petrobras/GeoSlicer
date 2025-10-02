# Compiling GeoSlicer from Source

This document provides detailed instructions on how to set up your development environment and compile GeoSlicer from the source code. Following these steps will allow you to contribute to the development of GeoSlicer, test new features, and customize the application to your needs.

## 1. Prerequisites

Before you begin, you will need to install the following tools and libraries on your system.

### Common Requirements (All Operating Systems)

-   **Python 3.9**: GeoSlicer is built on top of 3D Slicer and requires Python 3.9 for compatibility. We recommend using [Anaconda](https://www.anaconda.com/docs/getting-started/anaconda/install) to manage your Python environment.
    
    To create and activate a new environment with Python 3.9, run the following commands:
    
    ```bash
    conda create --name geoslicer python=3.9
    conda activate geoslicer
    ```
    
-   **Git LFS**: This repository uses Git LFS to handle large files. You will need to install it on your system.
    
    ```bash
    git lfs install
    ```

-   **CUDA and cuDNN**: For GPU acceleration, you will need to install CUDA and cuDNN. Make sure you have the correct NVIDIA drivers installed for your system.
    
    1.  Download and install **CUDA 11.6.2** from the [NVIDIA archive](https://developer.nvidia.com/cuda-11-6-2-download-archive).
    2.  Ensure the `CUDA_PATH_V11_6` environment variable is set and valid.
    3.  Download **cuDNN 8.9.7** for CUDA 11.x from the [NVIDIA developer website](https://developer.nvidia.com/rdp/cudnn-archive).
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
    
    *   [Windows amd64](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/j3-M11OKFLGFcWJGYr4hUQnW8u4sFruUATaH2IcaoSp4f8PcRCisaQH6mH2rtGv0/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/base/release/win32/GeoSlicer-2.2.2-2024-11-21-win-amd64.zip)
    *   [Linux amd64](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/jy3VVQsDEJb9lVRLUz-6Iu_FBwPpw8ooCPdHP9aXKfEJPvWrFPt2Gy2hxwSy3mnq/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/base/release/linux/GeoSlicer-2.2.2-2024-11-21-linux-amd64.tar.gz)
-   **Build from source**: If you need to make changes to the base application, you can build GeoSlicerBase from the source by cloning the [geoslicerbase](https://github.com/ltracegeo/geoslicerbase) and [slicer](https://github.com/ltracegeo/Slicer) repositories.

## 3. Deployment

Once you have all the prerequisites installed, you can deploy GeoSlicer in two modes: **development** and **production**.

### Development Mode

This mode is ideal for developers who are actively working on the GeoSlicer codebase. It sets up a development environment where you can quickly test your changes without having to create a full production build.

To deploy in development mode, run the following command:

```bash
python ./tools/deploy/deploy_slicer.py --dev <path_to_geoslicer_base>
```

Replace `<path_to_geoslicer_base>` with the path to your GeoSlicerBase directory or archive file.

### Production Mode

This mode is used to create a distributable version of GeoSlicer. It packages all the necessary files into a single archive that can be shared with users.

To deploy in production mode, you will need to provide a version number for the release. Run the following command:

```bash
python ./tools/deploy/deploy_slicer.py --geoslicer-version <version_number> <path_to_geoslicer_base>
```

Replace `<version_number>` with the version number for this release (e.g., `2.3.0`) and `<path_to_geoslicer_base>` with the path to your GeoSlicerBase directory or archive file.

### Additional Deployment Options

The deployment script provides several options to customize the build process. Here are a few of the most common ones:

-   `--sfx`: Creates a self-extracting archive for easier distribution.
-   `--generate-public-version`: Generates a public version of GeoSlicer, excluding any proprietary code.
-   `--fast-and-dirty`: Skips some of the build steps, such as installing dependencies, to create a build more quickly. This is useful for testing purposes but should not be used for production releases.

For a full list of options, you can run the deployment script with the `--help` flag:

```bash
python ./tools/deploy/deploy_slicer.py --help
```