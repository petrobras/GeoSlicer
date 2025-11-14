# MicroTom

The **MicroTom** module integrates the MicroTom simulation library, developed by Petrobras, into *GeoSlicer*. It offers a set of advanced tools for porous media analysis, enabling detailed characterization of petrophysical properties from digital images.

The main available methods are described below:

-   **PNM Complete Workflow**: Executes the complete workflow of the Pore Network Model, from network extraction to property simulation and interactive report generation.
-   **Pore Size Distribution**: Calculates the pore size distribution based on the maximum inscribed spheres method in a binary porous medium. The selected segment is considered the porous space.
-   **Hierarchical Pore Size Distribution**: Analyzes pore distribution in materials with hierarchical structure, which feature interconnected pores at different scales (micropores, mesopores, and macropores).
-   **Mercury Injection Capillary Pressure**: Simulates the mercury injection capillary pressure curve. The calculation is based on the radii of the maximum spheres that fill the binary porous medium and are connected to an inlet face.
-   **Incompressible Drainage Capillary Pressure**: Calculates the capillary pressure curve during the primary drainage process, considering an incompressible wetting fluid. In this method, the irreducible water saturation (Swi) is non-zero, as part of the wetting phase becomes trapped with increasing capillary pressure.
-   **Imbibition Capillary Pressure**: Calculates the capillary pressure curve during the imbibition process. The calculation assumes no trapping of the non-wetting phase (Sor = 0), which is completely displaced as capillary pressure decreases.
-   **Incompressible Imbibition Capillary Pressure**: Simulates the imbibition capillary pressure curve, considering the trapping of the non-wetting phase (Sor ≠ 0) as capillary pressure decreases.
-   **Absolute Permeability**: Calculates the absolute permeability of the porous medium through a Stokes flow simulation.
-   **Absolute Permeability - Representative Elementary Volume**: Performs the absolute permeability calculation in multiple subvolumes for Representative Elementary Volume (REV) analysis.
-   **Absolute Permeability - Darcy FOAM**: Reads a permeability field and configures a simulation case in OpenFOAM for the DarcyBR solver.
-   **Relative Permeability**: Calculates the two-phase relative permeability using the Lattice Boltzmann Method (LBM) from a segmented binary image.