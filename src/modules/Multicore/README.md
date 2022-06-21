# Multicore

_GeoSlicer_ module to process, orient and unwrap cores in batches.

Demo (old version): [https://youtu.be/JBkeHx6obTY](https://youtu.be/JBkeHx6obTY)

Follow the steps bellow to process some core data, orient the cores and unwrap them. You can also export results.

Decimal numbers use a dot as a separator, not comma.

### Process

1. Use the _Add directories_ button to add directories containing core data. These directories will appear at the _Data to be processed_ area (when processing, a search for core data in these directories will occur at one subdirectory level down at most). You can also remove unwanted entries by selecting them and clicking _Remove_.

2. Choose one of the ways to input the core boundaries: _Initial depth and core length_ or _Core boundaries CSV file_. For _Initial depth and core length_, input the _Initial depth_ and the _Core length_. For _Core boundaries CSV file_, use the _..._ button to add the CSV file containing the core boundaries (in meters). An example CSV file for two cores would be:

   5000.00,  5000.90

   5000.90,  5001.80

   The CSV is a two column file where each line refers to a core (in the processing order, see item 7), and the columns refer to the core upper and lower bound depths, sequentially.
   
3. For _Core diameter_, enter the approximate core diameter (in millimeters).

4. For _Core radial correction_, check it if you want to correct core transversal CT attenuation effects. Can be used to correct effects such as beam hardening. The objective is to multiply a correction factor to all the slices of the image (transversal slices, plane xy) to uniform the attenuation values in terms of the radial coordination. The correction factor is computed based on the average of all the slices and it depends on only the radius related to the center of the slices.

5. For _Smooth core surface_, check it if you plan to analise the core surface; it will be smoother (antialiased) with this option on.

6. For _Keep original volumes_, check it if you wish to keep the original loaded data.

7. Click the _Process cores_ button and wait for completion. The processing order is as follows: the order of the added directories in the _Data to be loaded_ area, and each subdirectory, if applicable, is processed in alphabetical order. You can inspect the loaded cores in the _Data_ tab of the _Core Environtment_, under the _Core_ directory.

#### Alignment and core extraction details

In the slices of the original core data, one can frequently spot three circles, which are (from the largest to the smallest): the outer surface of the liner, the inner surface of the liner and the surface of the core. The Circle Hough Transform is used to detect these circles, and then the smallest one is picked as representing the core surface, with information about its radius and position. We use the circle position from the slices to fit the best line that passes through the core center (longitudinal axis), using SVD (Singular Value Decomposition). This allows us to build a unit vector that must be rotated to the Z axis by applying a transformation (rotation) matrix. Once calculated, this rotation matrix is then applied to the data. A translation matrix is also used to move the core center to the origin of the coordinate system, and later on, to its configured depth on the Z axis.

After the alignment is made, all the points outside a cylinder surrounding the core are set to the lowest intensity value of the original data. The radius of this cylinder is equal to the mean radius of the detected core circles in the slices.

### Orient

1. Select the _Orientation algorithm_:
   
   - _Surface_ - the orientation is based on the saw cut angle at the core longitudinal ends. This option works best if the cut angle is not too shallow, and the core ends are well-preserved (i.e. cleaner cut surfaces).
     
   - _Sinusoid_ - uses the core unwrap to find the sinusoid patterns created by the depositional layers to orient. This option is good if the depositional layers are well pronounced in the cores batch.
     
   - _Surface + Sinusoid_ - If _Surface_ algorithm was capable of finding an alignment, it will be used, otherwise, _Sinusoid_ algorithm is applied instead.
   
2. Click _Orient cores_ button and wait for completion. The cores will be rotated along their longitudinal axis, according to the selected orientation algorithm. The first core (the smallest depth) dictates the orientation of the subsequent ones.

### Unwrap

1. For _Unwrap radial depth_, enter a value ranging from 0 to the core radius, in millimeters. From outside the core to the center, along the radial axis, it is the depth at which the unwrap will be generated. Use small values if you want unwraps near the core surface.

2. For _Well diameter_, enter the approximate well diameter value (high than the core dimater) that will be used to project the image of the core to the wall of the well

3. Click _Unwrap cores_ and wait for completion. The individual core unwraps and the global well unwrap will be generated. The unwrap images preseve the original scaling of the core in all axis. 
Therefore, the pixel size/upscaling does not depend on the core radius, i.e. the delta angle used in the iterative process of colecting the unwrap voxels are defined as pixel_size/radius.

You can also perform all the steps above by clicking the _Apply all_ button.

### Export

If you want, you can export the _Multicore_ summary, the core middle slices in each axis, and the core unwraps, by clicking at their respective buttons within the Export tab. This tab export a two column CSV file, where the first one is the depths and the second one is the CT intensities of the image. This format can be directly imported in the software Techlog.

Another way to export the images in using the Export module of GeoSlicer. We suggest to use the .nc file because both the image, the spacing/pixel size and the initial depth are exported. 