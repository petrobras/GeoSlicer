# Image Metrics

Measures micro-CT image quality from the segments of one segmentation: SNR, CNR, cupping and the edge-based MTF (ESF → LSF → FFT, resolvable distance at 50% and 10%, LSF FWHM). Every run appends a row to the `Image Quality Metrics` table, which can be exported as CSV.

- The numerical code is in `src/commons/commons/lmath/image_quality.py` (numpy/scipy only) and is covered by `tests/unit/commons/lmath/test_image_quality.py` (the module logic is in `tests/unit/modules/ImageQualityMetrics/test_logic.py`).
- One segmentation with a segment per material feeds every metric. Each metric has its own segment selectors: any number of segments for the SNR (one value each), two phases for the CNR, the whole sample (all segments, the default) or a single segment for the cupping and the two sides of an edge for the MTF. A metric that fails is reported without stopping the others.
- The MTF locates the interface as a sub-voxel contour of the smoothed side A on evenly spaced axial slices, so it works best for interfaces roughly perpendicular to the slices (a tube wall). Memory use does not grow with the volume: SNR/CNR are accumulated block by block and the radial profile and edge are processed one slice at a time.
- User documentation: `tools/deploy/GeoSlicerManual/docs/Pages/{en,pt}/ImageQualityMetrics.md`.
