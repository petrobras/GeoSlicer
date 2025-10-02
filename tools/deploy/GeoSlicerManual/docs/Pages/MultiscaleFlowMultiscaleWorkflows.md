## Fluxos Possíveis
### Importação de dados e tratamentos:

#### **Dados de Image Log:**
1. Import: Image Log Import ou *[Geolog Integration](GeologEnv.md)*
2. Inpaint: *[Preenchimento de Image Log](ImageLogInpaint.md)*
3. Spiral Filter
4. Crop: *[Recorte de Image Log](ImageLogCropVolume.md)*
5. Segmentation
6. Image log export

#### **Dados de MicroCT:**
1. Import: *[Volumes Loader](./MicroCTImport.md)*
2. Crop
3. Filter: Opções de filtros para a remoção de ruídos nas imagens microCT, facilitando a etapa de segmentação.
4. Segmentation
5. Transforms
6. Volumes export

#### **Dados de CoreCT:**
1. Import
2. Crop
3. Segmentation

### Simulando com *[Multiscale](Multiscale.md)*

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
5. Exportar dado após simulação: Volumes export (TIF, RAW e outros dados). É possível exportar resultados da simulação como TIF diretamente do módulo [Multiscale Image Generation](Multiscale.md)
