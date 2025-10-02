## Polynomial Shading Correction

_GeoSlicer_ module to apply shading correction on micro CT images. For a more detailed discussion about the method, please check the GeoSlicer [manual](https://ltracegeo.github.io/GeoSlicerManual/latest/Volumes/Filter/PolynomialShadingCorrection/PolynomialShadingCorrection.html).

To use this module, follow the steps bellow:

1. Select the _Input image_, the _Input mask_ and the _Input shading mask_.

2. Set the _Slice group size_ parameter, an odd number. This parameter will cause the polynomial function to be fitted for the central slice in the group of slices. All the other slices of the group will use the same fitted function. It speeds up the shading correction process, but returns worse results. For maximum resolution, set this value to 1 (slowest).

3. Set the _Number of fitting points_. A larger value will result in a finer shading correction, but at cost of a longer the process time.

4. Click _Apply_ and wait for the completion.