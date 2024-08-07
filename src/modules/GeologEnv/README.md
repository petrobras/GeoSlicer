# Geolog Env

This module provides _GeoSlicer_ an interface for connecting to _Geolog_. Allowing to import/export data from/to _Geolog_. This module requires _Geolog_ Python 3.8 as it contains some libraries and tools used during execution.

## Inputs
### Connection
1. __Geolog directory__: Select the directory of _Geolog_ installation. The usual directory path is "C:/Program Files/Paradigm/Geolog22.0" for Windows and "/home/USER/Paradigm/" in Linux. Version 22.0 was used during development.

2. __Projects folder__: Select the directory contaning _Geolog_ projects that are going to be accessed. The usual directory path is "C:/programData/Paradigm/projects" in Windows and "/home/USER/Paradigm/projects/" in Linux.

3. __Project__: _Geolog_ projects available in the chosen project directory.

### Importing from _GEOLOG_

1. __Null values list__: List of values that are considered to be null. they will be changed to nan after the data is imported into _Geoslicer_.

2. __Well diameter (inches)__: Diameter of the well which the data is being imported from. This is used for setting the vetical spacing of the imagelog.

3. __Well Name__: Name of the wells avaliable to choose from after connecting to the project.

4. __Log Table__: Table containing the logs available in the well.


### Exporting to _GEOLOG_

1. __Choose a well__: The dropdown list allows for easly selecting a target well to export. Choosing "New Well" option allows for user to create new well, although setting the name of an existing well will not overwrite it, but act as if a well was choosen.

2. __Choose a set__: Name of the set that will be created during export. At the moment we cannot add the data to an existing set, only creating a new set. Choosing a name of a existing set will overwrite it if the checkbox is selected. If not, the export will be terminated.

3. __Data selection__: Widget containig the _Geoslicer_ tree view to select which volumes are to be exported. Due to how we write the data into _Geoslicer_, the volumes must have the same vertical spacing to avoid gaps in _Geolog_