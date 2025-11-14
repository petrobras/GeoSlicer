## Volume Calculator

The **Volume Calculator** module performs mathematical and logical operations using the volumes loaded in the project. It is a flexible tool for combining, modifying, and analyzing volumetric data through custom formulas.

#### Step 1: Write the Formula

1.  Locate the volumes you want to use. You can use the filter field to find them more easily.
2.  In the **Formula** field, type the desired mathematical expression.
3.  To insert a volume into the formula, type its name exactly as it appears in the data tree, enclosing it in curly braces `{}`. Alternatively, double-click on the volume name in the data tree to have it automatically inserted into the **Formula** field.

Here are some examples of valid formulas:

*   **Simple arithmetic operation:**
    ```
    {Volume1} + log({Volume2})
    ```
    This formula adds the values of `Volume1` with the logarithm of the values of `Volume2`.

*   **Mask creation (thresholding):**
    ```
    {Volume1} < 10000
    ```
    This formula generates a new binary volume (mask). Regions where `Volume1` values are less than 10000 will receive the value 1, and the others will receive the value 0.

*   **Mask application:**
    ```
    ({Volume1} > 13000) * {Volume1}
    ```
    This formula first creates a mask for `Volume1` values greater than 13000 and then multiplies this mask by the original `Volume1`. The result is a volume where values below the threshold are zeroed out.

[Complete list of available operators and functions](https://numexpr.readthedocs.io/en/latest/user_guide.html#supported-operators)

#### Step 2 (Optional): Use Mnemonics

If volume names are too long or complex, you can use mnemonics (aliases) to simplify writing the formula.

1.  Expand the **Mnemonics** section.
2.  Click on the **Mnemonic Table** selector to choose an existing table or create a new one.
3.  If you create a new table, it will appear in the preview area. Double-click on the cells to edit and associate a **Volume name** with a **Mnemonic**.
4.  Use the **Add mnemonic** and **Remove selected mnemonics** buttons to add or remove rows from the table.
5.  With a mnemonic table selected, when you double-click on a volume in the data tree, its mnemonic will be inserted into the formula instead of its full name.

!!! note "Note"
    Mnemonic tables are saved in the _GeoSlicer_ scene within a folder called `Volume Calculator Mnemonics`, allowing them to be reused in future calculations.

#### Step 3: Define the Output Volume

1.  In the **Output volume name** field, type the name for the new volume that will be generated with the calculation result.

#### Step 4: Execute the Calculation

1.  Click the **Calculate** button.
2.  The operation will be executed, and a status bar will show the progress.
3.  At the end, the new output volume will be added to the scene, usually in the same folder or directory as the first volume used in the formula.

!!! warning "Geometry Alignment (Resampling)"
    If the volumes used in the formula have different geometries (distinct dimensions, spacing, or origin), all volumes will be **automatically resampled** temporarily to match the geometry of the **first volume** listed in the formula. Although this resampling is necessary for the calculation, it can introduce interpolation into the data. Verify that the order of the volumes in the formula is in accordance with the expected result.