# Multi Scale

This module provides _GeoSlicer_ an interface for the MPSLib Library, a set of algorithms based on a multiple point statistical (MPS) models inferred from a training image.

## Methods
Currently only the Generalized ENESIM algorithm with direct sampling mode (DS) is available

## Inputs
1. __Training Image Volume__: Select a volume node or segmentation node to act as the training image. For the moment, the reference volume node will be used in place of segmentation node itself.

2. __Hard Data__: Select a volume node or segmentation node to act as Hard Data. This define the cells which wont be changed. When selected a list of found values will be shown so that the user can choose the values that will act as hard data.

3. __Generate Preview__: This option is only available if the hard data input is a segmentation or label map. This section allows the user to generate a simplified 3d model of the well cylinder that will be used by the algorithm. 

## Parameters
1. __Final Image Resolution__: Resolution of the voxel of the resulting image in millimeters. Automatically set to the training image data resolution.

2. __Final image dimensions__: Resolution of resulting image (number of voxels in each dimension). Automatically set to the training image data dimensions.

3. __Number of Conditioning points__: Number of conditioning points that will be considered at each iteration. 

4. __Number of realizations__: Number of realizations that will be generated. Set to number of processors available. 

5. __Number of max iterations__: Maximum number of iterations to search through the training image. If less then 0, will scan the whole training image.

6. __Random seed__: Seed that will determine the realizations. A fixed value always results in the same realizations. Use 0 for a random seed. 

7. __Colocate Dimensions__: For a 3D TI make sure the order matters in the last dimensions

8. __Max Search Radius__: Only conditional data within a radius of max search radius is used as conditioning data.

9. __Distance Max__: Maximum distance what will lead to accepting a conditional template match. If set to 0, it will search of a perfect match."

10. __Distance Power__: Set the distace power to weight the conditioning data. Use 0 for no weight. Higher values favors data value of conditional events closer to the center value.

11. __Find Largest Interior Rectangle__: If checked the Training Image will be checked for invalid data and will be cropped to the largest volume without invalid data.

## Outputs

1. __Output prefix__: Name of the volumes and file that will be created. 

2. __Save first realization__: If checked the only the first realization will be saved as a volume.

3. __Save all realizations__: If checked all of the realizations will be saved in _Geoslicer_ as volume.

4. __Save as sequence__: If checked all of the realizations will be saved in a sequence node. This way the data can be visualized with the proxy node and controlled by the browser node.

5. __Save as files (.tif)__: If checked all of the realizations will be save as files in the selected directory.

6. __Export directory__: If save as file is selected, this lets the user select the directory in which the files will be saved.

## Simulation options

1. __Run__: Run sequential version of the algorithm in the main thread of _Geoslicer_.

2. __Run parallel__: Run parallel version of the algorithm through a CLi command as a background task.