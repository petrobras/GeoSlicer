## Relative Permeability (Krel) Simulation

### Single Krel Simulation (animation)
{{ video("pnm_krel_animation.webm", caption="Video: Workflow for relative permeability simulation with animation.") }}

The workflow below allows you to simulate and obtain an animation of **Drainage** and **Imbibition** processes:

1.  **Load** the volume on which you want to run the simulation;
2.  Perform **Manual Segmentation** using one of the segments to designate the porous region of the rock;
3.  Separate the segments using the **Inspector** tab, thus delineating the region of each pore;
4.  Use the **[Extraction](/Volumes/PNM/PNM.md#extractor)** tab to obtain the pore and throat network from the generated LabelMap volume;
5.  On the **[Simulation](/Volumes/PNM/PNM.md#two-phase)** tab;
6.  Check the option **"Create animation node"** in the **["Simulation options"](/Volumes/PNM/PNM.md#simulation-options)** box and click the **"Apply"** button;
7.  Upon finishing the simulation, go to the **"Cycles Visualization"** tab and select the animation node to visualize the generated cycle and curve;

### Sensitivity Test
{{ video("pnm_sensibility.webm", caption="Video: Workflow for Sensitivity Test (varying parameters for multiple Krel simulations).") }}

The workflow below allows the user to simulate and obtain a cloud of Krel curves from which they can perform different analyses to determine the most sensitive properties:

1.  **Load** the volume on which you want to run the simulation;
2.  Perform **Manual Segmentation** using one of the segments to designate the porous region of the rock;
3.  Separate the segments using the **Inspector** tab, thus delineating the region of each pore;
4.  Use the **Extraction** tab to obtain the pore and throat network from the generated LabelMap volume;
5.  On the **Simulation** tab, choose the pore table, in the Simulation selector select **"Two-phase"**;
6.  Select multiple values for some parameters by clicking the **"Multi"** button (as we did for the center of the contact angle distributions in the video) - You can find more information about the parameters in the **"Two-phase"** section;
7.  (Optional) Save the selected parameters using the **"Save parameters"** section;
8.  Click the **"Apply"** button to run the various simulations;
9.  Upon finishing the execution, go to the **"Krel EDA"** tab and select the generated parameters table to perform different analyses using the interface's visualization features (curve cloud, parameter and results correlations, etc.);

### Production Estimation
{{ video("pnm_production.webm", caption="Video: Production estimation workflow.") }}

The workflow below allows the user to simulate and obtain a cloud of Krel curves, on a single-scale sample:

1.  **Load** the volume on which you want to run the simulation;
2.  Perform **Manual Segmentation** using one of the segments to designate the porous region of the rock;
3.  Separate the segments using the **Inspector** tab, thus delineating the region of each pore;
4.  Use the **Extraction** tab to obtain the pore and throat network from the generated LabelMap volume;
5.  Select multiple values for some parameters by clicking the **"Multi"** button (as we did for the center of the contact angle distributions in the video) - You can find more information about the parameters in the **"Two-phase"** section;
6.  (Optional) Save the selected parameters using the **"Save parameters"** section;
7.  Click the **"Apply"** button to run the various simulations;
8.  Upon finishing the execution, go to the **"Production Prediction"** tab and select the parameters table generated in the simulation; Two options are available in this interface:
    *   The first one, "Single Krel," is an analysis of each individual simulation;
    *   The second, "Sensitivity test," is a production estimation considering all simulations performed;