## Volume Cropping

{{ video("thin_section_crop.webm", caption="Video: Volume Cropping") }}

The *Crop* module to crop a volume, as described in the steps below:

1.  Select the volume in *Volume to be cropped*.
2.  Adjust the desired position and size of the ROI in the slice views.
3.  Click *Crop* and wait for completion. The cropped volume will appear in the same directory as the original volume.

## Image Tools

{{ video("thin_section_image_tools.webm", caption="Video: Image Tools") }}

The *Image Tools* module allows image manipulation, as described below:

1.  Select the image in *Input image*.
2.  Select the tool in *Tool* and make the desired changes.
3.  Click the *Apply* button to confirm the changes. These changes are not permanent and can be undone by clicking the *Undo* button; they will be discarded if the module is left without saving or if the *Reset* button is clicked (this will revert the image to its last saved state). Changes can be made permanent by clicking the *Save* button (this will alter the image and cannot be undone).

## Registration

{{ video("thin_section_manual_registration.webm", caption="Video: Registration") }}

The *Register* module to register thin section and QEMSCAN images, as described in the steps below:

1.  Click the *Select images to register* button. A dialog window will appear that allows the selection of the fixed image (*Fixed image*) and the moving image (*Moving image*). After selecting the desired images, click the *Apply* button to start the registration.
2.  Add Landmarks (anchor points) to the images by clicking *Add* in the *Landmarks* section. Drag the Landmarks as desired to match the same locations in both images. You can use the various tools in the *Visualization* section and the window/level tool located in the toolbar to assist you with this task.
3.  After completing the placement of the Landmarks, you can click the *Finish registration* button. Transformations will be applied to the moving image to correspond to the fixed image, and the result will be saved as a new transformed image in the same directory as the moving image. You can also cancel the entire registration process by clicking the *Cancel registration* button.