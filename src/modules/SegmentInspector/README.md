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
13. __eccentricity__:	sqrt(1 - min_feret / max_feret)	related to the equivalent ellipse (0 <= e < 1), iqual 0 for circles.
14. __ellipse_perimeter__: Equivalent ellipse perimeter (equivalent ellipse with axis given by min ans max Feret caliper). Unit: mm.
15. __ellipse_area__: Equivalent ellipse area (equivalent ellipse with axis given by min ans max Feret caliper). Unit: mm^2.
16. __ellipse_perimeter_over_ellipse_area__: Equivalent ellipse perimeter divided by its area.
17. __perimeter__: Real perimeter of the partition (pore/grain). Unit: mm.
18. __perimeter_over_area__: Real perimeter divided by area of the partition (pore/grain).
19. __gamma__: Roundness of an area calculated as 'gamma = perimeter / (2 * sqrt(PI * area))'.
20. __pore_size_class__: Pore class Symbol/code/id.
21. __pore_size_class_label__: Pore class label.

#### Definition of the pore classes:

* __Microporo__: class = 0, max_feret lower than 0.062 mm.
* __Mesoporo mto pequeno__: class = 1, max_feret between 0.062 and 0.125 mm.
* __Mesoporo pequeno__: class = 2, max_feret between 0.125 and 0.25 mm.
* __Mesoporo médio__: class = 3, max_feret between 0.25 and 0.5 mm.
* __Mesoporo grande__: class = 4, max_feret between 0.5 and 1 mm.
* __Mesoporo muito grande__: class = 5, max_feret between 1 and 4 mm.
* __Megaporo pequeno__: class = 6, max_feret between 4 and 32 mm.
* __Megaporo grande__: class = 7, max_feret higher than 32mm.







