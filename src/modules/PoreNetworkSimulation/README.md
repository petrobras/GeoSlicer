# Pore Network Flow Simulation

Performs one-phase and two-phase flow simulations to obtain absolute and relative permeabilities, respectivelly.

## Interface

### Input

1. __Input Pore Table__: Choose a Pore table node generated on the PN Extraction tab.

### Parameters

1. __Fluids simulation__: Chose either "one-phase" for absolute permeability, "two-phase" for relative permeability or "mercury injection".

#### One-phase

1. __Pore Network model__: Defines the model used to determine pore and throat flow properties.
	- __Valvatne-Blunt__: Assigns circular, triangular or square cross sections to throats depending on their shape factor. Reference: Patzek, T. W., and D. B. Silin (2001), Shape factor and hydraulic conductance in noncircular capillaries I. One-phase creeping flow, J. Colloid Interface Sci., 236, 295–304.

#### Two-phase

##### Sensitivity test
Sensitivity step is run by setting up parameters with multiple values. To set up multiple value inputs, click the "Multi" button next to the value input to enable the start, stop and step inputs. Multi inputs generate "Step" values linearly distributed between "Start" and "Stop" values. If more than one parameter is set with multiple values, simulations are run with all possible combinations of parameters.


##### Fluid properties

Configure fluid properties to be used in the simulation. Attention: these values are independent from the configuration in production preview, and must be set independently in that tab.

- __Water viscosity (cP)__
- __Water density (Kg/m3)__
- __Oil viscosity (cP)__
- __Oil density (Kg/m3)__
- __Interface tension (N/m)__

##### Contact angle options

There are two main contact angle distribution:
1. __Initial contact angle__: Contact angle of pores before oil invasion.
2. __Equilibrium contact angle__: Contact angle of pores after oil invasion.
In addition to the base angle distribution, there is a second distribution for each of them, that allows a parallel set of rules to be applied to the pores. Each pore is assigned to either of the distributions, with the "Fraction" parameter determining how many of the pores will follow the second distribution.

Each angle, primary or secondary, has several parameters that define the distribution. Not all parameters
are available to all distributions.

1. __Model__: Choose the advancing/receding contact angle model for rough surfaces as a function of the intrinsic contact angle. The intrinsic contact angle is the contact angle measured in a smooth surface. Reference: Morrow, N. R. (1975), Effects of surface roughness on contact angle with special reference to petroleum recovery, Journal of Canadian Petroleum Technology, 14, 42-53.
	- __Model 1 (equal angles)__: Advancing and receding contact angles are equal to the intrinsic contact angle.
	- __Model 2 (constant difference)__: Advancing and receding have a constant difference, with advancing angle equal to 0º when the intrinsic angle is 0º and receding angle equal to 180º when the intrinsic angle is 180º.
	- __Model 3 (Morrow curve)__: Assign advancing and receding contact angles from the intrinsic contact angle using the two hysteresis from the Morrow curve.
2. __Contact angle distribution center (degrees)__: Defines the center of the contact angle distribution
3. __Contact angle distribution range (degrees)__: Each distribution will occur between center - range/2 and center + range/2, clipped between 0 and 180 (clipping may displace the distribution center).
4. __Delta__: Defines the delta parameter of the truncated Weibull distribution for the contact angle. If a negative number is chosen, uses a uniform distribution instead.
5. __Gamma__: Defines the gamma parameter of the truncated Weibull distribution for the contact angle. If a negative number is chosen, uses a uniform distribution instead.
6. __Contact angle correlation__: Set if contact angles should correlate with pore radius. "Positive radius" means higher contact angles correlate with larger radii, while "Negative radius" means the opposite.
7. __Separation (Degrees)__: The difference between advancing and receding contact angles if Model 2 is chosen (no effect for models 1 and 3)
8. __Fraction__: A value between 0 and 1, defines the ratio of pores that will have this second contact angle distribution, instead of the first one.
9. __Fraction distribution__: Is the fraction determined by pore quantity or total pore volume.
10. __Correlation diameter__: If "Spatially correlated" is chosen for Fraction correlation, sets the distance more likely to find pores with the same contact angle distribution.
11. __Fraction correlation__: Defines if this second distribution should be spatially correlated, associated with smaller radii, associated with larger radii, or randomly assigned.

##### Simulation options

1. __Minimum SWi__: Enforces SWi, stopping the drainage cycle once this Sw value is reached (SWi may be higher if water becomes trapped).
2. __Final cycle Pc__: Stops the cycle once this capillary pressure is achieved.
3. __Sw step length__: Advance Sw by this value each step of the simulation before checking new permeability value.
4. __Inject from__: Sets which pores the fluid is injected from, across the Z axis of the image. The same side can both inject and produce.
5. __Produce from__: Sets which pores the fluid is produced from, across the Z axis of the image. The same side can both inject and produce.
6. __Pore fill__: Model parameters to determine which mechanism dominates each individual pore filling event.
7. __Lower box boundary__: Pores with relative distance on the Z axis up to this value from the left plane are considered "left" pores.
8. __Upper box boundary__: Pores with relative distance on the Z axis up to this value from the right plane are considered "right" pores.
9. __Subresolution volume__: Considers the volume contains this fraction of subresolution pore space that is always filled with water.
11. __Plot first injection cycle__: If selected, the first cycle, oil injection into a fully water saturated medium will be included in the output plot. The simulation itself will be run whether the option is selected or not.
12. __Create animation node__: Creates an animation node that can be used on the "Cycles Visualization" tab.
13. __Keep temporary files__: Maintains .vtu files in the geoslicer temporary files folder, one file for each step of the simulation.
14. __Max subprocesses__: How many single-thread subprocesses should be run in this simulation. The recommended value for an idle machine is 2/3 of the total amount of cores.

#### Mercury injection

Estimates pore radius distribution with Mercury Injection simulation. Interprets pore.phase as 1 for resolved porosity and 2 for subresolution porosity. 

##### Subscale entry pressure model:

Defines the model used to assign entry pressure for pores with subresolution porosity.

1. __Fixed radius__: All subresolution pores have the same entry pressure relative to the assigned fixed radius.

2. __Leverett Function - Sample Permeability__: Assigns entry pressure based on the J Leverett curve and the permeability of the sample. The J leverett table must have columns "J" for the J value and "Sw" for the water saturation.

3. __Leverett Function - Permeability curve__: Assigns entry pressure based on the J Leverett curve, a permeability model and the chosen method parameters. The J leverett table must have columns "J" for the J value and "Sw" for the water saturation.

4. __Pressure curve__: Assigns entry pressure based on the pressure curve of the sample (such as the one obtained with experimental mercury injection). Entry pressure is assigned in such way that the entry pressure is proportional and has the same distribution as the pore porosity.

##### MICP Visualization:

Allows visualization of the Mercury injection simulation.

### Output

1. __Output prefix__: Name prefix to be used on the result nodes.
