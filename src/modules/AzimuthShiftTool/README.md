# Azimuth Shift Tool
This module provides _GeoSlicer_ an interface to correct the orientation of the Acoustic Image Log with the Azimuth profile

## Methods
The developed method corrects the position of the pixel present in the image by rotating and interpolating the data according to the angles provided by the well profile.

## Inputs
1. __Image Node__: Acoustic Image Log volume to be corrected.
2. __Azimuth Table__: Table with the azimuth shifts to be used in the correcting
3. __Table Column__: Column of the selected table with the azimuths shifts.

## Parameters
1. __Reverse direction__: If checked, the image will be corrected by rotating anti-clockwise instead of clockwise.

## Outputs
1. __Output prefix__: Name of the volumes that will be created with the results.