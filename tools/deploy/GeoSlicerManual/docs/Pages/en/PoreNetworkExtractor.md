## Extractor

This module is used to extract the pore and bond network from: an individualized segmentation of pores (_Label Map Volume_) performed by a _watershed_ algorithm, generating a uniscalar network; or from a porosity map (_Scalar Volume_), which will generate a multiscalar model with resolved and unresolved pores.

| ![Extraction Module Interface](../../assets/images/PoreNetworkExtractor.png) |
|:-----------------------------------------------------------------------:|
| Figure 1: Extraction Module Interface. |

After extraction, the following will be available in the GeoSlicer interface: the pore and throat tables, as well as the network visualization models. The generated tables will be the data used in the subsequent simulation step.

| ![Label Map](../../assets/images/PoreNetworkExtractorLabelMap.png){ width=50% }![Uniscalar Network](../../assets/images/PoreNetworkExtractorRedeUniescalar.png){ width=50% } |
|:-----------------------------------------------------------------------:|
| Figure 1: On the left, the Label Map used as input for extraction, and on the right, the extracted uniscalar network. |

| ![Scalar](../../assets/images/PoreNetworkExtractorScalar.png){ width=50% }![Multiscalar Network](../../assets/images/PoreNetworkExtractorRedeMultiescala.png){ width=50% } |
|:-----------------------------------------------------------------------:|
| Figure 2: On the left, the Scalar Volume used as input for extraction, and on the right, the extracted multiscalar network, where blue represents resolved pores, and pink represents unresolved pores. |

**Color Scale:**

**Spheres (Pores):**

*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:blue; vertical-align: middle;"></span> **Blue** - Resolved pore
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:magenta; vertical-align: middle;"></span> **Magenta** - Unresolved pore

**Cylinders (Throats):**

*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:green; vertical-align: middle;"></span> **Green** - Throat between resolved pores
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:yellow; vertical-align: middle;"></span> **Yellow** - Throat between a resolved and an unresolved pore
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:red; vertical-align: middle;"></span> **Red** - Throat between unresolved pores