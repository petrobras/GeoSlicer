## Automatic Segmentation

This module provides advanced methods for automatic and supervised segmentation of several image types, such as thin-section and tomography allowing multiple input images.


### Input

1. __Annotations__: Select the segmentation node that contains the annotations made on the image to train the chosen segmentation method.
2. __Region (SOI)__: Select a segmentation node where the first segment delimits the region of interest where the segmentation will be performed.
3. __Input image__: Select the image to be segmented. Several types are accepted, such as RGB images and tomographic images.


### Setting

1. __Method__: Select the algorithm to perform segmentation.
    1. __Random Forest__: Random forests are an ensemble learning method for classification that operates by constructing a multitude of decision trees at training time. The __input__ is a combination of:
        * Quantized input (reduced RGB to a 8-bit value)
        * Raw HSV
        * Multiple Gaussian Kernels (size and number of kernels defined by the parameter __Radius__)
        * If selected, __Variance__ kernels are calculated (Check __Use variation__).
        * If selected, __Sobel__ kernels are calculated (Check __Use contours__).
    2. __Colored K-Means__: A method of vector quantization that aims to partition __n observations__ into __k clusters__ in which each observation belongs to the cluster with the nearest mean (cluster centers or cluster centroid), serving as a prototype of the cluster. Colored here means that the algorithm works on the 3-dimensional color space, specifically HSV.
        * __Seed Initializer__: Algorithm used to choose initial cluster prototypes.
            * __Random__: Choose a random seed from annotations, one for each segment (different segments).
            * __Smooth Centroid__: For each segment, combine all the annotated samples to generate a more general seed.

### Output

1. __Output prefix__: Type a name to be used as prefix for the results object. 
