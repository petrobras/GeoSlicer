## Spiral filter

_GeoSlicer_ module to remove the spiral and eccentricity effect of image log data.

The filtering process is computed based on a band-rejection filter in the 2D Fourier frequencies of the image. The band commonly associated with eccentricity and spiraling is between 4 and 100 meters of vertical wavelengths and 360deg of horizontal wavelength.

The exact minimum and maximum vertical wavelengths can be measured in the data by the user using the ruler tool.

1. Select the _Input image_.

2. Configure the parameters:
   - _Minimum wavelength_: minimum vertical wavelength of the spiraling effect in meters.
   - _Maximum wavelength_: maximum vertical wavelength of the spiraling effect in meters.
   - _Filtering factor_: multiplicative factor of the filter. 0 leads to  no filtering at all. 1 leads to the maximum filtering.
   - _Band spectrum step length_: step length of the filter spectrum band. Higher this values, more smooth the step of the band width.

3. Set the _Output image name_.

4. Click _Apply_.