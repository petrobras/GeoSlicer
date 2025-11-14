## Mercury Intrusion Simulation

### MICP Simulation

The workflow below allows simulating the Mercury Intrusion experiment on the sample:

1. **Load** the volume in which you want to run the simulation;
2. Perform **Manual Segmentation** using one of the segments to designate the porous region of the rock;
3. Separate the segments using the **Inspector** tab, thus delimiting the region of each pore;
4. Use the [**Extraction**](/Volumes/PNM/PNM.md#extractor) tab to obtain the pore and throat network from the generated LabelMap volume;
5. In the [**Simulation**](/Volumes/PNM/PNM.md#simulation) tab, choose the pore table, in the Simulation selector select [**Mercury injection**](/Volumes/PNM/PNM.md#mercury-injection);
6. Upon completion of the simulation, the results can be viewed in the generated table or in the created graphs;

{{ video("pnm_micp.webm", caption="Video: Workflow for mercury intrusion simulation.") }}