## Virtual Segmentation Flow

Flow for obtaining a porosity map from a scalar volume.

```mermaid
%%{
  init: {
    'themeVariables': {
      'lineColor': '#c4c4c4'
    }
  }
}%%
flowchart LR
    Start --> Import
    Import --> Segmentation
    Segmentation --> Modelling
    Modelling --> Results
    
    click Segmentation "../../Segmentation/segmentation.html" "teste de imagem"
    style Start fill:#808080,stroke:#333,stroke-width:1px,color:#fff;
    style Import fill:#6d8873,stroke:#333,stroke-width:1px,color:#fff;
    style Segmentation fill:#5a9b87,stroke:#333,stroke-width:1px,color:#fff;
    style Modelling fill:#45ae97,stroke:#333,stroke-width:1px,color:#fff;
    style Results fill:#2ea67e,stroke:#333,stroke-width:1px,color:#fff;

    Segmentation["Segmentation"]
```

```mermaid
graph LR
    hello --> world
    world --> again
    again --> hello
```

1. Start Geoslicer in the **Volumes** environment from the application interface.

2. Select the input volume by clicking on "Escolher pasta" or "Escolher arquivo" and choose the desired import data from the available options. We suggest testing the default parameters first.

3. Select the input volume by clicking on "Input:" Adjust the parameters for different segmentation effects, such as "Múltiplos Limiares," "Remoção de Fronteira," and "Expandir Segmentos." Adjust the settings to achieve the desired segmentation results, using interface feedback and visualization tools.

4. Review and refine the segmented data. Adjust segmentation boundaries, merge or split segments, and apply other modifications to enhance the porosity model using the provided tools.

5. Save the porosity map or export the volume with the parameter tables.

```mermaid
%%{init: { 'logLevel': 'debug', 'theme': 'default','themeVariables': {
            'git0': '#808080',
            'git1': '#6d8873',
            'git2': '#5a9b87',
            'git3': '#45ae97',
            'git4': '#2ea67e',
            'git5': '#ffff00',
            'git6': '#ff00ff',
            'git7': '#00ffff',
            'gitBranchLabel0': '#ffffff',
            'gitBranchLabel1': '#ffffff',
            'gitBranchLabel2': '#ffffff',
            'gitBranchLabel3': '#ffffff',
            'gitBranchLabel4': '#ffffff',
            'gitBranchLabel5': '#ffffff',
            'gitBranchLabel6': '#ffffff',
            'gitBranchLabel7': '#ffffff',
            'gitBranchLabel8': '#ffffff',
            'gitBranchLabel9': '#ffffff',
            'commitLabelColor': '#afafaf',
              'commitLabelBackground': '#0000',
              'commitLabelFontSize': '13px'
       }, 'gitGraph': {'showBranches': true, 'showCommitLabel':true,'mainBranchName': 'Start'}} }%%
      gitGraph LR:
        commit id:"Start"
        commit id:"Volumes  ."
        branch "Import"
        commit id:"Data Tab"
        commit id:"Import Tab"
        commit id:"Select file"
        commit id:"Parameters"
        commit id:"Load  ."
        branch "Segmentation"
        commit id:"Segmentation Tab"
        commit id:"Add new segmentation node"
        commit id:"Create at least 4 segments"
        commit id:"Add ROI  ."
        branch Modelling
        commit id:"Modelling Tab"
        commit id:"Segmentation"
        commit id:"Select Volume"
        commit id:"Select Segmentation"
        commit id:"Apply  ."
        branch Results
        commit id:"Charts"
        commit id:"Images"
        commit id:"Tables"
        commit id:"Reportsd"
```
#### Start
Start Geoslicer in the MicroCT environment from the application interface.

#### Import(TODO)
Select the input volume by clicking on "Escolher pasta" or "Escolher arquivo" and choose the desired import data from the available options. We suggest testing the default parameters first.

#### Segmentation
Select the input volume by clicking on "Input:" Adjust the parameters for different segmentation effects, such as:
 
 1. Multiple Thresholds(TODO)
 2. Boundary Removal(TODO)
 3. Expand Segments(TODO)
  
Adjust the settings to obtain the desired segmentation results, using interface feedback and visualization tools.

#### Modeling(TODO)
 Review and refine the segmented data. Adjust segmentation boundaries, merge or split segments, and apply other modifications to enhance the segmentation model using the provided tools.(TODO)

#### Results(TODO)
Save the project or export the segmented volume. The results can be displayed as:

 1. Image(Screenshot)(TODO)
 2. Graphs(Charts)(TODO)
 3. Served via Reports (Streamlit)(TODO)