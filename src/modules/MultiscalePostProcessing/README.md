# Multiscale Post Processing

This module provides _GeoSlicer_ an interface for generating extra tables related to multiscale.

## Methods

1. __porosity per realization__: Create a table of porosity per slice for each relialization in a volume sequence. 
2. __Pore size distribution__: Recalculate the pore size distribution to frequency.

### porosity per realization
#### Inputs
1. __Realization Volume__: Selected volume node that the table will be based on. If the node is a proxy for a sequence node (4D), the porosity will be calculated for all realizations

2. __Training Image__: If a volume is selected, the porosity will be calculated and added to the table as reference. Node that it must have the same dimensions and size of the selected volume in the previous option. 

#### Parameters
1. __Pore segment value__: Value that will be used to find pores in the selected volumes. This option is for scalar volumes.
2. __Pore segment__: Segments that will be considered as pores for the porosity. This option is for labelmap volumes.

### Pore size distribution
#### Inputs
1. __PSD Sequence Table__: Table sequence from the Microtom module in the Simulation Tab.
2. __PSD TI Table__: Same as above, but for the training image.


## Outputs
1. __Output prefix__: Name of the table that will be created.