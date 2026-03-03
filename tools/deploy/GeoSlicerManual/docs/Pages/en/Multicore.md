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

## Common Problems

### "Could not detect core geometry"

The error "Could not detect core geometry" occurs in the `Multicore` module when the `CoreGeometryCLI` command-line interface fails to detect any valid core geometry in the provided volume. This happens because the CLI is unable to find circular features (representing the core) in the volume slices using image processing techniques.

Primary reasons this error can occur:

### 1. **No Detectable Core Circles in the Volume**
   - The volume image does not contain a clear, cylindrical core structure that can be identified via Hough circle detection.
   - Possible causes:
     - The core is obscured, damaged, or has irregular geometry that doesn't form detectable circles in cross-sections.
     - Low image quality, noise, or artifacts prevent edge detection from working properly.

### 2. **Incorrect Core Radius Parameter**
   - The `coreRadius` value passed to the CLI is inaccurate, causing the search radius range (min/max) to not match the actual core size in the image.
   - The search radius is calculated as `[coreRadius - 3mm, coreRadius + 3mm]` in pixels. If the real core radius is outside this range, no circles will be detected.
   - Users should verify the core radius matches the physical dimensions of the sample by loading the original volume and measuring the radius.

### 3. **Insufficient Valid Slices for Analysis**
   - The CLI discards 20 slices from each end of the volume to avoid "destroyed core ends," then samples every 5th slice.
   - If the volume has very few slices (e.g., <40 total), there may be no slices left to analyze after discarding ends.
   - If all sampled slices fail the geometry detection (e.g., due to poor image quality in those slices), the result list remains empty.

### 4. **Circle Detection Filtering**
   - Detected circles are filtered out if their center is too close to the image center (within 10% of the minimum image dimension from the center). This is to avoid false positives from central artifacts.
   - If all detected circles are filtered out by this condition, no valid geometry is recorded.


### Troubleshooting Steps for Users
- **Verify Input Data**: Ensure the volume is a valid core image with clear circular cross-sections. Check volume dimensions and spacing.
- **Adjust Core Radius**: Provide an accurate core radius in meters. If unsure, try a range of values.
- **Check Volume Quality**: Load only the original core image to confirm the core is visible and not obscured.

If the error persists, the volume may not be suitable for automated core geometry detection, and manual intervention or alternative modules might be needed.