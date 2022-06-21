# Pore Network Production Prediction

Performs oil production estimation from relative permeability curves using Buckley-Leverett.

## Interface

### Input

1. __Single Krel__: Estimate production from a single Krel result.

1. __Sensitivity test__: Estimate production from multiple Krel results generated with the "Sensitivity test" option selected in the Simulation tab.

2. __Input Krel Table__: Choose a Table Node generated with a Two-Phase simulation.


### Setting

1. __Water viscosity (Pa\*s)__: Select water viscosity for the estimation. Does not need to match viscosity used in the simulation.

2. __Oil viscosity (Pa\*s)__: Select oil viscosity for the estimation. Does not need to match viscosity used in the simulation.

1. __Krel data smoothing (Standard Deviation)__: Applyies a moving window gaussian blur filter on the Krel data.
