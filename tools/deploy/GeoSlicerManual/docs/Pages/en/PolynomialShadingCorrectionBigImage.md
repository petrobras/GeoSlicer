## Polynomial Shading Correction

The **Polynomial Shading Correction (Big Image)** module is designed to correct shading artifacts or irregular illumination in large-volume images that cannot be entirely loaded into memory. It works by fitting a polynomial to the image background and normalizing the illumination, similar to the [Polynomial Shading Correction](/Volumes/Filter/Filter.md#polynomial-shading-correction) filter, but with optimizations for out-of-core processing.

This module operates on NetCDF (`.nc`) files and saves the result to a new file, making it ideal for massive data processing pipelines.

### Operating Principle

This module adapts the polynomial shading correction algorithm for images that exceed RAM capacity. The main differences and optimizations are:

1.  **Block Processing (Out-of-Core):** The image is divided and processed in blocks (chunks), ensuring that only a portion of the volume is loaded into memory at any given time.
2.  **Point Sampling:** To fit the polynomial in each slice, instead of using all pixels from the shading mask, the module randomly selects a defined number of points (`Number of fitting points`). This drastically speeds up the fitting calculation without significantly compromising the accuracy of the shading correction.
3.  **Slice Grouping:** To further optimize the process, the polynomial fit is calculated on the central slice of a group of slices (`Slice group size`). The resulting correction function is then applied to all slices within that group.

For a detailed description of the base shading correction algorithm, please refer to the [Polynomial Shading Correction](/Volumes/Filter/Filter.md#polynomial-shading-correction) filter manual.

### Parameters

-   **Input image:** The large-volume image (in NetCDF format) to be corrected.
-   **Input mask:** A mask that defines the region of interest. The area outside this mask will be zeroed in the output image.
-   **Input shading mask:** The mask indicating background areas (or areas with uniform intensity) to be used for point sampling and polynomial fitting.
-   **Slice group size:** Defines the number of slices in a group. The correction is calculated on the central slice and applied to the entire group. A larger value speeds up the process but may not capture rapid shading variations along the slice axis.
-   **Number of fitting points:** The number of points to be randomly sampled from the `Input shading mask` to perform the polynomial fitting.
-   **Output Path:** The path to the output file in NetCDF (`.nc`) format where the corrected image will be saved.

### Use Cases

This module is ideal for:

-   Preprocessing high-resolution, large-scale micro-computed tomographies (µCT).
-   Correcting illumination in image mosaics or any voluminous image that does not fit in memory.
-   Normalizing illumination gradients in large datasets before segmentation or quantitative analysis.
