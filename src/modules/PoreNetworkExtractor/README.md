# Pore Network Extraction

Generates a Pore-throat Network (PN) representation of a labeled volume. The extracted network only includes pore clusters that touch at least one of the volume faces.

__Available extracion methods__

* PoreSpy
* PNExtract

## Interface

### Input

1. __Input Label Volume__: Choose a Label Map Node. For the PoreSpy extraction, the Label Map must have an unique label for each pore in the volume (as obtained with watershed). For PNExtract, labels must be "1" for pore space and "0" for background. A Label map with label values equal and higher than one can be extracted with PNExtract, all values greater than one will be interpreted as beign "1".

### Setting

1. __Extract Method__: Select which extraction method will be employed.
	Porespy - Uses de PMEAL Porespy library to extract the pore network from a labeled volume
	PNExtract (Dev mode only) - Uses the Imperial College PNExtract application to extract the pore network from a binary volume

### Output

1. __Pore Output Table__: Table node to store pore information.
1. __Throat Output Table__: Table node to store throat information.

