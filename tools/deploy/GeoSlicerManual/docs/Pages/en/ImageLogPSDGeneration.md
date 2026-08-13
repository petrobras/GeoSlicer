## Image Generation

The **Image Generation** module allows you to analyze a segmented well log image and determine the Pore Size Distribution (PSD) of the log. This module offers two distinct libraries, Microtom and PoreSpy, each providing different methodologies to calculate the PSD.

### Panels and their usage

| ![Figure 1](../../assets/images/ImageLogPSDGeneration1.png) |
| :---------------------------------------------------------: |
|   Figure 1: Presentation of the Image Generation module.    |

#### The Image Generation module interface is organized into a few sections

1. **Library:**

    | ![Figure 2](../../assets/images/ImageLogPSDGeneration2.png) |
    | :---------------------------------------------------------: |
    |             Figure 2: First section - Library.              |

    In this section, the library used for PSD calculation is selected.

2. **Input:**

    | ![Figure 3](../../assets/images/ImageLogPSDGeneration3.png) |
    | :---------------------------------------------------------: |
    |              Figure 3: Second section - Input.              |

    - **Segmentation:** Segmentation of the well log image from which the PSD will be calculated.
    - **Region (SOI):** Optional input. If a Segment of Interest (SOI) is selected, the PSD calculation will be limited to that specific region of the image, instead of processing the entire log. This can be useful for focusing on specific depth intervals or areas of interest within the log.
    - **Image:** Well log image.

3. **Parameters:**

    In this section, specific parameters for the selected library are configured. The available parameters will dynamically change based on the selected library. The parameters are initially filled with default values, but the user can modify them to suit their needs. The parameters for each library can be reset by clicking the 'Reload Default Values' button.

    - **Microtom:**

        | ![Figure 4](../../assets/images/ImageLogPSDGeneration4.png) |
        | :---------------------------------------------------------: |
        |      Figure 4: Third section - Parameters (Microtom).       |

        - **Saturation resolution:** Resolution of the saturation calculated. Determines a limit for the discretization of the PSD curve in saturation.
        - **Radius resolution:** Resolution of the radii calculated. Determines a limit for the discretization of the PSD curve in radii.

    - **Porespy:**

        | ![Figure 5](../../assets/images/ImageLogPSDGeneration5.png) |
        | :---------------------------------------------------------: |
        |       Figure 5: Third section - Parameters (Porespy).       |

        - **Sizes:** This input can be an integer, a comma-separated list of integers (e.g., `25` or `1, 2, 3, 4`) or empty. This is only used if the method is `Distance Transform` or `Convolution`. If a list of values is provided they are used directly. If a scalar is provided then that number of points spanning the min and max of the distance transform are used. If empty, then all the unique values in the distance transform are used, which may become time consuming.
        - **Smooth:** Indicates if protrusions should be removed from the faces of the spheres or not. Default is `True`.
        - **Method:** Method used to calculate the result:
            - `Distance Transform`: Uses distance transforms to perform erosion and dilation for each radius in the image.
            - `Brute Force`: Uses brute-force to inserts spheres at each voxel.
            - `ImageJ`: Uses the brute-force method but reduces the number of insertion sites by 80-90% to speed up the process.
            - `Convolution`: Uses FFT-based (Fast Fourier Transform) convolution to perform erosion and dilation for each radius in the image.

    The user also has the option to save parameter presets for each library, which can be useful for reusing specific configurations across different logs or projects. When a saved preset is selected, the corresponding parameters will be automatically filled in, facilitating quick module setup for future analyses.

    | ![Figure 6](../../assets/images/ImageLogPSDGeneration6.png) |
    | :---------------------------------------------------------: |
    |        Figure 6: Third section - Parameters Presets.        |

    If a preset is selected and the parameter fields are edited, a warning will appear on the screen indicating that the value in the field differs from the one saved in the preset. This gives the user the option to save the modified values or reset them to the values saved in the preset by clicking the ‘Reload Preset Values’ button.

    | ![Figure 7](../../assets/images/ImageLogPSDGeneration7.png) |
    | :---------------------------------------------------------: |
    |   Figure 7: Third section - Parameters Presets (Warning).   |

    When exporting or importing preset files, the user can select which presets to export or import.

    |  ![Figure 8](../../assets/images/ImageLogPSDGeneration8.png)  |
    | :-----------------------------------------------------------: |
    | Figure 8: Third section - Parameters Presets (Import/Export). |

4. **Output:**

    | ![Figure 9](../../assets/images/ImageLogPSDGeneration9.png) |
    | :---------------------------------------------------------: |
    |             Figure 9: Fourth section - Output.              |

    Defines the prefix for the output node. By default, the prefix takes the same name as the input segmentation node with the `_PSD` suffix.

    | ![Figure 10](../../assets/images/ImageLogPSDGeneration10.png) |
    | :-----------------------------------------------------------: |
    |         Figure 10: Fourth section - Output (Manual).          |

    The prefix can be manually renamed by checking the box next to the field.

### Output

Upon successful execution, the module will generate a new image containing the pore size values in each voxel. It can be used as input in the **Histogram Per Depth** module to generate Probability Density Function (PDF) graphs of the pore sizes.
