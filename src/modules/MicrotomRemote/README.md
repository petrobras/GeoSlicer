# MicroTom

This modules allows _GeoSlicer_ users to use algorithms and methods of the library MicroTom, developed by Petrobras.

__Available methods__

* Pore Size Distribution
* Hierarchical Pore Size Distribution
* Mercury Injection capillary Pressure
* Stokes-Kabs Absolute Permeability on the Pore Scale

## Interface

### Input

1. __Segmentation__: Select a labelmap in which the microtom algorithm will be applied. It must be a labelmap, segementation-node is not accepted (any segementation-node can be transformed to a labelmap in the _Data_ tab by left clicking on the node. ).
2. __Region (SOI)__: Select a segmentation-note where the first segment delimits the region of interest where the segmentation will be performed.
3. __Segments__: Select a segment in the list to be used as the pore space of the rock.

### Setting

1. __Select a Simulation__: Select one of the MicroTom algorithm in the list
2. __Store result at__: (optional) The user can define a specific folder to store the files.
3. __Execution Mode__: Local or Remote.
4. __Show (Jobs list)__: By clicking on "Show", the user can see a list of process sent to the remote cluster.