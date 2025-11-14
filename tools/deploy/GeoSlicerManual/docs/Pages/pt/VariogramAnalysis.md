## Variogram Analysis

O módulo **Variogram Analysis** faz uma análise da correlação espacial e a representatividade estatística dos dados em um determinado volume.

O variograma é uma função que mede a diferença quadrática média entre valores da imagem para uma dada distância entre eles. Funções que apresentam baixos valores para longas distâncias indicam um maior grau de continuidade da amostra. O módulo calcula esta função para as três direções da imagem (X, Y e Z) e ajusta um modelo para extrair parâmetros como **Alcance (Range)**, **Patamar (Sill)** e **Efeito Pepita (Nugget)**.

![Variograma](../../assets/images/Schematic_variogram.png){width=40%}

A análise de subvolumes é um método de avaliação do **Volume Elementar Representativo (REV)**, que corresponde ao menor volume para o qual a média das propriedades de um material se torna constante e representativa do todo. O módulo determina o REV analisando a variação (na forma de desvio padrão) da média da propriedade dentro de subvolumes de tamanhos crescentes. O REV é tomado como a região de baixa inclinação na curva resultante.

### Entradas

O módulo utiliza um painel de entrada unificado:

-   **Input node**: O volume principal para análise. Pode ser:
    -   `vtkMRMLScalarVolumeNode`: Uma imagem em escala de cinza (ex: imagem de micro-CT).
    -   `vtkMRMLLabelMapVolumeNode`: Uma imagem segmentada (label map).
    -   `vtkMRMLSegmentationNode`: Uma segmentação. Se esta opção for usada, o usuário deve selecionar quais segmentos da lista devem ser analisados. A análise será binária (1 para segmentos selecionados, 0 para o resto).

-   **Reference**: O volume usado para definir a geometria, espaçamento (tamanho do voxel) e orientação do espaço. Geralmente, é o mesmo que o nó de entrada.

-   **Region (SOI)**: Um nó opcional para definir uma máscara. Se um SOI for fornecido, toda a análise (Variograma e REV) será restrita apenas aos voxels dentro desta região.

### Parâmetros

Existem duas formas principais de usar o módulo:

-   **Sem SOI (Método FFT)**: Se nenhuma "Região (SOI)" for fornecida, o módulo assume que o usuário deseja analisar o volume inteiro. Para acelerar o cálculo, ele utiliza um método baseado em Transformada Rápida de Fourier (FFT).

-   **Com SOI (Método de Amostragem)**: Se uma "Região (SOI)" for fornecida, o módulo usa um método de amostragem de pares de pontos dentro da máscara. Este método calcula variogramas direcionais (**X**, **Y**, **Z**) e um variograma omnidirecional (**r**).

O módulo é dividido em duas seções de análise. *Variogram results* calcula o variograma para entender a variabilidade da propriedade no volume. Os parâmetros desse algoritmo são:

-   `Sampling rate`: Porcentagem de pontos que será subamostrada dentro do SOI para o cálculo. Visa melhorar o tempo de processamento, ao custo de uma potencial perda de acurácia.
-   `Maximum number of samples`: Número máximo de pontos da subamostragem que será utilizada, limitando a amostragem definida pelo `Sampling rate`. O objetivo é também melhorar o tempo de processamento, sacrificando acurácia.
-   `Number of lags`: Define o número de divisões no eixo de distância (eixo X do variograma), análogo ao número de *bins* em um histograma.
-   `Directional tolerance`: Tolerância angular (em graus) para o cálculo dos variogramas direcionais (X, Y, Z). Durante o cálculo em uma direção específica, o algoritmo considera não apenas os pontos perfeitamente alinhados, mas também aqueles que estão dentro dessa tolerância angular. O objetivo é aumentar a robustez estatística, especialmente em dados esparsos. Para dados de micro-CT, onde a densidade de pontos é alta, valores menores (ex: < 60°) são geralmente suficientes.
-   `Maximum distance`: Permite definir manualmente a distância máxima (em mm) para o cálculo do variograma. Se desmarcado, usa uma distância padrão (baseada na média).
-   `Use nugget`: Se marcado, leva em conta o "Efeito Pepita" no ajuste do modelo de variograma.

A seção *Representative volume analysis* calcula o desvio padrão da média conforme a distância. isso serve para determinar o tamanho de subvolume onde a propriedade de interesse se torna estatisticamente estável. Nesse algoritmo os parâmetros são:

-   `Number of volume sizes`: O número de tamanhos de aresta diferentes a serem testados (ex: 10 tamanhos entre o mínimo e o máximo).
-   `Maximum number of samples per volume`: O número de subvolumes aleatórios a serem amostrados para cada tamanho, garantindo robustez estatística.

### Resultados e Saídas

-   **Gráficos de Variograma**:
    -   Um gráfico de barras superior mostra o número de pares de pontos (amostras) usados em cada "lag" (distância).
    -   O gráfico principal mostra os pontos do variograma experimental e a curva do modelo ajustado para cada direção (X, Y, Z, r).

-   **Tabela de Parâmetros**: Abaixo do gráfico, uma tabela exibe os valores ajustados de **Range (Alcance)**, **Sill (Patamar)** e **Nugget (Efeito Pepita)** para cada direção.

-   **Gráfico de REV**:
    -   Um gráfico de barras superior mostra o número de amostras (subvolumes) usadas para cada tamanho.
    -   O gráfico principal plota o **Desvio Padrão da Média** (eixo Y) contra o **Tamanho da Aresta** (eixo X, em mm).

#### Exportação de Relatório (HTML)

O módulo pode gerar um relatório HTML unificado contendo os resultados de ambas as análises.

-   **Export directory**: O usuário especifica a pasta onde o relatório será salvo.
-   **Export report**: Ao clicar, o módulo:
    1.  Extrai metadados do nome do arquivo de referência (ex: Poço, Plugue, Condição, usando a convenção).
    2.  Captura uma imagem da visualização 3D atual do Slicer.
    3.  Captura imagens dos gráficos de Variograma e REV (se tiverem sido calculados).
    4.  Insere todas essas informações (metadados, imagens, tabelas de resultados) em um modelo HTML (`variogram_report_template.html`) e o salva no diretório de exportação.
