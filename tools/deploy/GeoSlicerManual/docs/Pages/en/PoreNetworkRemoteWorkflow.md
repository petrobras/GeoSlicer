## Remote Workflow

The **Pore Network Remote Workflow** module provides an end-to-end automated pipeline for batch processing raw micro-CT sample volumes on a remote computing cluster. It coordinates raw data loading, adaptive cropping, artifact shading correction, porosity mapping, and multiscale pore network extraction, leading directly into single- and two-phase transport simulations.

By using **Dask** distributed scheduling over a **SLURM Cluster**, the workflow parallelizes tasks across multiple instances, making large sensitivity studies manageable from a single dashboard.

---

### Sample Listing and Selection

| ![Remote Workflow Module Interface](../../assets/images/PoreNetworkRemoteWorkflow.png) |
|----------------------------------------------------------------------------------------|
| **Figure 1:** Main data selector and sample filtering table.                           |

* **Select CSV File / Load:** Select your index file data (e.g., `All`) and click **Load** to populate the sample list.
* **Filter:** Dynamically query the loaded samples by:
    * `name`
    * `codigo_amostra`
    * `tipo_amostra`
    * `phi` (experimentally measured absolute porosity, if available)

* **Sample Selection:** Double-click any row in the filtered table to add the sample name to the selection box below. Sample names may also be pasted or edited manually using spaces, commas, or semicolons as separators.

---

| ![Remote Workflow Module Interface](../../assets/images/PoreNetworkRemoteWorkflowSettings.png) |
|------------------------------------------------------------------------------------------------|
| **Figure 2:** Workflow settings.                                                               |

#### Workflow Configuration

The **Load parameters** and **Save parameters** sections allow the complete Remote Workflow configuration to be stored as reusable parameter nodes inside the current GeoSlicer scene. This enables entire workflow configurations to be saved, shared, and restored without manually reconfiguring the interface.

##### Save parameters

The **Save parameters** section stores the current workflow configuration as a new Remote Workflow parameter node.

* **Output parameter node name:** Specifies the name of the parameter node to create.
* **Save parameters:** Saves the current workflow configuration into the scene.

The generated parameter node appears in the scene and can later be selected from the **Load parameters** section.

##### Load parameters

The **Load parameters** section restores a previously saved Remote Workflow configuration.

* **Input parameter node:** Select a previously saved Remote Workflow parameter node.
* **Load parameters:** Restores all saved settings into the current interface.

> **Note:** Remote Workflow parameter nodes store references to existing Extractor and Simulation parameter nodes. If a referenced parameter node is no longer present in the current scene, its corresponding selector remains empty.

#### Processing Parameters

* **Extractor params:** Select the extraction parameters used to generate the pore network.
* **One-phase params:** Select the parameters used for the one-phase simulation.
* **Two-phase params:** Select the parameters used for the two-phase simulation.

> **Note:** One-phase and two-phase simulations are executed only when **Extractor params** is selected.

> 💡 **How Parameter Nodes are Generated**
> The parameter nodes available in the **Extractor params**, **One-phase params**, and **Two-phase params** selectors are created from the **Pore Network Extractor** and **Pore Network Simulation** modules.
> Configure the desired settings in those modules, expand the **Save parameters** section, and click **Save parameters** to create reusable parameter nodes.
> The **Remote Workflow** parameter nodes created by this module are separate objects. They store the workflow configuration together with references to the selected extractor and simulation parameter nodes, allowing an entire workflow setup to be restored with a single click.

* **Output Folder Prefix:** Appends a custom identifying string to the workflow output directory name.
* **Downsampling Factor(s):** Accepts a comma-separated list of values (e.g., `2`, `4.5`, `6`). A separate workflow is generated for each specified factor.
* **Workers:** Defines the maximum number of samples processed simultaneously on the cluster. The **Suggest** button automatically calculates the recommended number of workers based on the number of selected samples and downsampling factors.
* **Save workstep image:** Controls whether intermediate workstep images are generated and stored for inspection.

---

### Crop Sample Options

When samples do not fill the visual field or exhibit border degradation, the **Crop Sample** stage isolates the valid rock volume.

#### Crop Methods

* **Method:** Specifies the method used to isolate the rock volume.
* **Auto:** The workflow analyzes the micro-CT volume boundaries to automatically choose the most appropriate cropping strategy:
    * If the sample fills the image but exhibits corner attenuation, **Cylindrical crop** is selected.
    * If the sample terminates before the image boundaries, **Sample segmentation** is selected.
    * Otherwise, cropping is skipped.

* **Cylindrical Crop:** Applies a cylindrical mask. Center coordinates default to the detected sample center. The radius may be automatically reduced using the **Reduction (%)** parameter.
* **Sample Segmentation:** Uses a 3-phase Multi-Otsu segmentation followed by morphological processing to separate the rock from the background and remove artifacts.

* **Discard bottom/top:** Removes a configurable percentage (0–45%) from the lower and upper ends of the sample along the Z axis.

Once the crop mask is generated, the workflow trims the image to the smallest bounding box enclosing the selected sample.

---

### Shading Correction Options

Corrects illumination gradients and X-ray beam hardening artifacts.

* **Function:** Specifies the correction model:
* **Auto:** Evaluates sample boundaries and cropping results to select the most appropriate correction model.
    * If it is a cylindrical cropping or partial sample boundaries are detected, **Polynomial Radial** is selected.
    * If no sample cropping is required, **Spline Radial** is selected.

* **Polynomial:** Fits a conventional polynomial across the calculated slice mask.
* **Polynomial Radial:** Constraints the polynomial fitting to a radially symmetric model.
* **Spline Radial:** Applies a radially symmetric spline-based function.
* **Order:** Specifies the polynomial order (2, 4, or 6) when a polynomial model is selected.
* **Slice Group Size:** Number of consecutive slices sharing the same fitted correction model.
* **Fitting Points (%):** Percentage of mask pixels used to estimate the correction surface.
* **Mask Percentile Min/Max:** Defines the intensity percentile range used to estimate the correction mask.

---

### Porosity Map Options

This stage generates the porosity map required by multiscale pore network extraction.

* **Gradient Anisotropic Diffusion (GAD):** Optional edge-preserving smoothing filter that reduces noise while preserving pore boundaries.
* **Porosity Derivation Methods**
    * **Standard Method (experimental φ available):** Uses the experimental porosity loaded from the database to calibrate the porosity map.
    * **Fallback Method (experimental φ unavailable):** Uses a three-class Multi-Otsu segmentation to estimate macro- and sub-resolution porosity.
* **Otsu Threshold Shifts:** Allow manual adjustment (±15%) of the Multi-Otsu thresholds when using the fallback method.

---

### Remote Jobs Tab Interface

When **Apply** or **Visualize** is executed, the workflow is submitted to the remote cluster as a single master job (`PNM Workflow: <prefix>`). Progress can be monitored from the **Remote Jobs** tab.

Right-clicking a workflow entry provides the following actions:

* **Open:** Downloads every completed sample currently available without waiting for the entire workflow to finish.
* **Details:** Displays job information, SLURM identifiers, execution paths, and stored parameters.
* **Reconnect:** Reconnects to the remote scheduler after communication interruptions.
* **Cancel/Delete:** Terminates the workflow and removes the associated cluster jobs.

---

### Data Collection

When workflow results are opened, GeoSlicer automatically reconstructs the project hierarchy:

1. **Creates workflow directory:** `<Prefix>_<Workflow_ID>`.
2. **Creates sample directories:** `<Sample_Name_Stem>`.
3. **Creates one directory for each downsampling factor (`DS_<Factor>_R<Index>`):**
    * Workflow params
    * Experimental Krel data
    * Workstep image lazy nodes:
        * `Sample`
        * `Cropped_Sample`
        * `Cropped_Sample_Mask`
        * `Shading_Correction`
        * `Shading_Mask`
        * `GAD_Pre_Porosity_Map`
        * `Porosity_Map`
    * Network Extraction nodes
    * One-Phase simulation nodes
    * Two-Phase simulation nodes

4. **Creates aggregated resolution analysis nodes** for comparing multiple downsampling factors.

---

### Step-by-Step Execution Guide

1. **Generate parameter nodes**
    * Configure the **Pore Network Extractor** module and save its parameter node.
    * Configure the **Pore Network Simulation** module and save the desired one-phase and/or two-phase parameter nodes.

2. **Load the database**
    * Open **Pore Network Remote Workflow**.
    * Select the desired CSV repository and click **Load**.

3. **Select samples**
    * Filter the sample list.
    * Double-click the desired samples or paste sample names into the selection box.

4. **Configure the workflow**
    * Optionally load a previously saved Remote Workflow configuration.
    * Select the Extractor, One-phase, and Two-phase parameter nodes.
    * Configure downsampling factors, worker count, and preprocessing options.

5. **Run the workflow**
    * Click **Apply** to submit the workflow to the cluster.
    * Click **Visualize** to perform a visualization-only execution.

6. **Monitor execution**
    * Open the **Remote Jobs** tab.
    * Use **Open** at any time to retrieve completed samples while the remaining tasks continue processing.