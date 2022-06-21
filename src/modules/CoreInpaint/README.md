# Core Inpaint

This module fills in rock fractures specified by a segment.

![]($README_DIR/Resources/image.jpg)

## How to use

First, create a segmentation where the first segment represents any fractures in the master volume that need to be inpainted. It is safer to make this segmentation slightly larger than necessary. If the area around a fracture is darker, try including it too.

Then select the segmentation in this module, choose an output name and apply.