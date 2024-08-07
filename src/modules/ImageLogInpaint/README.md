# Image Log Inpaint

_GeoSlicer_ module to interactively inpaint image logs.

## Usage


1. Select the input image log volume.
    * To keep the original image unchanged, create a new volume by clicking **`Clone Volume`**. This will create another volume with the same content of the selected one.
1. Select the **`scissors`** effect.
1. There will be two views:
    * **The first view** is where the user will draw areas for inpainting.
    * **The second view** is only for preview. It will show all the drawn areas inpainted so far.
        * Click the eye button to show/hide the image log.
        * All the drawn areas will be saved in a segmentation volume.
1. Click the **`arrow back`** or **`arrow forward`** buttons to undo or redo an inpaint modification.