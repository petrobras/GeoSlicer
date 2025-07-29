# CLAHE Tool
This module applies the Contrast Limit Adaptive Histogram Equalization (CLAHE)

## Methods
"an algorithm for local contrast enhancement, that uses histograms computed over different tile regions of the image. Local details can therefore be enhanced even in regions that are darker or lighter than most of the image." - scikit-image equalize_adapthist documentation

## Inputs
1. __Image Node__: Image Log volume to be processed.

## Parameters
1. __Kernel Size__: "Defines the shape of contextual regions used in the algorithm. By default, kernel_size is 1/8 of image height by 1/8 of its width."
2. __Clip Limit__: "Clipping limit, normalized between 0 and 1 (higher values give more contrast)."
3. __Number of Bins__: "Number of bins for histogram ('data range')."
## Outputs
1. __Output prefix__: Equalized image with float64 dtype.