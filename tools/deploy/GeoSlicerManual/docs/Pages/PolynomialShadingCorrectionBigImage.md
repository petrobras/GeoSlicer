## Polynomial Shading Correction

O módulo **Polynomial Shading Correction (Big Image)** é projetado para corrigir artefatos de sombreamento ou iluminação irregular em imagens de grande volume, que não podem ser carregadas inteiramente na memória. Ele funciona ajustando um polinômio ao fundo da imagem e normalizando a iluminação, de forma similar ao filtro [Polynomial Shading Correction](PolynomialShadingCorrection.md), mas com otimizações para processamento fora do núcleo (out-of-core).

Este módulo opera sobre arquivos NetCDF (`.nc`) e salva o resultado em um novo arquivo, sendo ideal para pipelines de processamento de dados massivos.

### Princípio de Funcionamento

Este módulo adapta o algoritmo de correção de sombreamento polinomial para imagens que excedem a capacidade da memória RAM. As principais diferenças e otimizações são:

1.  **Processamento em Blocos (Out-of-Core):** A imagem é dividida e processada em blocos (chunks), garantindo que apenas uma parte do volume seja carregada na memória a qualquer momento.
2.  **Amostragem de Pontos:** Para ajustar o polinômio em cada fatia, em vez de usar todos os pixels da máscara de sombreamento, o módulo seleciona aleatoriamente um número definido de pontos (`Number of fitting points`). Isso acelera drasticamente o cálculo do ajuste sem comprometer significativamente a precisão da correção do sombreamento.
3.  **Agrupamento de Fatias (Slice Grouping):** Para otimizar ainda mais o processo, o ajuste do polinômio é calculado na fatia central de um grupo de fatias (`Slice group size`). A função de correção resultante é então aplicada a todas as fatias dentro daquele grupo.

Para uma descrição detalhada do algoritmo base de correção de sombreamento, consulte o manual do filtro [Polynomial Shading Correction](PolynomialShadingCorrection.md).

### Parâmetros

-   **Input image:** A imagem de grande volume (em formato NetCDF) a ser corrigida.
-   **Input mask:** Uma máscara que define a região de interesse. A área fora desta máscara será zerada na imagem de saída.
-   **Input shading mask:** A máscara que indica as áreas de fundo (ou com intensidade uniforme) a serem usadas para a amostragem de pontos e ajuste do polinômio.
-   **Slice group size:** Define o número de fatias em um grupo. A correção é calculada na fatia central e aplicada a todo o grupo. Um valor maior acelera o processo, mas pode não capturar variações rápidas de sombreamento ao longo do eixo das fatias.
-   **Number of fitting points:** O número de pontos a serem amostrados aleatoriamente da `Input shading mask` para realizar o ajuste do polinômio.
-   **Output Path:** O caminho do arquivo de saída no formato NetCDF (`.nc`) onde a imagem corrigida será salva.

### Casos de Uso

Este módulo é ideal para:

-   Pré-processamento de micro-tomografias computadorizadas (µCT) de alta resolução e grande escala.
-   Correção de iluminação em mosaicos de imagens ou qualquer imagem volumosa que não caiba na memória.
-   Normalização de gradientes de iluminação em grandes datasets antes da segmentação ou análise quantitativa.

