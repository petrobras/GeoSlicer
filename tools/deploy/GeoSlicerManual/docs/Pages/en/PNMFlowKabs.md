## Absolute Permeability Simulation (Kabs)

### Single-scale Kabs Simulation

{{ video("pnm_kabs.webm", caption="Video: Workflow for absolute permeability simulation.") }}

The workflow below allows simulating and obtaining an estimate of absolute permeability in a single-scale sample, considering all pores as resolved:

1.  **Load** the volume in which you want to run the simulation;
2.  Perform **Manual Segmentation** using one of the segments to designate the porous region of the rock;
3.  Separate the segments using the **Inspector** tab, thus delimiting the region of each pore;
4.  Use the [**Extraction**](/Volumes/PNM/PNM.md#extractor) tab to obtain the pore and throat network from the generated LabelMap volume;
5.  On the [**Simulation**](/Volumes/PNM/PNM.md#one-phase) tab to run the Kabs simulation;