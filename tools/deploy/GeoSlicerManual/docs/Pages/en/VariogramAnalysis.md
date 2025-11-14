## Variogram Analysis

The **Variogram Analysis** module performs an analysis of the spatial correlation and statistical representativeness of data within a given volume.

The variogram is a function that measures the mean squared difference between image values for a given distance between them. Functions that show low values for long distances indicate a greater degree of sample continuity. The module calculates this function for the three image directions (X, Y, and Z) and fits a model to extract parameters such as **Range**, **Sill**, and **Nugget**.

![Variograma](../../assets/images/Schematic_variogram.png){width=40%}

Subvolume analysis is a method for evaluating the **Representative Elementary Volume (REV)**, which corresponds to the smallest volume for which the average of a material's properties becomes constant and representative of the whole. The module determines the REV by analyzing the variation (in the form of standard deviation) of the property's average within subvolumes of increasing sizes. The REV is taken as the low-slope region in the resulting curve.

### Inputs

The module uses a unified input panel:

-   **Input node**: The main volume for analysis. It can be:
    -   `vtkMRMLScalarVolumeNode`: A grayscale image (e.g., micro-CT image).
    -   `vtkMRMLLabelMapVolumeNode`: A segmented image (label map).
    -   `vtkMRMLSegmentationNode`: A segmentation. If this option is used, the user must select which segments from the list should be analyzed. The analysis will be binary (1 for selected segments, 0 for the rest).

-   **Reference**: The volume used to define the geometry, spacing (voxel size), and spatial orientation. Generally, it is the same as the input node.

-   **Region (SOI)**: An optional node to define a mask. If an SOI is provided, the entire analysis (Variogram and REV) will be restricted only to voxels within this region.

### Parameters

There are two main ways to use the module:

-   **Without SOI (FFT Method)**: If no "Region (SOI)" is provided, the module assumes the user wants to analyze the entire volume. To speed up the calculation, it uses a method based on Fast Fourier Transform (FFT).

-   **With SOI (Sampling Method)**: If a "Region (SOI)" is provided, the module uses a point-pair sampling method within the mask. This method calculates directional variograms (**X**, **Y**, **Z**) and an omnidirectional variogram (**r**).

The module is divided into two analysis sections. *Variogram results* calculates the variogram to understand the property's variability in the volume. The parameters of this algorithm are:

-   `Sampling rate`: Percentage of points that will be subsampled within the SOI for the calculation. Aims to improve processing time, at the cost of potential accuracy loss.
-   `Maximum number of samples`: Maximum number of subsampling points that will be used, limiting the sampling defined by the `Sampling rate`. The objective is also to improve processing time, sacrificing accuracy.
-   `Number of lags`: Defines the number of divisions on the distance axis (X-axis of the variogram), analogous to the number of *bins* in a histogram.
-   `Directional tolerance`: Angular tolerance (in degrees) for calculating directional variograms (X, Y, Z). During calculation in a specific direction, the algorithm considers not only perfectly aligned points but also those within this angular tolerance. The objective is to increase statistical robustness, especially in sparse data. For micro-CT data, where point density is high, smaller values (e.g., < 60°) are generally sufficient.
-   `Maximum distance`: Allows manually defining the maximum distance (in mm) for variogram calculation. If unchecked, it uses a default distance (based on the average).
-   `Use nugget`: If checked, it takes into account the "Nugget Effect" when fitting the variogram model.

The *Representative volume analysis* section calculates the standard deviation of the mean as a function of distance. This serves to determine the subvolume size where the property of interest becomes statistically stable. The parameters for this algorithm are:

-   `Number of volume sizes`: The number of different edge sizes to be tested (e.g., 10 sizes between minimum and maximum).
-   `Maximum number of samples per volume`: The number of random subvolumes to be sampled for each size, ensuring statistical robustness.

### Results and Outputs

-   **Variogram Plots**:
    -   A top bar chart shows the number of point pairs (samples) used at each "lag" (distance).
    -   The main plot shows the experimental variogram points and the fitted model curve for each direction (X, Y, Z, r).

-   **Parameter Table**: Below the plot, a table displays the fitted values for **Range**, **Sill**, and **Nugget** for each direction.

-   **REV Plot**:
    -   A top bar chart shows the number of samples (subvolumes) used for each size.
    -   The main plot graphs the **Standard Deviation of the Mean** (Y-axis) against the **Edge Size** (X-axis, in mm).

#### Report Export (HTML)

The module can generate a unified HTML report containing the results of both analyses.

-   **Export directory**: The user specifies the folder where the report will be saved.
-   **Export report**: Upon clicking, the module:
    1.  Extracts metadata from the reference file name (e.g., Well, Plug, Condition, using the convention).
    2.  Captures an image of the current 3D view in Slicer.
    3.  Captures images of the Variogram and REV plots (if they have been calculated).
    4.  Inserts all this information (metadata, images, results tables) into an HTML template (`variogram_report_template.html`) and saves it to the export directory.