# Multiscale Environment



# Multiscale Environment


The Multiscale environment offers a unique integration between three analysis scales: MicroCT, CoreCT, and Image Logs, bringing together specialized modules from each of these areas to facilitate multiscale integration. It is composed of three main components: ***[Geolog Integration](/Multiscale/GeologIntegration/GeologEnv.md)***, which facilitates the import and export of files with Geolog projects; **[Multiscale Image Generation](/Multiscale/MultiscaleImageGeneration/Multiscale.md)**, which uses the MPSlib library to generate synthetic images from a training image; and **[Multiscale Post-Processing](/Multiscale/MultiscalePostProcessing/MultiscalePostProcessing.md)**, focused on the analysis and metrics of multiscale simulation results. With this combination of tools, it is possible to perform multiscale simulations, allowing for more precise and detailed geological modeling. Additionally, the environment enables the import of different data types, expanding the capacity for integration and analysis.


## Sections

The GeoSlicer Multiscale environment is organized into several modules, each dedicated to a specific set of tasks. Click on a module to learn more about its functionalities:

*   **[Geolog Integration](/Multiscale/GeologIntegration/GeologEnv.md):** Tools for integration with Geolog software.
*   **[Import Tools](/Multiscale/ImportTools/ImportTools.md):** Modules for importing Image Log, Core, and Micro-CT data.
*   **[Export Tools](/Multiscale/ExportTools/ExportTools.md):** Modules for exporting Image Log, Core, and Micro-CT data.
*   **[Image Log Pre-processing](/Multiscale/ImageLogPreProcessing/ImageLogPreProcessing.md#image-log-crop):** Tools for cropping, filtering, and correcting image log data.
*   **[Volume Pre-processing](/Multiscale/VolumesPreProcessing/VolumesPreProcessing.md#volumes-crop):** Tools for cropping, resampling, and filtering volumes.
*   **[Multiscale Image Generation](/Multiscale/MultiscaleImageGeneration/Multiscale.md):** Central module for generating high-resolution 3D images.
*   **[Multiscale Post-processing](/Multiscale/MultiscalePostProcessing/MultiscalePostProcessing.md):** Tools for analyzing and processing the generated multiscale image.
*   **[Pore Network](/Multiscale/PNM/PNM.md#extractor):** Modules for extracting and simulating pore networks.
*   **[Volume Segmentation](/Multiscale/Segmentation/VolumeSegmentation.md#manual-segmentation):** Tools for manual and automatic volume segmentation.

## What can you do?

With the GeoSlicer Multiscale environment, you can:

*   **Integrate data from different scales (image logs, cores, micro-CT).**
*   **Generate a high-resolution 3D image representative of the rock from well data.**
*   **Pre-process image data to improve quality and consistency.**
*   **Analyze the generated multiscale image with segmentation and pore analysis tools.**
*   **Extract pore network models to simulate petrophysical properties.**
*   **Calculate permeability and other flow properties.**