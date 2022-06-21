## Quality Indicator

_GeoSlicer_ module to indicate the quality of the image log data in terms of level of eccentricity and spiraling effects.

The output is an image where values close to one indicates a high level of eccentricity and spiraling, whereas values close to zeros one indicates a low level.

The indicator is computed based on the 2D Fourier transform of the image. Its values are defined by the average amplitude spectrum of the band commonly associated with eccentricity and spiraling (vertical wavelengths between 4 and 100 meters and horizontal wavelength of 360deg).

1. Select the _Input volume_.

2. Configure the parameters:
   - _Window size_: size of the moving window in meters used to compute de indicator.
   - _Minimum wavelength_: minimum vertical wavelength of the spiraling effect in meters.
   - _Maximum wavelength_: maximum vertical wavelength of the spiraling effect in meters.
   - _Filtering factor_: multiplicative factor of the filter. 0 leads to  no filtering at all. 1 leads to the maximum filtering.
   - _Band spectrum step length_: step length of the filter spectrum band. Higher this values, more smooth the step of the band width.

4. Set the _Output volume name_.

5. Click _Apply_.