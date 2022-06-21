# QEMSCAN Loader

_GeoSlicer_ module to load QEMSCAN images in batches, as described in the steps bellow:

1. Use the _Add directories_ button to add directories containing QEMSCAN data. These directories will appear at the _Data to be loaded_ area (a search for QEMSCAN data in these directories will occur at one subdirectory level down at most). You can also remove unwanted entries by selecting them and clicking _Remove_.

2. Select the _Lookup color table_. You can select the _Default mineral colors_ table or add a new lookup table yourself, by clicking the _Add new_ button and selecting a CSV file. You also have the option to let the loader look for a CSV file in the same directory as the QEMSCAN file being loaded. You also have the checkbox option to _Fill missing values from "Default mineral colors" lookup table_. 

3. Set the _Pixel size_ (in millimeters).

4. Click the _Load QEMSCANs_ button and wait for completion. The loaded QEMSCANs can be accessed from the _Data_ tab, under the _QEMSCAN_ directory.