## Thin Section Auto Registration

_GeoSlicer_ module to automatically register thin section images, as described in the steps bellow:

1. Select the _Fixed segmentation_ and the _Moving segmentation_. Transformations will be applied to the moving node to match the fixed node, and the result will be saved in a transform node.

2. Select the segments that will be considered in the registration process, for both the _Fixed segmentation_ and the _Moving segmentation_.

3. Set the _Translation scale_. It determines how much to scale up changes in position compared to unit rotational changes in radians. Decrease this to put more rotation in the search pattern.

4. Click the _Register_ button and wait for completion. A transform node will be created and is applied to the moving segmentation.