## Heterogeneity Index

The Heterogeneity Index module (_Heterogeneity Index_) calculates the heterogeneity index of a well image, as proposed by [Oliveira and Gonçalves (2023)](https://doi.org/10.30632/SPWLA-2023-0034).

### Interface

The module is located in the _Well Logs_ environment. In the left sidebar, navigate through _Processing_ > _Heterogeneity Index_.

| ![Figure 1](/assets/images/HeterogeneityIndex.png) |
|:-----------------------------------------------:|
| Figure 1: Heterogeneity Index module (left) and the image visualization next to the index (right). |

#### Parameters

 - **Input**:
    - _Amplitude image_: Select the amplitude image to be analyzed.
 - **Parameters**:
    - _Window size (m)_: Size in meters of the largest depth window to be analyzed. Increasing this value will result in a smoother HI curve.
 - **Output**:
    - _Output prefix_: The output prefix. The output curve will be named as `<prefix>_HI`.
 - _Apply_: Executes the algorithm.

### Method

The method calculates the heterogeneity index (HI) of an amplitude image by evaluating the standard deviation at different scales (convolution window sizes). Subsequently, the algorithm fits a linear regression between the logarithm of the scale and the standard deviation. The slope coefficient of this regression represents the heterogeneity index for each analyzed depth. Thus, the index quantifies the relationship between local variation and the observation scale.

### References

- OLIVEIRA, Lucas Abreu Blanes de; GONÇALVES, Leonardo. *Heterogeneity index from acoustic image logs and its application in core samples representativeness: a case study in the Brazilian pre-salt carbonates*. In: **SPWLA 64th Annual Logging Symposium**, June 10–14, 2023. Proceedings [...]. [S.l.]: Society of Petrophysicists and Well-Log Analysts, 2023. DOI: [10.30632/SPWLA-2023-0034](https://doi.org/10.30632/SPWLA-2023-0034).