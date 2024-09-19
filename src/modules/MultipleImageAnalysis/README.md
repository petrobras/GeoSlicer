# Multiple Image Analysis

This extension of _GeoSlicer_, developed by LTRACE, enables the generation of various analyses from datasets included in multiple GeoSlicer projects. To use this extension, provide a directory path that contains multiple GeoSlicer project folders. Each project name should follow the pattern:

`<TAG>_<DEPTH_VALUE>`

### Example Directory Structure

- **Projects**
  - `TAG_3000.00m`
    - `TAG_3000.00m.mrml`
    - **Data**
  - `TAG_3010.00m`
    - `TAG_3010.00m.mrml`
    - **Data**

## Available Analysis Types

### 1. Histogram in Depth

Generates a histogram curve for each depth value based on a specific parameter from the Segment Inspector plugin's report.

#### Configuration Options

- **Histogram Input Parameter**: Defines the parameter used to create the histogram.
- **Histogram Weight Parameters**: Defines the parameter used as weight in the histogram.
- **Histogram Bins**: Specifies the number of bins in the histogram.
- **Histogram Height**: Adjusts the visual height of the histogram curve.
- **Normalize**: Applies normalization to the histogram values. Normalization can be based on the number of elements in the report or on parameters available in the Segment Inspector's report (e.g., Voxel area, ROI area).

### 2. Mean in Depth

Calculates the mean value for each depth based on a specific parameter from the Segment Inspector plugin's report.

#### Configuration Options

- **Mean Input Parameter**: Defines the parameter to be analyzed.
- **Mean Weight Parameter**: Defines the parameter used as weight during the analysis.

### 3. Basic Petrophysics

Generates a table that includes parameters related to the Basic Petrophysics method from the Segment Inspector plugin, organized by depth value.

