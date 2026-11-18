## Segment inspector

For a more detailed discussion about the use of the watershed algorithm, please check the GeoSlicer [manual](https://ltracegeo.github.io/GeoSlicerManual/latest/Volumes/Segmentation/SegmentInspector.html).

This module provides several methods for analyse a segmented image. Particularly, Watershed and Island algorithms allow to fragment a segmentation in several partitions, or several segments. Usually it is applied to pore space segmentation to compute the metrics of each pore element.
The input is a segmentation-node or labelmap volume, a region of interest (defined by a segmentation-node) and the master image/volume. The output is a labelmap where each partitions (pore element) is in a different color, a table with gobal parameters and table with the different metrics for each partition.

### Input

1. __Select__ single-shot (single segmentation) or Batch (multiple samples defined by a multiple GeoSlicer projects).
2. __Segmentation__: Select a segmentation-node or a labelmap to be inspected.
3. __Region__: Select a segmentation-node to define a interest region (Optional).
4. __Image__: Select the master image/volume where the segmentation is related. 

### Setting

1. __Method__: Select a method to be applied. With island algorithm, the segmentation is fragmented according to direct connections. With Watershed, the segmentation is fragmented according to the distance transform and the parameters of the advanced tab.
2. __Size Filter__: Filter spurious partitions with major axis (feret_max) smaller than Size Filter value.
3. __Smooth factor__: Smooth Factor being the standard deviation of the Gaussian filter applied to distance transform. As Smooth Factor increases less partitions will be created. Use small values for more reliable results.
4. __Minimum distance__:  Minimum distance separating peaks in a region of 2 * min_distance + 1 (i.e. peaks are separated by at least min_distance). To find the maximum number of peaks, use min_distance = 0.
5. __Orientation line__: select a line to be used for orientation angle calculation.

### Output

Type a name to be used as prefix for the results object (labelmap where each partitions (pore element) is in a different color, a table with gobal parameters and table with the different metrics for each partition.)

Check __Include segment centroids in the report__ to add the __centroid_z__, __centroid_y__ and __centroid_x__ columns to the metrics table.

For 3D images, check __Include principal axis orientations in the report__ and __Include ellipsoid axis lengths in the report__ to add the principal axes columns described below.

Clicking a row of the metrics table, in the table view or in the Explorer panel, centers and zooms the slice views and the 3D view on that partition.

To go the other way, turn on __Pick segment__ in the mouse mode toolbar and click a partition in a slice view: a tooltip shows its main metrics from the table. Ctrl+click shows the table, in the Explorer panel (or in the table view, for tables over 3000 rows), with the partition's row selected. Choosing another mouse mode turns it off.

### Properties / Metrics:

1. __Label__: label identification of the partition.
2. __mean__: mean value of the input image/volume within the partition (pore/grain) region.
3. __median__: median value of the input image/volume within the partition (pore/grain) region.
4. __stddev__:	Std deviation value of the input image/volume within the partition (pore/grain) region.
5. __voxelCount__: Total number of pixels/voxels of the partition (pore/grain) region.
6. __area__: Total area of the partition (pore/grain). Unit: mm^2.
7. __angle__: Angle in degrees (between 270 and 90) related to the orientation line (optional, if no line is selected, the reference orientation is top horizontal).
8. __max_feret__: Maximum Feret caliper axis. Unit: mm.
9. __min_feret__: Minimum Feret caliper axis. Unit: mm.
10. __mean_feret__: Mean of minimum and maximum caliper.
11. __aspect_ratio__: 	min_feret / max_feret.
12. __elongation__:	max_feret / min_feret.
13. __eccentricity__:	sqrt(1 - (min_feret / max_feret)^2)	related to the equivalent ellipse (0 <= e < 1), iqual 0 for circles.
14. __ellipse_perimeter__: Equivalent ellipse perimeter (equivalent ellipse with axis given by min ans max Feret caliper). Unit: mm.
15. __ellipse_area__: Equivalent ellipse area (equivalent ellipse with axis given by min ans max Feret caliper). Unit: mm^2.
16. __ellipse_perimeter_over_ellipse_area__: Equivalent ellipse perimeter divided by its area.
17. __perimeter__: Real perimeter of the partition (pore/grain). Unit: mm.
18. __perimeter_over_area__: Real perimeter divided by area of the partition (pore/grain).
19. __gamma__: Roundness of an area calculated as 'gamma = perimeter / (2 * sqrt(PI * area))'.
20. __pore_size_class__: Pore class Symbol/code/id.
21. __pore_size_class_label__: Pore class label.
22. __centroid_z__, __centroid_y__, __centroid_x__ (optional): Centroid of the partition, the mean position of its pixels/voxels in world coordinates (z = S, y = A, x = R). Unit: mm.

#### 3D shape properties

For 3D images, the shape properties come from the principal component analysis (PCA) of the partition's voxels. The standard deviations along its major, intermediate and minor axes are σ1 ≥ σ2 ≥ σ3, and the equivalent ellipsoid has semi-axes √5·σ (the ellipsoid with the same second moments).

Each voxel is taken as the box it fills, not as a point at its center: the PCA includes the spread within each voxel, and __max_feret__ is the largest distance between the corners of the partition's voxels. So partitions one voxel thick are measured with that voxel's thickness, and a box of voxels has exactly its side lengths.

* __aspect_ratio__: σ3 / σ1.
* __elongation__: 1 - σ2 / σ1 (Kong & Fonseca). 0 when the two largest axes are equal, approaching 1 for elongated partitions.
* __flatness__: 1 - σ3 / σ2 (Kong & Fonseca). 0 when the two smallest axes are equal, approaching 1 for flat partitions.
* __ellipsoid_area__, __ellipsoid_volume__: Surface area and volume of the equivalent ellipsoid. Units: mm², mm³.
* __major_axis_z__, __major_axis_y__, __major_axis_x__, and the same for __intermediate_axis__ and __minor_axis__ (optional): Direction of each principal axis, as a unit vector in world coordinates (z = S, y = A, x = R). An axis has no direction of its own, so each vector is the one pointing toward +S (z ≥ 0); horizontal axes point toward +A, and axes along x toward +R. When two axes have almost the same length, their directions are poorly defined.
* __major_axis_length__, __intermediate_axis_length__, __minor_axis_length__ (optional): Full length of each axis of the equivalent ellipsoid, 2·√5·σ. Unit: mm.

#### Definition of the pore classes:

* __Microporo__: class = 0, max_feret lower than 0.062 mm.
* __Mesoporo mto pequeno__: class = 1, max_feret between 0.062 and 0.125 mm.
* __Mesoporo pequeno__: class = 2, max_feret between 0.125 and 0.25 mm.
* __Mesoporo médio__: class = 3, max_feret between 0.25 and 0.5 mm.
* __Mesoporo grande__: class = 4, max_feret between 0.5 and 1 mm.
* __Mesoporo muito grande__: class = 5, max_feret between 1 and 4 mm.
* __Megaporo pequeno__: class = 6, max_feret between 4 and 32 mm.
* __Megaporo grande__: class = 7, max_feret higher than 32mm.







