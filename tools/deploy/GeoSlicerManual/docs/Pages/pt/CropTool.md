## Volumes Crop

O módulo **Volumes Crop** permite o recorte eficiente de um ou múltiplos volumes simultaneamente usando uma Região de Interesse (ROI) customizável. Ele suporta volumes do tipo Scalar, Vector e LabelMap, garantindo que todos os dados relacionados possam ser processados com um limite espacial consistente.

### Painéis e sua utilização

| ![Figura 1](../../assets/images/CropTool_UI.png) |
|:------------------------------------------------:|
|      Figura 1: Apresentação do módulo Crop.      |


### Principais opções

**Input (Entrada)**
 - _Image_: Selecione uma imagem e clique em **Add**. Você pode adicionar múltiplas imagens à lista; todas serão recortadas usando a mesma configuração de ROI. Use os botões de rádio na coluna **Visible** para escolher qual volume usar como referência nas visualizações de fatia.

**Parameters (Parâmetros)**
 - _Copy from_: (Opcional) Selecione uma ROI existente para definir a região de recorte.
 - _Center_: Define o centro preciso do recorte em coordenadas IJK. Clique no botão **...** para selecionar uma das últimas 10 configurações utilizadas.
 - _Dimensions_: Define o tamanho do recorte nas três dimensões (X, Y, Z). Clique no botão **...** para selecionar uma das últimas 10 configurações utilizadas.
 - _Copy attributes and references_: Se marcado, os volumes recortados herdarão metadados, atributos e referências dos volumes originais.
 - _Keep ROI after crop_: Se marcado, a ROI temporária será mantida como um nó permanente na cena após o recorte.

**Actions (Ações)**
 - _Crop All/Cancel_: Botões para iniciar o processo de recorte em lote ou cancelar e limpar a lista.

### Utilização

1. Selecione as imagens a serem recortadas e adicione-as à tabela.
2. Ajuste a ROI interativamente nas visualizações de fatia ou manualmente através dos campos Center e Dimensions.
3. (Opcional) Segure a tecla **Alt** enquanto arrasta as alças da ROI nas visualizações de fatia para redimensionar simetricamente em torno do centro.
4. Clique em **Crop All** e aguarde a finalização. Os volumes recortados aparecerão na mesma pasta da hierarquia de assuntos que os volumes originais.

