# Ambiente Multiscale

Este ambiente de trabalho oferece uma integração única entre três escalas de análise: MicroCT, CoreCT e Image Logs, reunindo módulos especializados de cada uma dessas áreas para facilitar a integração multiescalar. Ele é composto por três componentes principais: ***[Geolog Integration](../Multiscale/GeologEnv.md)***, que facilita a importação e exportação de arquivos com projetos do Geolog; **[Multiscale Image Generation](../Multiscale/Multiscale.md)**, que utiliza a biblioteca MPSlib para gerar imagens sintéticas a partir de uma imagem de treino; e **[Multiscale Post-Processing](../Multiscale/MultiscalePostProcessing.md)**, focado na análise e métricas dos resultados das simulações multiescala. Com essa combinação de ferramentas, é possível realizar simulações multiescala, permitindo uma modelagem geológica mais precisa e detalhada. Além disso, o ambiente possibilita a importação de diferentes tipos de dados, ampliando a capacidade de integração e análise.

## Fluxos Possíveis:
### Importação de dados e tratamentos:

#### **Dados de Image Log:**
1. Import: *[Image Log Import](../../Data_loading/load_well_log.md)* ou *[Geolog Integration](../Multiscale/GeologEnv.md)*
2. Inpaint: *[Preenchimento de Image Log](../Multiscale/ImageLogInpaint.md)*
3. Spiral Filter
4. Crop: *[Recorte de Image Log](../Multiscale/ImageLogCropVolume.md)*
5. Segmentation: *[Segmentação](../../Filtering_and_Segmentation/Segmentation/manual_segmentation.md)*
6. Image log export

#### **Dados de MicroCT:**
1. Import: *[Volumes Loader](../../Data_loading/load_microct.md)*
2. Crop: *[Recorte de Volume](../../Transforms/transforms.md)*
3. Filter: Opções de filtros para a remoção de ruídos nas imagens microCT, facilitando a etapa de segmentação.
4. Segmentation: *[Segmentação](../../Filtering_and_Segmentation/Segmentation/manual_segmentation.md)*
5. Transforms: *[Ferramentas de imagem](../../Transforms/transforms.md)*
6. Volumes export

#### **Dados de CoreCT:**
1. Import: *[Multicore](../../Data_loading/load_corect.md)*
2. Crop: *[Recorte de Volume](../../Transforms/transforms.md)*
3. Segmentation: *[Segmentação](../../Filtering_and_Segmentation/Segmentation/manual_segmentation.md)*

### Simulando com *[Multiscale](../Multiscale/Multiscale.md)*

#### **Preenchendo image logs com dados faltantes ou incompletos:** 
1. Importar imagem de poço: Image Log importer ou Geolog Integration.
2. Segmentação: Separar em camadas com dados e sem dados.
3. Multiscale: Mesma imagem como TI e HD, desmarcar segmento do espaço vazio.
4. Simulação. Resultado deve preencher apenas o espaço vazio.
5. Exportar dado após simulação: Image Log Export (csv, DLIS ou LAS) ou Geolog Integration.

#### **Simulando um volume a partir de um Image Log**
1. Importar imagem de poço (HD): Image Log importer ou Geolog Integration.
2. Importar Imagem de treino (TI): Volumes Loader ou multicore.
3. Segmentação: Segmentação das imagens é obrigatória para simulação discreta. Para dados contínuos segmentação permite controlar regiões que entraram na simulação.
3. Multiscale: Volume 3D como TI e imagem de poço como HD.
4. Simulação: Marcar a opção "Wrap cylinder". Opção marcar "Continuous Data".
5. Exportar dado após simulação: Volumes export (TIF, RAW e outros dados). É possível exportar resultados da simulação como TIF diretamente do módulo [Multiscale Image Generation](../Multiscale/Multiscale.md)