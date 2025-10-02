## Image Log Instance Segmenter

_GeoSlicer_ module to apply instance segmentation for image logs, as described in the steps bellow. For a more detailed description on the methods, please check the GeoSlicer [manual](https://ltracegeo.github.io/GeoSlicerManual/latest/ImageLog/Segmentation/InstanceSegmenter/InstanceSegmenter.html).

1. Select the model, which determines the type of artifact to be detected.

2. Select the necessary images:

- Sidewall sample models: select the _Amplitude image_ and the _Transit time image_.
- Stops models: select the _Transit time image_.

3. Set the parameters:

- Sidewall sample models: select the _Nominal depths file_ (not required).
- Stops models: set the _Threshold_, _Size_ and _Sigma_ parameters.

4. Set the _Output prefix_ (automatically suggested when you select the input images).

5. Click the _Segment_ button and wait for completion.