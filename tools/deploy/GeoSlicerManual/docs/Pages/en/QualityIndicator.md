## Quality Indicator

Well image profiles can be affected by problems during acquisition, such as tool eccentricity (when the tool is not centered in the well) and spiraling (when the tool rotates while moving). These issues introduce artifacts into the data that can hinder interpretation.

The Quality Indicator module calculates an index to quantify the presence and intensity of these artifacts in an image, allowing the user to assess data quality.

### Theory

The indicator is calculated based on the 2D Fourier transform of the input image, processed in sliding windows along the depth. The method calculates the average amplitude spectrum within a specific frequency band, which is commonly associated with eccentricity and spiraling effects (vertical wavelengths between 4 and 100 meters and a horizontal wavelength of 360 degrees).

The result is a normalized value between 0 and 1:

-   Values close to 0 indicate a low presence of artifacts (high quality).
-   Values close to 1 indicate a high presence of artifacts (low quality).

### How to Use

#### Input

-   **Tempo de Trânsito (Transit Time):** Select the input image for the analysis. Although the label suggests "Tempo de Trânsito", any profile image can be used. However, eccentricity and spiraling artifacts are generally more evident in transit time images.

#### Parameters

-   **Tamanho da janela (m) (Window size):** Defines the size (height) of the sliding window in meters used to calculate the indicator along the well.
-   **Comprimento de onda mínimo (m) (Minimum wavelength):** The minimum vertical wavelength, in meters, to be considered as part of the spiraling effect.
-   **Comprimento de onda máximo (m) (Maximum wavelength):** The maximum vertical wavelength, in meters, to be considered.

#### Advanced Settings

-   **Fator de filtragem (Filtering factor):** A multiplicative factor for the filter. A value of `0` applies no filtering, while `1` applies maximum filtering.
-   **Passo do espectro da banda (Band spectrum step length):** Controls the smoothness of the filter band's roll-off in the frequency domain. Higher values result in a smoother transition.

#### Output

-   **Prefixo de saída (Output prefix):** Defines the prefix for the name of the generated result.
-   **Saída como imagem (Output as image):** Controls the format of the result.
    -   **Checked:** The result is an image (with the same dimensions as the input) where the value of each pixel is the quality indicator (between 0 and 1).
    -   **Unchecked:** The result is a table with two columns: `DEPTH` (Profundidade) and `QUALITY` (Qualidade), which can be viewed as a curve.

    !!! note "Note on Table Output"
        To optimize performance, the data in the table is a subsampled version (reduced by 10 times) of the full-resolution quality curve. The image output contains the full-resolution data.

#### Execution

-   **Apply:** Starts the quality indicator calculation.
-   **Cancel:** Stops a process in progress.