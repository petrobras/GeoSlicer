# Export

_GeoSlicer_ module to allow data export, as described bellow:

## Standard

1. Select the items in the data tree to be exported (can be nodes or entire directories).

2. Select the _Export directory_.

3. In the _Data types_ tab, select the data types to be exported.

4. In the _Options_ tabs, select the formats for each data type to be exported.

5. Click the _Export_  button and wait for completion.

## netCDF

1. Select a directory or node in the data tree to be exported.
2. Select the _Export directory_.
3. Click the _Export_  button and wait for completion.

The data directory can hold the name WELL\_SAMPLE\_STATE\_TYPE\_TYPEOFIMAGE\_NX\_NY\_NZ\_RESOLUTION
and save the information on global attributes of the .nc file.


### Further information about export formats

**RAW** - to load this format using the *RAW Loader* module, these necessary parameters need to be set:

 - *Pixel type*: 16 bit unsigned
 - *Endianness*: Little endian
 - *X dimension*, *Y dimension*, *Z dimension*: the data dimensions
