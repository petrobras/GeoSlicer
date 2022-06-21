# Micro CT Loader

_GeoSlicer_ module to load micro CT images in batches, as described in the steps bellow:

1. Use the _Add directories_ button to add directories containing micro CT data (currently, the allowed file extensions are: tif, png and jpg). These directories will appear at the _Data to be loaded_ area (a search for micro CT data in these directories will occur at one subdirectory level down at most). You can also remove unwanted entries by selecting them and clicking _Remove_.

2. Set the _Pixel size_ (in millimeters).

3. Click the _Load micro CTs_ button and wait for completion. The loaded images can be accessed from the _Data_ tab, under the _Micro CT_ directory.

## Raw Loader

_GeoSlicer_ module to load images stored in an unknown file format by allowing quickly trying various voxel types and image sizes, as described in the steps bellow:

1. Select the _Input file_.
   
2. Try to guess image parameters based on any information available about the image.
   
3. Click _Load_ to see preview of the image that can be loaded.
   
4. Experiment with image parameters (click the checkbox on _Load_ button to automatically update output volume when any parameter is changed).

5. Move _X dimension_ slider until straight image columns appear (if image columns are slightly skewed then it means the value is close to the correct value), try with different endianness and pixel type values if no _X dimension_ value seems to make sense.

6. Move _Header size_ until the first row of the image appears on top.

7. If loading a 3D volume: set _Z dimension_ slider to a few ten slices to make it easier to see when _Y dimension_ value is correct.

8. Move _Y dimension_ slider until last row of the image appears at the bottom.

9. If loading a 3D volume: Move _Z dimension_ slider until all the slices of the image are included.

10. When the correct combination of parameters is found then either save the current output volume or click _Generate NRRD header_ to create a header file that can be loaded directly into Slicer.

## Further information about export formats

**RAW** - to load this format exported by the *Export* module, these necessary parameters need to be set:

 - *Endianness*: Little endian
 - *X dimension*, *Y dimension*, *Z dimension*: the data dimensions


 - For scalar volumes and images:

     - *Pixel type*: 16 bit unsigned
    

 - For label maps and segmentations:

     - *Pixel type*: 8 bit unsigned
