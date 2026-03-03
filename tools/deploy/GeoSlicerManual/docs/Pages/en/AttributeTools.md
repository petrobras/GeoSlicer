## Attribute Tools

The Attribute Tools module provides tools for editing image attributes. These attributes can be inspected in the "Attributes" tab in the Explorer module.

### Import PCR from file

This tool allows the user to import a PCR file and associate it with a volume. The PCR file contains information which is particularly useful for certain analyses like porosity mapping from saturation.

While PCR information is usually imported alongside the image data (for example, through **MicroCT Import** or **NetCDF Loader**), this tool is useful when the PCR data needs to be imported separately or updated.

#### How to use

1.  **Select a tool**: From the "Tool" dropdown menu, select "Import PCR from file".
2.  **Input Volume**: Select the volume node that you want to associate the PCR data with.
3.  **PCR File**: Click the file browser icon to select the `.pcr` file from your computer.
4.  **File Validation**: After selecting a file, the module will validate it.
    -   If the file is a valid PCR file, it will display the minimum and maximum values found in the file.
    -   If the file is not valid or does not exist, an error message will be displayed.
5.  **Import**: Once a valid volume and a valid PCR file are selected, the "Import PCR" button will be enabled. Click it to import the data.
6.  A success message will appear after the import is complete. The PCR information is now stored within the volume node's metadata. You can verify this by navigating to the Explorer module, selecting the volume, and inspecting the `Attributes` tab.
