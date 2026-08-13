# README #

## Setup environment

1. Clone this repository and enter in the created directory with:
```bash
git clone git@bitbucket.org:ltrace/pnmreport.git
cd pnmreport
```

2. Set up your Python environment as prefered, a good practice is to create a virtual environment to ensure isolation of your python system:
```bash
python -m venv .venv
```
and activate it:
```bash
# Windows command prompt
.venv\Scripts\activate.bat

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS and Linux
source .venv/bin/activate
```

3. Install the required packages by using pip:
```bash
pip install -r requirements.txt
```

4. You can now be able to start the web server just by typing:
```bash
streamlit run PNM_Report.py
```
in the `pnmreport/` folder.

If you need more information about the streamlit you could follow their docs [here](https://docs.streamlit.io/).

## Basic structure of the project

This streamlit project is designed to show some simulation results for the Pore Network models, this includes 3d representation of the microtomography, and equivalent pore network extracted, althogheter with some tables with data used to create some plots.

Below we show the complete file structure of the project:

```bash
.
├── PNM_Report.py           # main page
├── utils.py                # usefull functions and definitions used by the server
├── pages/                  # pages listed in the sidebar go here
│   ├── 1_Single_Report.py
│   └── 2_Folder_Report.py
├── static/                 # public data served by streamlit, we are using it to store the 
│   ├── Project1            # projects that will be loaded in interface
│   │   ├── *.tsv
│   │   ├── *.vtk
│   │   ├── *.vtp
│   │   └── *.nrrd
...
│   ├── ProjectN
│   │   ├── *.tsv
│   │   ├── *.vtk
│   │   ├── *.vtp
│   │   └── *.nrrd
│   ├── folder_report.csv   # production data generated to all projects
│   └── projects.json       # dict used to map Projects data
├── stitkvtkviewer/         # folder of JS component created for the 3d visualizations
│   ├── __init__.py         # definition of the function and arguments of stitkvtkviewer() used in pages
│   ├── index.html          # frontend part of the component
│   ├── main.js             # javascript code called by python on rendering
│   ├── streamlit-component-lib.js
│   └── calculate_hash.py   # script used to calculate hash of a file get from a CDN (to set a integrity check)
├── README.md
└── requirements.txt
```

## stvtkitkviewer Manual

For now, the stitkvtkviewer can receive the following parameters:
```python
def stitkvtkviewer(
    filenames: list,
    geometries_colors: Optional[list] = None,
    bg_color: Optional[list] = [0.58, 0.58, 0.8],
    ui_collapsed: Optional[bool] = True,
    rotate: Optional[bool] = False,
    key: Optional[str] = None,
):
```

- **filenames**: must be a list of path's of one of the following: `.nrrd`, `.vtk`, `.vtp`, served in streamlit like <http://localhost:port/app/static/{path}>, from the static folder;

- **geometries_colors** are a list of tuples used to color polydatas that are imported like a vtk. They must be the same length as the filenames to work;

- **bg_color**: the background color;

- **ui_collapsed**: ui begins collapsed;

- **rotate**: scene begins already rotating;

- **key**: used to identify the widget in streamlit;

> **WARNING**: Until now the only type of `.vtk` that we are loading using the library is ASCII formatted in version 4.2, to be more specific. BINARY `.vtk`'s as the ones that are exported directly by GeoSlicer don't seem to be supported by vtk.js. An option if you have a case like this, is to convert between the formats by using the script available at `stitkvtkviewer/bin2asciivtk.py`.

Some usage examples of this function are listed below with the corresponding results:

-----

### NRRD Volume

```python
from stitkvtkviewer import stitkvtkviewer

stitkvtkviewer(
    "Cropped_Label_PNM_0100_0100_0100_01660nm/volume.nrrd", 
    key="volume",
)
```

![alt text](image-1.png)

-----

### VTK polydatas

```python
from stitkvtkviewer import stitkvtkviewer

stitkvtkviewer(
    [
        "Cropped_Label_PNM_0100_0100_0100_01660nm/pore_polydata_0.vtk", 
        "Cropped_Label_PNM_0100_0100_0100_01660nm/throat_polydata_0.vtk",
    ], 
    geometries_colors=[
        (0.1, 0.1, 0.9), 
        (0.1, 0.9, 0.1),
    ], 
    key="network",
)
```
![alt text](image-2.png)

-----

### Mixed VTK/VTP polydatas

In order to show a polydata with a custom color range instead of the solid colors as the example above, we are using another format named `.vtp`, that serializes actors and mappers from vtk. 

So, instead of using `vtk.IO.Legacy.vtkPolyDataReader` from vtk.js to load this data, we currently use `vtk.IO.XML.vtkXMLPolyDataReader`, so their preserve it color range to show in itkvtkviewer.

> **WARNING**: We also make available a script to convert between vtk and vtp in `stitkvtkviewer/vtk2vtp.py`.

```python
stitkvtkviewer(
    [
        "Cropped_Label_PNM_0100_0100_0100_01660nm/multiangle_model.vtp", 
        "Cropped_Label_PNM_0100_0100_0100_01660nm/multiangle_arrow_model.vtk",
        "Cropped_Label_PNM_0100_0100_0100_01660nm/multiangle_plane_model.vtk",
        "Cropped_Label_PNM_0100_0100_0100_01660nm/multiangle_circle_model.vtk",
    ], 
    geometries_colors=[
        None,                 # as the first entry is a vtp, it already uses a color range so we put None here
        [0.0, 0.0, 1.0],      # blue
        [0.5, 0.5, 0.5, 0.5], # the fourth entry is opacity
        [0.5, 0.5, 0.5].      # grey
    ], 
    key="multiangle",
)
```

![alt text](image-3.png)


## Aditional information

For more details about this project can be found in our [wiki](https://bitbucket.org/ltrace/pnmreport/wiki/Home), where we also do a [FAQ](https://bitbucket.org/ltrace/pnmreport/wiki/FAQ.md), with some common problems.
