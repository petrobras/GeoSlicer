# Pore Size Distribution Along Depths (PSDPerDepth)

_GeoSlicer_ module that takes a pore size distribution image and calculates a series of stacked histograms of pore size distribution for consecutive intervals of depth.

## Interface

### Input

1. __Input PSD image__: Select the pore size distribution volume (much likely an output of the ImageLogPSD module) used as input.
2. __Depth intervals (m)__: The depth thickness over which each histogram will be computed. For example, If an input image has 10m and Depth Intervals was set to 2m, the calculation will result in 5 histograms - the first covering 0-1m, the second 2-3m, ..., till 8-9m.
3. __Number of histogram bins__: This controls the horizontal resolution of the histograms. The more bins, the higher the resolution. The horizontal axis represents the pore sizes in mm.
4. __Log X axis__: Toggles the histograms between linear and logarithmic horizontal scale
5. __Presets__: Different combination of parameters (depth intervals, number of bins, horizontal scale) can be saved and loaded as presets