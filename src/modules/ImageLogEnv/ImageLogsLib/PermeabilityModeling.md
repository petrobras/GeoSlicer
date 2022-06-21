## Permeability Modeling

The modeling module is based on the reference Menezes de Jesus, C., Compan, A. L. M. and Surmas, R., Permeability Estimation Using Ultrasonic Borehole Image Logs in Dual-Porosity Carbonate Reservoirs, 2016.

It is a method for permeability modeling using a segmented image log and a porosity log. The total porosity is weighted by fractions of each of the input segmented classes extracted from the image logs.
The permeability is defined by

K = (A1 * F1* Phi ^B1) + (A2 * F2* Phi ^B2) + ... +  (An * Fn* Phi ^Bn)  +  (Am * Fm* Phi),

where A and B are the equations parameters, F are the fractions of the n segment classes and m is the macro pore segment.

1. Depth Log: Select depth log of the LAS file related to the porosity log.
2. Porosity Log: Select porosity log imported from the LAS file.
3. Depth Image: Select depth related to the segmented image log.
4. Segmented Image: Select the segmented image log.
5. Macro Pore Segment class: Select the segment class related to the macro pore segment
6. Ignored class:Select the segment class related to the null class. This class will be ignored in the fraction calculation. 
7. Plugs Depth Log: Select the depth of the plug measurements 
8. Plugs Permeability Log:Select the permeability measurements of the plugs