## Azimuth Shift

The **Azimuth Correction** module applies a rotation to acoustic image profiles (such as UBI) to correct rotational misalignments caused by tool movement in the well.

Acoustic image profiles are unwrapped in 2D, where one dimension is depth and the other is azimuth (0 to 360 degrees). During acquisition, the logging tool can rotate, which distorts the appearance of geological structures.

This module uses an azimuth table to rotate each image line back to its correct orientation, ensuring that geological features are displayed consistently and interpretably.

### How to Use

1.  **Image node:** Select the image profile you want to correct.
2.  **Azimuth Table:** Choose the table that contains the azimuth data. This table should contain a depth column and a column with the azimuth deviation values in degrees.
3.  **Table Column:** Select the specific column in the table that contains the azimuth values to be used for correction.
4.  **Invert Direction (Optional):** Check this box if you want the rotation to be applied counter-clockwise. By default, the rotation is clockwise.
5.  **Output prefix:** Define the name for the corrected image that will be generated.
6.  **Click Apply:** Press the button to start the correction process.

### Output

The result is a new image in the project with the azimuthal correction applied.