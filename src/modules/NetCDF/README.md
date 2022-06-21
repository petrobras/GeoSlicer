# NetCDF

Import and export images to NetCDF format.
Files follow xarray conventions with coordinate arrays.
Dimensions are 'x', 'y', 'z' and optionally 'c' for color channels.
Segmentations have a 'labels' attribute which describes segment names, labels and colors; and also a 'reference' attribute with the name of the reference image.
