## ImageLog Export

The **Image Log Exporter** module is used to export well log data, such as scalar volumes, segmentations, and tables, into industry-standard file formats.

The main purpose of this module is to allow data processed or generated in GeoSlicer to be easily transferred to other software specialized in well log analysis, such as Techlog or Geolog. It ensures that the data is converted into compatible formats, preserving its structure and essential information.

### How to Use

1.  **Select Data:** In the data hierarchy tree, select the items (volumes, segmentations, or tables) you want to export. You can select multiple items.
    * **Associated data**: If a selected item has any associated data, the **Associated data** option will be available and will allow you to choose the types of data to be exported together. Currently, only **Proportions** data is available.
    *   **Well log:** Define the output format for any selected well log data (e.g.: `LAS`, `DLIS`, `CSV`).
    *   **Table:** Define the output format for the selected tables, if any.
3.  **Ignore directory structure (Optional):** Check the **Ignore directory structure** option if you want all files to be saved directly into the export directory, without recreating the project hierarchy's folder structure.
4.  **Select Export Directory:** In the **Export directory** field, choose the folder where the files will be saved.
5.  **Click Export:** Press the **Export** button to start the process.

### Output Formats

#### Well Logs

-   **DLIS:** Industry-standard format for well logging data.
-   **CSV (matrix format):** Exports data in a "wide" spreadsheet format, where each row represents a single depth value given in the first column, while the other columns represent values at that depth. Example of matrix CSV:
    ```
    MD,Volume[0],Volume[1]
    10.0,50,60
    10.1,52,62
    ```
-   **CSV (Techlog format):** Generates a CSV file in a specific format, optimized for import into Techlog software. It is a "flattened" format, where multiple values at the same depth are stored as multiple rows. Example of Techlog CSV:
    ```
    depth,intensity
    m,HU
    10.0,50
    10.0,60
    10.1,52
    10.1,62
    ```
-   **LAS:** Another widely used standard text format for well log data.
-   **LAS (for Geolog):** A variation of the LAS format, adjusted for better compatibility with Geolog software.

#### Tables (Table)

-   **CSV:** Standard comma-separated values format, compatible with most spreadsheet and data analysis software.