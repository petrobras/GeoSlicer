# Modules

GeoSlicer is a modular application, meaning each specific function added to the _software_ is implemented through a new
module.
This allows GeoSlicer to be easily expanded and customized to meet different project needs. Users can even develop their own modules and integrate them into GeoSlicer.

### Design

GeoSlicer modules are developed following certain design patterns, which aim to establish a cohesive and
intuitive interface regardless of the module. Next, we will discuss these patterns and how they impact user experience.

### Inputs / Configuration / Output

The vast majority of modules are structured into three parts: inputs, configuration, and output. Inputs are the data that
the module needs to run the task it implements. Configuration refers to the parameters that the user can adjust to
customize the execution.
And the output is the result of the module's execution, usually only requiring a suffix for the name of the resulting node/data.

### Flows

The most repetitive and common workflows are implemented in the form of flows (_flows_). A flow is a specific sequence
of pre-configured modules that, when executed step-by-step, implement a workflow. GeoSlicer already has some flows implemented:

- Thin Sections:
    - **Segmentation Flow**: Flows implemented for PP, PP/PX, and QEMSCAN. They perform the complete analysis flow of the sections with segmentation, partitioning, and quantification of the images.
- Micro CT:
    - **Permeability Modeling Flow**: This flow executes all steps up to permeability modeling.
    - **Microporosity Segmentation Flow for Large Images**: This flow executes all steps up to segmentation in large images.

### Custom

Some modules are customized to meet specific project needs. These modules will not always follow the patterns described above, due to some problem specificity or application characteristic. An example is the _Manual Segmentation_ module, which offers a range of tools for manual image segmentation. Being extremely interactive, this module requires its own interface that allows the user to switch between tools easily.