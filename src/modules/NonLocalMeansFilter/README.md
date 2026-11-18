# Non-Local Means Filter

_GeoSlicer_ module to denoise images with the non-local means filter, preserving edges and fine textures, as described in the steps below:

1. Select the _Input image_ to be filtered.

2. Choose the _Mode_: _3D_ filters the full volume, _2D (slice by slice)_ filters each axial slice independently.

3. Adjust the _Strength_, as a multiple of the noise standard deviation. Recommended values are about 0.45-0.6 for 3D and 0.6-0.8 for 2D.

4. Keep _Estimate_ checked to estimate the noise standard deviation from the image, or uncheck it and type a known value.

5. Optionally adjust the _Patch size_, _Search distance_ and _Fast mode_.

6. Type the _Output image name_, click the _Apply_ button and wait for completion. The filtered image will be located in the same directory as the _Input image_.
