### Auto-fragmentar

Divida a segmentação atual em vários objetos usando o método escolhido.

Escolha quais segmentos na segmentação atual dividir em objetos utilizando as caixas de seleção. Os segmentos selecionados serão considerados um só no algoritmo de fragmentação.

**Módulo correspondente**: *[Segment Inspector](./SegmentInspector.md)*

#### Elementos da Interface

![Auto-fragmentar](../assets/images/PNMFlowAutoLabel.png)

- **Method:** Selecione o método desejado para dividir os segmentos. As opções incluem:
    - **Watershed**: Divide os segmentos encontrando bacias nos valores da imagem subjacente.
    - **Separate objects**: Divide segmentos em regiões contíguas. Os objetos não tocarão uns aos outros.

- **Segments:**
    - Lista de segmentos atualmente na imagem com caixas de seleção para escolher quais devem ser divididos.
    - Cada segmento é representado por sua cor e nome.

- **Calculate proportions:** Caixa de seleção para habilitar ou desabilitar o cálculo das proporções dos segmentos. Se habilitado, mostra a área de cada segmento em relação à região de interesse.
