# Permeability Modeling

This module estimates a continuous permeability profile (a 1D curve) from a well log image (2D) that has been previously segmented. The method also uses a porosity profile and plug permeability data (samples) to calibrate the model. It is a particularly useful method for dual-porosity reservoirs.

The process is based on the work of Menezes de Jesus, C., et al. (2016).

## Inputs and Outputs

- **Main Inputs:**
    1.  **Segmented Profile Image (2D):** An image of the wellbore wall where each pixel has been classified into a rock or pore type (e.g., "microporosity", "macroporosity", "vug", "solid rock"). The set of classes is defined by the user during the segmentation step.
    2.  **Porosity Profile (1D):** A continuous well log (curve) representing the total porosity along the depth.
    3.  **Plug Permeability Measurements (point-wise):** Laboratory measurements on rock samples, used as a reference to calibrate the model.
- **Output:**
    - **Modeled Permeability Profile (1D):** A new table containing a continuous permeability versus depth profile (curve), with the same depth interval as the input image.

## Theory

Permeability ($K$) at each depth is calculated as a weighted sum, where the contribution of each segment class is taken into account. The formula is:

$$ K = (A_1 \cdot F_1 \cdot \Phi^{B_1}) + (A_2 \cdot F_2 \cdot \Phi^{B_2}) + \dots + (A_n \cdot F_n \cdot \Phi^{B_n}) + (A_m \cdot F_m \cdot \Phi) $$

Where, for each depth:

- **$A$ and $B$**: Calibration parameters, optimized by the model so that the result fits the reference measurements (plugs).
- **$F_n$**: Fraction of segment class *n* (e.g., the fraction of "microporosity" at that depth in the image).
- **$F_m$**: Fraction of the segment defined as "Macropore". For this class, the porosity exponent is fixed at 1, differentiating it from the others.
- **$\Phi$**: Total porosity (read from the input porosity profile).

## How to Use

!!! note "Important Note about the Data"
    To ensure correct results, input data must meet the following requirements:

    *   **Depth Units:** All input profiles (well logs and plug measurements) must use **millimeters (mm)** as the depth unit. The output table will also be generated with depths in millimeters.
    *   **Calculation and Interpolation Interval:** The calculation is performed only within the depth interval where the porosity profile and the segmented image **overlap**. The porosity profile will be interpolated to match the exact depths of the image, and any missing values (NaN) in the porosity profile will be ignored.

1.  **Input Images:**
    *   **Well Logs (.las):** Select the table containing the well logs (imported via [Image Log Import](/ImageLog/Import/Import.md)).
    *   **Porosity Profile:** From the list, choose which column in the table corresponds to the porosity profile (1D curve).
    *   **Segmented Image:** Select the 2D well log image that has already been segmented into classes.

2.  **Parameters:**
    *   **Macropore Segment:** Among the classes present in your segmented image, select the one that represents macropores. This class will be treated differently in the formula, as described in the Theory section.
    *   **Ignored/Null Segment:** Select a class from your segmented image that should be disregarded in the calculation (e.g., an "uncertainty" class or one with poor image quality).

3.  **Reference Permeability:**
    *   **Plug Measurements:** Select the table containing the plug permeability measurements.
    *   **Plug Permeability Profile:** Choose which column in the plug table corresponds to the permeability values.

4.  **Kds Optimization (Advanced):**
    *   This section allows the user to input manual calibration points to force the model to pass through specific values at certain depths. This is useful for correcting errors in zones of interest.

5.  **Output:**
    *   **Output Name:** Define the name for the output table that will contain the calculated permeability profile.

6.  **Apply:**
    *   Click "Apply" to start the calculation. The result will be a new table with "DEPTH" and the modeled permeability profile columns.

---
*Reference: Menezes de Jesus, C., Compan, A. L. M. and Surmas, R., Permeability Estimation Using Ultrasonic Borehole Image Logs in Dual-Porosity Carbonate Reservoirs, 2016.*