# Image Log PSD Generation

_GeoSlicer_ module to generate the pore size distribution image on image logs.

## Interface

### Input
1. __PSD Backend__: Select the lib that will be used to execute the Pore Size Distribution.
2. __Segmentation__: Select a segmentation node in which the PSD algorithm will be applied.
3. __Region (SOI)__: Select a segmentation node where the first segment delimits the region of interest where the segmentation will be performed. (Optional)
4. __Segments__: Select one or more segments in the list to be used as the pore space.
5. __Parameters__:
    1. __Presets__: Select a preset to autofill the parameter fields. (Optional)
    2. __Microtom__:
        1. __Saturation Resolution__: Resolution of the saturation calculated. Determines a limit for the discretization of the PSD curve in saturation.
        2. __Radius Resolution__: Resolution of the radii calculated. Determines a limit for the discretization of the PSD curve in the radii.
    3. __PoresSpy__:
        1. __Sizes__: This input can be an integer or a comma-separated list of integers (e.g., `25` or `1, 2, 3, 4`). It represents the number of bins to be used when drawing the spheres, or the actual bins to be used. The default is 25, which means 25 logarithmically spaced sizes are used, from the maximum of the distance transform down to 1. If a list of actual sizes is provided, these are used directly, which can be useful for generating custom compartments, for example, with linear or bimodal spacing.
        2. __Division__: This input can be an integer or a comma-separated list of two integers (e.g., `1` or `2, 2`). This parameter represents the number of times the image should be divided for parallel processing. If it is `1`, parallel processing does not occur. `2` is equivalent to `[2, 2]` for a 2D image.
        3. __Mode__: Method used to calculate the result:
            - `Hybrid`: This is the default value. It performs a distance transform of the void space, sets limits to find voxels larger than those defined in `Sizes`, reduces the resulting mask, and then dilates it using the Efficient Fast Fourier Transform (FFT) method to obtain the non-wetting fluid configuration.
            - `Distance Transforms`: Same as `Hybrid`, except it uses a second distance transform, relative to the thresholded mask, to find the invading fluid configuration. The choice between `Distance Transforms` or `Hybrid` depends on speed, which is system and installation specific.
            - `Morphological Image Opening`: Uses a single step of morphological image opening to directly obtain the invading fluid configuration and then reduces the resulting mask. This method is not ideal and is included for comparison purposes.