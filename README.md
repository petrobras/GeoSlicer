# GeoSlicer

[![Apache 2.0][apache-shield]][apache] 
[![Code style][black-shield]][black]
![OS](https://img.shields.io/badge/OS-linux%2C%20windows-0078D4)
![language](https://img.shields.io/badge/python-3.12-blue)
[![based](https://img.shields.io/badge/Based_on-3D_Slicer-1F65B0)](https://github.com/Slicer/Slicer)
[![Discourse](https://img.shields.io/badge/discourse-forum-brightgreen.svg)](https://discourse.ltrace.com.br/)

[apache]: https://opensource.org/licenses/Apache-2.0
[apache-shield]: https://img.shields.io/badge/License-Apache_2.0-blue.svg
[black]: https://github.com/psf/black
[black-shield]: https://img.shields.io/badge/code%20style-black-000000.svg

[![Introduction  video](https://img.youtube.com/vi/EPKBOYkJE40/0.jpg)](https://www.youtube.com/watch?v=_FkbP9fqBJQ)

GeoSlicer is a software platform for digital rock visualization and image processing. It's designed for geoscientists, engineers, and researchers to analyze and visualize 2D and 3D data from various imaging modalities, including thin sections, CT scans, and mCT imagery.

With GeoSlicer, you can perform complex analyses, such as:

*   Image filtering and segmentation
*   Pore network extraction and analysis
*   Petrophysical property calculations
*   3D visualization and animation

GeoSlicer is built on top of [3D Slicer](https://www.slicer.org/) medical imaging platform and can be extended with custom modules to meet your specific needs.

## Table of Contents

*   [Getting Started](#getting-started)
    *   [Developers](#developers)
    *   [How to install GeoSlicer](#how-to-install-geoslicer)
    *   [Usage](#usage)
*   [Features](#features)
*   [Examples and Resources](#examples-and-resources)
*   [Contributing](#contributing)
*   [Community](#community)
*   [License](#license)
*   [Citations](#citations)

## Getting Started

This section will guide you through the process of installing and running GeoSlicer on your local machine.

### System requirements

GeoSlicer runs on most Windows or Linux computers released within the last 5 years. Performance is primarily determined by graphics capabilities and available system memory.

#### Operating System Versions

| OS | Recommended | Notes |
| :--- | :--- | :--- |
| **Windows** | Windows 11 | Windows 10 and older are not officially supported or tested. |
| **Linux** | Ubuntu 22.04+, Debian 11+, Fedora 35+, AlmaLinux 8+ | Latest LTS versions are strongly recommended. |

#### Recommended Hardware Configuration

| Component | Minimum | Recommended |
| :--- | :--- | :--- |
| **Memory** | 8 GB RAM | 10x the size of your loaded dataset (e.g., 16GB RAM for 1.6GB data). |
| **Display** | 1366 x 768 | 1920 x 1080 or higher. |
| **Graphics** | OpenGL 3.2 support | Discrete NVIDIA GPU with VRAM > largest dataset size. |

> **NVIDIA Driver Compatibility**  
> For stable operation and compatibility with GeoSlicer's Python environment, we recommend using **NVIDIA Driver version 576.28 or earlier**. Newer versions may exhibit stability issues with specific internal dependencies.

#### Graphics & Rendering Details
*   **Discrete GPU:** Highly recommended for interactive 3D volume rendering and fluid navigation of complex scenes.
*   **VRAM:** Texture memory should ideally be larger than your largest dataset to avoid performance bottlenecks.
*   **Integrated Graphics:** Suitable for basic 2D visualization and data exploration only.

### Developers

For instructions on how to build GeoSlicer from source, please refer to the [build guide](BUILD.md).

### How to install GeoSlicer

To get started with GeoSlicer, follow these simple steps:

1.  **Download the latest release:**

    Visit the [releases page](https://github.com/petrobras/geoslicer/releases) and download the appropriate version of GeoSlicer for your operating system.

2.  **Extract the archive:**

    Unpack the downloaded `.zip` or `.tar.gz` file to a location of your choice.

**Note:** GeoSlicer is a portable application, so there's no need to run an installer. However, you must have **write permissions** on the folder where you extract the application, as it needs to write data to the `LTrace` subfolder.

### Usage

Once you have extracted the archive, you can run GeoSlicer by executing the `GeoSlicer` executable located in the extracted directory.

## Features

*   **Multi-modal image support:** Work with a wide range of image types, including thin sections, CT scans, and mCT imagery.
*   **Advanced image processing:** Apply a variety of filters and algorithms to enhance and analyze your images.
*   **Pore network analysis:** Extract and analyze pore networks to understand the properties of your rock samples.
*   **Petrophysical calculations:** Calculate important petrophysical properties, such as porosity and permeability.
*   **3D visualization:** Visualize your data in 3D and create stunning animations.
*   **Extensible platform:** Create your own custom modules to extend the functionality of GeoSlicer.

## Examples and Resources

For interactive tutorials and step-by-step guides, visit the [GeoSlicer Manual] (https://ltracegeo.github.io/GeoSlicerManual) or explore videos on the [LTrace YouTube channel](https://www.youtube.com/@ltracegeo).


## Contributing

We welcome contributions from the community! If you'd like to contribute to GeoSlicer, please read our [contributing guidelines](CONTRIBUTING.md) to get started.

## Community

Join our community to ask questions, share your work, and connect with other GeoSlicer users.

*   **GeoSlicer discourse:** [General discussion, bugs, usage questions, examples and solutions](https://discourse.ltrace.com.br/)
*   **GitHub Issues:** [Report bugs and request features](https://github.com/petrobras/geoslicer/issues)

## License

GeoSlicer is licensed under the Apache 2.0 License. See the [LICENSE](LICENSE) file for more details.

## Citations

If you use GeoSlicer in your work, please cite this repository using the right-hand side link **Cite this repository**. Below you can find recent papers that cite GeoSlicer:

*   Carneiro, I., Zanellato, D., Figueiredo, L., & Bordignon, F. (2023). Comparison of geostatistical and machine learning methods for reconstructing 3D images of carbonate rocks. 6th Brazil Interpore Chapter Conference on Porous Media.
*   Carneiro, I., Sapucaia, V., Bordignon, F., Figueiredo, L., Honório, B., & Matias, J. (2024). Application of MPS to Image Log and CoreCT Images Inpainting. 85th EAGE Annual Conference & Exhibition, (1), 1-5.
*   Carneiro, I., Souza, J., Zanellato, D., Mei, M., Sapucaia, V., Figueiredo, L., Bordignon, F., Matias, J., Honório, Bruno César Zanardo, & Surmas, R. (2024). Multiscale analysis of carbonate rocks for the digital rocks platform GeoSlicer, an open source plugin. ROG.e 2024, (2975).
*   Arenhart, R., Bordignon, F., Figueiredo, L., Pereira, M., Formighieri, G., Pacheco, R., Cenci R., & Surmas, R. (2025). Geoslicer open source platform for digital rock image analysis. 5th International Rock Imaging Summit, (276)
*   Arenhart, R., Bordignon, F., Figueiredo, L., Pereira, M., Formighieri, G., Pacheco, R., Cenci R., Melo, R., & Surmas, R. (2025). A Multiscale Approach to Pore-Network Two-Phase Flow Simulation Applied to a Carbonate Reservoir. 17th Annual Meeting Interpore, (7844)
*   Carneiro, I. B., Bordignon, F., Moreira, A. C., Figueiredo, L. P., Mantovani, I. F., Fernandes, C. P., & Volpatto, D. T. (2026). Influence of REV Selection on Multiscale Porosity and Permeability Assessment Using Digital Rock Imaging. 18th Annual Meeting InterPore, MS09 Pore-Scale Physics and Modeling, Poster Presentation.
*   Bordignon, F., Figueiredo, L., Carneiro, I., Arenhart, R., Honório, B., & Surmas, R. (2026). GeoSlicer a Platform for Digital Rock Physics: Integrated Machine Learning, Data Preparation, and Generative AI with SinGAN. 18th Annual Meeting InterPore, MS15 Machine Learning in Porous Media, Oral Presentation.
*   Arenhart, R., Bordignon, F., Figueiredo, L. P., Formighieri, G., Pacheco, R., Cenci, R., Melo, R., & Surmas, R. (2026). Multiscale Pore-Network Model of Carbonate Reservoirs: Experimental Validation and Wettability Analysis. 18th Annual Meeting InterPore, MS09 Pore-Scale Physics and Modeling, Oral Presentation.
