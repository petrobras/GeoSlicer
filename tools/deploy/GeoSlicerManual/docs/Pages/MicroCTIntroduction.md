# Ambiente Volumes

O ambiente Volumes oferece diferentes análises e processamento de imagens de Micro-CT de rochas. Com este ambiente, você pode executar uma ampla gama de tarefas, desde a aplicação de filtros nas imagens até a modelagem e simulações de fluxos de permeabilidade. 

## Seções

O ambiente Volumes do GeoSlicer é organizado em vários módulos, cada um dedicado a um conjunto específico de tarefas. Clique em um módulo para saber mais sobre suas funcionalidades:

*   **[Carregamento](../Volumes/MicroCTImport/Import.md):** Projetado para importar e processar imagens de MicroCT.
*   **[Filtros](../Volumes/Filter/Filter.md):** Disponibiliza filtros de imagem para aprimorar seus dados e remover ruído. Inclui filtros avançados como Gradiente de Difusão Anisotrópica e Correção Polinomial de Sombreamento.
*   **[Segmentação](../Volumes/Segmentation/Segmentation.md):** Realize a segmentação de imagens usando métodos [automáticos](../Volumes/Segmentation/Segmentation.md#ai-segmenter) ou [manuais](../Volumes/Segmentation/Segmentation.md#manual-segmentation) para separar diferentes fases e características em suas amostras de rocha.
*   **[Microtom](../Volumes/Microtom/Microtom.md):** Um módulo dedicado a simulação em dados de microtomografia.
*   **[Microporosidade](../Volumes/Microporosity/Microporosity.md):** Calculo da microporosidade gerando um mapa de porosidade de suas amostras de rocha a partir de uma [segmentação](../Volumes/Microporosity/Microporosity.md#mapa-de-porosidade-via-segmentacao) ou a partir das amostras [seca e saturada](../Volumes/Microporosity/Microporosity.md#mapa-de-porosidade-via-saturacao).
*   **[Modelling Flow](../Volumes/ModellingFlow/StreamlinedModelling.md):** Fluxos comuns para o cálculo de microporosidade.
*   **[Registro](../Volumes/Register/Register.md):** Alinhe e registre várias imagens em um sistema de coordenadas comum.
*   **[PNM (Modelagem de Rede de Poros)](../Volumes/PNM/PNM.md):** [Extraia](../Volumes/PNM/PNM.md#extractor), [simule](../Volumes/PNM/PNM.md#simulation) e [analise](../Volumes/PNM/PNM.md#krel-eda) redes de poros a partir de suas amostras. Esta é uma ferramenta poderosa para entender as propriedades de fluxo de suas amostras.
*   **[Big Image](../Volumes/BigImage/BigImage.md):** Permite carregar e processar arquivos de imagem grandes que não podem ser carregados na memória de uma só vez.
*   **[More tools](../Volumes/MoreTools/MoreTools.md):** Explore ferramentas adicionais para análise e visualização de resultados.
*   **[Import](../Volumes/Import/Import.md):** Importa dados de fontes padronizadas.

## O que você pode fazer?

Com o ambiente MicroCT do GeoSlicer, você pode:

*   **Visualizar e analisar imagens 2D e 3D de Micro-CT de rochas.**
*   **Aplicar uma ampla gama de filtros de processamento de imagem.**
*   **Segmentar imagens para identificar diferentes fases e características.**
*   **Extrair e analisar redes de poros.**
*   **Calcular propriedades petrofísicas importantes como porosidade e permeabilidade a partir de simulações.**
