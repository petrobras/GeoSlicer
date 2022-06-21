## Instance Segmenter Editor

_GeoSlicer_ module to visualize and edit the instance segmenter results.

### Visualize

1. Set the image log and the segmentation labelmap (generated from the _Image Log Instance Segmenter_) in the views of the _Image Log Environment_.

2. Select the corresponding _Report table_, also generated from the _Image Log Instance Segmenter_.

3. The detected instances can be inspected by clicking in any of the rows on the _Parameters_ table. The selected instance will be centered in the views.

4. The detected instances can also be filtered by some properties by moving the sliders in the _Parameters_ section. This will help to chose which instances are good candidates.

### Edit

1. Open the _Edit_ section to add, edit or delete instances.

2. To edit, select an instance from the table and click _Edit_. A crosshair cursor will apper when you move the mouse over the views. Click to paint an instance on the image log (you can also set the _Brush size_). When finished, click _Apply_.

3. To delete an instance, simply select one from the table and click _Decline_ and confirm.

4. When finished editing, you can click _Apply_, at the bottom of the module, to generate another report table with the modifications with the chosen _Output prefix_. Clicking _Cancel_ will revert all the modifications on the current report table.