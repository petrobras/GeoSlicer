# Segmentation Modelling

Generates a Porosity map representation of a volume. The values of a porosity map are represented as pore (1) and solid (0).

__Available methods__

* Porosity Map from Segmentation 
* Permeability Map
* Porosity Map from Saturated Image

## Interface

### Inputs

1. __Porosity Map from Segmentation__: Segmentation Node

. __Permeability Map__: For each segment in the segmentation, users can provide a mathematical equation that defines how permeability should be calculated for that specific region.

3. __Porosity Map from Saturated Image__: One dry image Node and a saturated image Node


### Setting

1. __Porosity Map from Segmentation__: Choose a Segmentation Node and classify microporosity, macroporosity, and reference solid segments. You can run quality control to fine-tune the pore attenuation factor and solid attenuation factor. Finally, use the 'Compute' button to preview the total porosity before running the method and creating a porosity map node.

2. __Permeability Map__: Select a Segmentation Node and define a formula for each segment within the segmentation node.

3. __Porosity Map from Saturated Image__: Select a dry image Node and a saturated image Node. You can perform quality control to fine-tune the air attenuation factor (outside the water-immersed acquisition container) and solid attenuation factor (solid 'calcite') for each image (dry and saturated). Finally, use the 'Compute' button to preview the total porosity before executing the method and creating a porosity map node.

### Output

1. __Porosity Map Volume__: scalar node to show porosity map information.
1. __Variables Table__: Table node to store porosity map information.

