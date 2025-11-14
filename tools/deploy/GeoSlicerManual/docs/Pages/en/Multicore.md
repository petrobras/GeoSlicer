# Multicore

_GeoSlicer_ module for processing, orienting, and unwrapping cores in batches.
A [demonstration video](https://youtu.be/JBkeHx6obTY) of an earlier version of _GeoSlicer_ is available.

## Panels and their usage

| ![Figura 1](../../assets/images/Multicore.png) |
|:-----------------------------------------------:|
| Figure 1: Multicore Module. |

### Data selection

- _Add directories_: Adds directories containing _core_ data. These directories will appear in the _Data to be processed_ list. During execution, data search will occur only one level down.

- _Remove_: Removes directories from the search list.

- _Depth control_: Choose the method to configure _core_ boundaries:
    - _Initial depth and core length_:
        - _Initial depth (m)_: Depth of the top of the _core_.
        - _Core length (cm)_: Length of the _core_.
    - _Core boundaries CSV file_:
        - _Core depth file_: Selector for a CSV file containing _core_ boundaries in meters. The file must have two columns, with each row corresponding to a different _core_, in processing order. The columns should indicate, respectively, the upper and lower depth boundaries.

- _Core diameter (inch)_: Approximate _core_ diameter in millimeters.

### Processing
Check the option you wish to execute:

- _Core radial correction_: Corrects attenuation effects of _core CT_, such as _beam hardening_. Applies a correction factor to all image slices (transverse images, xy plane) to standardize attenuation in terms of radial coordinates. The correction factor is calculated based on the average of all slices and depends only on the radial distance from the center of the slices.

- _Smooth core surface_: Applies smoothing (_anti-aliasing_) to the _core_ surface.

- _Keep original volumes_: Saves the original data without corrections and without smoothing.

- _Process cores_: Processes the cores in the directories in the order they were added. Once loaded, the data can be viewed in the _Explorer_ module.

### Orientation
- _Orientation algorithm_: Choose a _core_ orientation algorithm:
    - _Surface_: Orientation is based on the longitudinal cutting angle of the _core_ ends. This option is better in cases where the cutting angle is not shallow and if the ends are well preserved (cleaner cutting surfaces).
        
    - _Sinusoid_: Uses _core_ unwrapping to find the sinusoidal patterns created by depositional layers to orient the _cores_. This option is good if the depositional layers are well pronounced in the _core_ group.
        
    - _Surface + Sinusoid_: If the _Surface_ algorithm is able to find an alignment, it will be used; otherwise, the _Sinusoid_ algorithm will be applied instead.
   
- _Orient cores_: Applies rotation along the longitudinal axis of the _core_, according to the selected algorithm. The first _core_ determines the orientation of subsequent ones.

### Unwrap
- _Unwrap radial depth (mm)_: Enter a value ranging from 0 up to the _core_ radius, in millimeters. From the outside of the _core_ to the center, along the radial axis, this is the depth at which the unwrap will be generated. Use small values if you want to unwrap close to the _core_ surface.

- _Well diameter_: Enter the approximate well diameter (greater than the _core_ diameter) which will be used to project the core image onto the well wall.

- _Unwrap cores_: Generates the unwrapped images of the _core_ and the well. The images preserve the _core_ scale along all axes. Thus, pixel size and _upscaling_ do not depend on the _core_ radius. The delta angle used in the iterative process of collecting unwrapped _voxels_ is defined as pixel_size/radius.

### Apply all
Applies all processing, orientation, and unwrapping steps.