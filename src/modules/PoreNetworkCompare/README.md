# Pore Network Compare

_GeoSlicer_ module to compare the PNM simulation models to laboratory measured data.

## Input

The input section generates a laboratory based visualization model and saturation plot data, based on the simulation data and laboratory data as inputs.

The simulation data are:
- _Pore table_: the pore table from the extracted network (Extraction module);
- _Throat table_: the throat table from the extracted network (Extraction module);
- _Watershed pore labelmap_: the watershed labelmap, generated from the _Pore labelmap_ (Inspector module);
- _Cycle model_: the 3D two-phase simulation model (Visualization module);

The experimental data are:
- _Pore labelmap_: the pore segmentation from the sample microtomography;
- _Drainage oil labelmaps_: labelmaps representing the time evolution of the drainage stage; 
- _Imbibition oil labelmaps_: labelmaps representing the time evolution of the imbibition stage;

To use this functionality, prepare a scene containing all the above-mentioned data and input them on each field accordingly.
The _Drainage oil labelmaps_ and _Imbibition oil labelmaps_ are selected by the folders containing them.

Click apply to start the generation process. After finishing, it will generate two new 3D models in the same folder as the input _Cycle model_:
- _Real model_: a model with the pore and throat saturations calculated from the laboratory data;
- _Synthetic model_: a model with the same input simulation data, but with saturation steps matching the _Real model_;

## Visualization

The visualization model enables the comparison between two models generated at the _Input_ section.

To use this functionality, select the _Cycle model 1_ and _Cycle model 2_ and click _Compare_.
A screen with the saturation plots and the two models side-by-side will appear.
Move the _Step_ slider above the plots to see the evolution of the drainage and imbibition steps.