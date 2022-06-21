# LTrace Library

Contains codes that are agnostic to GeoSlicer and permeate several modules.

## Structure

The library is divided into the following parts:

* __algorithms/__, contains all code related to advanced calculations and functionalities provived to modules. For example, segmentation workflows, measurements, neural network models, classification algoritms and so on.
* __assets/__, stores all kind of data/state necessary to be kept together with code, like trained neural network models.
* __cli_progrss/__, deprecated and will be removed in future releases.
* __image/__, specialized feature workflows for image processing.
* __lmath/__, holds common math helpers.
* __slicer/__, provides customized widgets, slicer utility improvements and matplotlib integration.
* __constants__, easy access to constant values.
* __generators__, sample generators, like sliding windows on 2d and 3d.
* __slicer_utils__, wrapper classes for GeoSlicer module.
* __tranforms__, data transformation functions.
* __units__, units helpers

