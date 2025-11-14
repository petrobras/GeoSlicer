## Segmenter

*Segmenter* module for automatically segmenting an image, as described in the steps below:

1.  Go to the *Smart-seg* segmentation section of the environment.
2.  Select the *Pre-trained models*.
3.  The *Carbonate Multiphase(Unet)* model was used as an example.
4.  Check Model inputs and outputs.
5.  Select a previously created SOI (*Segment of interest*) for the *Region SOI* parameter.
6.  Select a PP (*Plane polarized light*) image for the *PP* parameter.
7.  Select a PX (*Crossed polarized light*) image for the *PX* parameter.
8.  A prefix for the resulting segmentation name is generated, but this can be modified in the *Output Prefix* area.
9.  Click *Apply* and wait for it to finish. A segmentation node will appear, and its visualization can be changed in the Explorer.

{{ video("thin_section_smart_seg.webm", caption="Video: Automatic segmentation with pre-trained model") }}