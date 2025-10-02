
# Ambiente Multiscale



# Ambiente Multiescale


O ambiente Multiescale oferece uma integração única entre três escalas de análise: MicroCT, CoreCT e Image Logs, reunindo módulos especializados de cada uma dessas áreas para facilitar a integração multiescalar. Ele é composto por três componentes principais: ***[Geolog Integration](../Multiscale/GeologIntegration/GeologEnv.md)***, que facilita a importação e exportação de arquivos com projetos do Geolog; **[Multiscale Image Generation](../Multiscale/MultiscaleImageGeneration/Multiscale.md)**, que utiliza a biblioteca MPSlib para gerar imagens sintéticas a partir de uma imagem de treino; e **[Multiscale Post-Processing](../Multiscale/MultiscalePostProcessing/MultiscalePostProcessing.md)**, focado na análise e métricas dos resultados das simulações multiescala. Com essa combinação de ferramentas, é possível realizar simulações multiescala, permitindo uma modelagem geológica mais precisa e detalhada. Além disso, o ambiente possibilita a importação de diferentes tipos de dados, ampliando a capacidade de integração e análise.


## Seções

O ambiente Multiescale do GeoSlicer é organizado em vários módulos, cada um dedicado a um conjunto específico de tarefas. Clique em um módulo para saber mais sobre suas funcionalidades:

*   **[Integração Geolog](../Multiscale/GeologIntegration/GeologEnv.md):** Ferramentas para integração com o software Geolog.
*   **[Ferramentas de Importação](../Multiscale/ImportTools/ImportTools.md):** Módulos para importar dados de Perfis de Imagem, Testemunhos e Micro-CT.
*   **[Ferramentas de Exportação](../Multiscale/ExportTools/ExportTools.md):** Módulos para exportar dados de Perfis de Imagem, Testemunhos e Micro-CT.
*   **[Pré-processamento de Perfis de Imagem](../Multiscale/ImageLogPreProcessing/ImageLogPreProcessing.md#image-log-crop):** Ferramentas para recortar, filtrar e corrigir dados de perfis de imagem.
*   **[Pré-processamento de Volumes](../Multiscale/VolumesPreProcessing/VolumesPreProcessing.md#volumes-crop):** Ferramentas para recortar, reamostrar e filtrar volumes.
*   **[Geração de Imagem Multiescala](../Multiscale/MultiscaleImageGeneration/Multiscale.md):** Módulo central para a geração da imagem 3D de alta resolução.
*   **[Pós-processamento Multiescala](../Multiscale/MultiscalePostProcessing/MultiscalePostProcessing.md):** Ferramentas para analisar e processar a imagem multiescala gerada.
*   **[Rede de Poros](../Multiscale/PNM/PNM.md#extractor):** Módulos para extração e simulação de redes de poros.
*   **[Segmentação de Volume](../Multiscale/Segmentation/Segmentation.md#manual-segmentation):** Ferramentas para segmentação manual e automática de volumes.

## O que você pode fazer?

Com o ambiente Multiescala do GeoSlicer, você pode:

*   **Integrar dados de diferentes escalas (perfis de imagem, testemunhos, micro-CT).**
*   **Gerar uma imagem 3D de alta resolução representativa da rocha a partir de dados de poço.**
*   **Pré-processar dados de imagem para melhorar a qualidade e consistência.**
*   **Analisar a imagem multiescala gerada com ferramentas de segmentação e análise de poros.**
*   **Extrair modelos de rede de poros para simular propriedades petrofísicas.**
*   **Calcular permeabilidade e outras propriedades de fluxo.**
