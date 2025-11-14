# Introduction

GeoSlicer can open various types of files, among which RAW, TIFF, PNG, JPG are the main ones when it comes to 2D images for thin sections. For 3D images, GeoSlicer can open files in NetCDF, RAW format, and even directories with 2D images (PNG, JPG, TIFF) forming a 3D volume.

## Open Image

Each project type loads a specific module for image loading into its environment. In all environments, the module that will appear first on the left side of the screen is the main **_Loader_** for that environment. Some environments have more than one loading module, such as the **_Thin Section_** environment, which has the **_Loader_** and the **_QEMSCAN Loader_**.

The existing loading modules are:

- **_Thin Section_**:
    - **_Loader_**: Loads thin section images.
    - **_QEMSCAN Loader_**: Loads thin section images obtained by QEMSCAN.
- **_Volumes_**:
    - **_Micro CT Loader_**: Loads micro CT images.
- **_Well Log_**:
    - **_Loader_**: Loads well log images
    - **_Importer_**: Loads well logs in CSV, JPG, PNG, and TIFF.
- **_Core_**:
    - **_Multicore_**: Loads well core images in batch.
- **_Multiscale_**:
    - **_GeoLog Integration_**: Loads images of different types directly from the Geolog program
    - **_Loader_**: Loads well log images
    - **_Importer_**: Loads well logs in CSV, JPG, PNG, and TIFF.
    - **_Micro CT Loader_**: Loads micro CT images.
    - **_Multicore_**: Loads well core images in batch.