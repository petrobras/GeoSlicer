# Micro CT Environment

Ambiente para trabalhar com micro-CTs.

Módulos:

- Data
- Loader (Micro CT Loader)
- Raw Loader
- Crop (Crop Volume)
- Registration (Manual and Auto Registration)
- Segmentation
- Simulation (Microtom and Pore Network)

## Data

Módulo _GeoSlicer_ para visualizar os dados sendo trabalhados e suas propriedades.

## Micro CT Loader

Módulo _GeoSlicer_ para carregar imagens de micro-CT em lotes, conformed descrito no passos abaixo:

1. Use o botão _Add directories_ para adicionar diretórios contendo dados de micro-CT (atualmente, as extensões de arquivo aceitas são: tif, png e jpg). Esses diretórios aparecerão na área _Data to be loaded_ (uma procura por dados de micro-CT nesses diretórios ocorrá em subdiretórios abaixo em no máximo um nível). Pode-se também remover entradas indesejadas selecionando-as e clicando em _Remove_.

2. Defina o tamanho do pixel (_Pixel size_) em milímetros.

3. Clique no botão _Load micro CTs_ e aguarde o carregamento ser finalizado. As imagens carregadas podem ser acessadas na aba _Data_, dentro do diretório _Micro CT_.

## Raw Loader

Módulo _GeoSlicer_ para carregar imagens armazenadas em um formato de arquivo desconhecido ao permitir rapidamente tentar vários tipos de voxel e tamanhos de imagem, conforme descrito nos passos abaixo:

1. Selecione o arquivo de entrada em _Input file_.
   
2. Caso não souver as informações do volumes, tente adivinhar os parâmetros da imagem baseado em informações disponíveis.
   
3. Clique em _Load_ para ver uma prévia da imagem que pode ser carregada.
   
4. Experimente com os parâmetros da imagem (clique na caixa no botão _Load_ para atualizar automaticamente o volume de saída quando algum parâmetro for alterado).

5. Mova o slider _X dimension_ até colunas retas aparecerem na image (se as colunas estiverem ligeiramente inclinadas então o valor está próximo de estar correto). Tente com diferentes valores de endianness e tipo de pixel se nenhum valor em _X dimension_ parece fazer sentido.

6. Mova _Header size_ até a primeira linha da imagem aparecer no topo.

7. Se estiver carregando um volume 3D: Altere o valor do slider _Z dimension_ para algumas dezenas de fatias para tornar mais fácil ver quando o valor de _Y dimension_ está correto.

8. Mova o slider _Y dimension_ até a última linha da imagem aparecer na parte mais baixa.

9. Se estiver carregando um volume 3D: Mova o slider _Z dimension_ até todas as fatias da imagem estarem inclusas.

10. Quando a combinação correta de parâmetros for encontrada salve a saída atual ou clique em _Generate NRRD header_ para criar um arquivo de cabeçalho que pode ser carregado diretamente no Slicer.

### Mais informações sobre os formatos de exportação

**RAW** - para carregar esse formato exportado pelo módulo *Export*, estes parâmetros precisam ser definidos:

 - *Endianness*: Little endian
 - *X dimension*, *Y dimension*, *Z dimension*: as dimensões do dado
 - Para volumes escalares e imagens:
     - *Pixel type*: 16 bit unsigned
 - Para labelmaps e segmentações:
     - *Pixel type*: 8 bit unsigned

## Crop Volume

Módulo _GeoSlicer_ para cortar um volume, conforme descrito nos passos abaixo:

1. Selecione o volume em _Volume to be cropped_.

2. Ajuste a posição e tamanho desejados da ROI  nas slice views .

3. Clique em _Crop_ e aguarde a finalização. O volume cortado aparecerá no mesmo diretório que o volume original.

## Filtering Tools

Módulo _GeoSlicer_ que permite filtragem de imagens, conforme descrito abaixo:

1. Selecione uma ferramenta em _Filtering tool_.

2. Preencha as entradas necessárias e aplique.

### Gradient Anisotropic Diffusion

Módulo _GeoSlicer_ para aplicar filtro de difusão anisotrópica de gradiente a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro de condutância em _Conductance_. A condutância controla a sensibilidade do termo de condutância. Como regra geral, quanto menor o valor, mais fortemente o filtro preservará as bordas. Um alto valor causará difusão (suavização) das bordas. Note que o número de iterações controla o quanto haverá de suavização dentro de regiões delimitadas pelas bordas.

3. Defina o parâmetro de número de iterações em _Iterations_. Quanto mais iterações, maior suavização. Cada iteração leva a mesma quantidade de tempo. Se uma iteração leva 10 segundos, 10 iterações levam 100 segundos. Note que a condutância controla o quanto cada iteração suavizará as bordas.
   
4. Defina o parâmetro de passo temporal em _Time step_. O passo temporal depende da dimensionalidade da imagem. Para imagens tridimensionais, o valor padrão de de 0.0625 fornece uma solução estável.

5. Defina o nome de saída em _Output image name_.

6. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Curvature Anisotropic Diffusion

Módulo _GeoSlicer_ para plicar filtro de difusão anisotrópica de curvatura em imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro de condutância em _Conductance_. A condutância controla a sensibilidade do termo de condutância. Como regra geral, quanto menor o valor, mais fortemente o filtro preservará as bordas. Um alto valor causará difusão (suavização) das bordas. Note que o número de iterações controla o quanto haverá de suavização dentro de regiões delimitadas pelas bordas.
   
3. Defina o parâmetro de número de iterações em _Iterations_. Quanto mais iterações, maior suavização. Cada iteração leva a mesma quantidade de tempo. Se uma iteração leva 10 segundos, 10 iterações levam 100 segundos. Note que a condutância controla o quanto cada iteração suavizará as bordas.

4. Defina o parâmetro de passo temporal em _Time step_. O passo temporal depende da dimensionalidade da imagem. Para imagens tridimensionais, o valor padrão de de 0.0625 fornece uma solução estável.

5. Defina o nome de saída em _Output image name_.

6. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Gaussian Blur Image Filter

Módulo _GeoSlicer para aplicar filtro de desfoque gaussiano a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro _Sigma_, o valor em unidades físicas (e.g. mm) do kernel gaussiano.

3. Defina o nome de saída em _Output image name_.

4. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Median Image Filter

Módulo _GeoSlicer_ para aplicar filtro mediano a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser filtrada em _Input image_.

2. Defina o parâmetro _Neighborhood size_, o tamanho da vizinhança em cada dimensão.

3. Defina o nome de saída em _Output image name_.

4. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

### Shading Correction (temporariamente apenas para usuários Windows)

Módulo _GeoSlicer_ para aplicar correção de sombreamento a imagens, conforme descrito nos passos abaixo:

1. Selecione a imagem a ser corrigida em _Input image_.

2. Selecione a máscara de entrada em _Input mask LabelMap_ para ajustar as bordas do dado corrigido final.

3. Selecione a máscara de sombreamento em _Input shading mask LabelMap_, que proverá o intervalo de intensidades usado no cálculo de fundo.

4. Defina o o raio da bola do algoritmo rolling ball em _Ball Radius_.

5. Clique no botão _Apply_ e aguarde a finalização. O volume de saída filtrado estará localizado no mesmo diretório que o volume de entrada.

## Registration

### Micro CT Transforms

Esse módulo provê transformadas manuais de translação e rotação para o usuário realizar registro manual de imagens.

1. Seleciones micro-CTs a serem transformadas na área _Available volumes_ e clique na seta verde para a direita para movê-las para a área _Selected volumes_, à direita. Pode-se também remover micro-CTs da área _Selected volumes_ usando a seta para a esquerda.

2. Ajuste a translação e a rotação conforme necessário. Pode-se prever essas mudanças em _Slice views_.

3. Após definir a transformação, o usuário pode clicar em _Apply_ para aplicar as mudanças e reiniciar os parâmetros de transformação. Os botões _Undo_, _Redo_ e _Cancel_ também estão disponíveis próximo ao botão _Apply_. A transformada final é aplicada ao dado apenas após clicar em _Save_.

### CT Auto Registration

Módulo _GeoSlicer_ para registrar automaticamente imagens de CT tridimensionais, conforme descrito nos passos abaixo:

1. Selecione o volume fixo (_Fixed volume_) e o volume móvel (_Moving volume_). Transformações serão aplicadas à imagem móvel para corresponder à imagem fixa, e o resultado será salvo em um novo volume transformado, preservando os volumes fixo e móvel.

2. Defina o raio da amostra em _Sample radius_, em milímetros. Esse raio será usado para criar a máscara que identificará o dado relevante a ser registrado.

3. Defina a fração de amostragem em _Sampling fraction_, a fração dos voxels do volume fixo que serão usados para o registro. O numero deve ser maior que zero e menor ou igual a 1. Valores maiores aumentam o tempo de computação mas podem render resultados mais precisos.

4. Defina tamanho do passo mínimo em _Minimum step length_, um valor maior ou igual a 10<sup>-8</sup>. Cada passo na otimização terá no mínimo esse tamanho. Quando nenhum for possível, o registro estará completo. Valores menores permite que o otimizador faça ajustes menores, mas o tempo do registro pode aumentar.

5. Defina o número de iterações em _Number of iterations_, que determina o número máximo de iteração para tentar antes de parar a otimização. Ao ser usado um valor menor (500-1000) o registro é forçado a terminar antes, mas há um risco maior de parar antes de uma solução ótima ser obtida.

6. Defina um fator de downsampling. Esse parâmetro afeta diretamente a eficiẽncia do algoritmo. Valores altos (~1) podem exigir um alto tempo de execução para finalizar o registro. Valores intermediários, como 0.3, foram encontrados como valores ótimos para obter-se um bom resultado sem um grande custo computacional.

7. Selecione ao menos uma das fase de registro em _Registration phases_. Cada fase de registro será usada para inicializar a próxima fase.

8. Clique no botão _Register_ e aguarde completar. O volume registrado (transformado) pode ser acessado pela aba _Data_, dentro do mesmo diretório que o volume móvel. O nodo de transformada e as máscaras de labelmap criadas também estarão disponíveis para inspeção pelo usuário, mas podem ser deletadas.

## Segmentation

### Manual Segmentation

1. Selecione/crie o nodo  de segmentação de saída. O usuário pode criar uma nova segmentação ou editar uma segmentação previamente definida.
2. Selecione a imagem de entrada a ser segmentada.
3. Clique em _Add_ para adicionar segmentos.
4. Selecione um segmento da lista a ser editado.
5. Selecione uma ferramenta dentre as opção sob a lista de segmentos.
6. Mais instruções sobre cada ferramenta de segmentação pode ser encontrada após selecionada clicando em _Show details._

### Smart Segmentation

Esse módulo provê métodos avançados para segmentação automática e supervisionada de vários tipos de imagem, tais como seção delgada e tomografia permitindo múltiplas imagens de entrada.

#### __Inputs__

1. __Annotations__: Selecione o nodo de segmentação que contém as anotações feitas na imagem para treinar o método de segmentação escolido.
2. __Region (SOI)__: Selecione o nodo de segmentação em que o primeiro segmento delimita a região de interesse onde a segmentação será realizada.
3. __Input image__: Selecione a imagem a ser segmentada. Vários tipos são aceitos, como imagens RGB e tomográficas.

#### __Parameters__

1. __Method__: Selecione o algoritmo para realizará a segmentação.
    1. __Random Forest__: Florestas aleatórias são um método de aprendizado por agrupamento para classificação que opera construindo múltiplas árvores de decisão em tempo de treinamento. A __entrada__ é uma combinação de:
        * Entrada quantificada (RGB reduzido a um valor de 8 bits)
        * HSV puro
        * Múltiplos kernels gaussianos  (tamanho e número de kernels são definidos pelo parâmetro __Radius__)
        * Se selecionado, kernels de __Variância__ são calculados (Ver __Use variation__).
        * If selected, kernels de __Sobel__ são calculados (Ver __Use contours__).
    2. __Colored K-Means__: Um método de quantificação vetorial que busca particionar __n observações__ em __k clusters__ onde cada observação pertence ao cluster com a média (centro ou centroide) mais próxima. _Colored_ significa que o algoritmo funciona em espaço de cor tridimensional, especialmente HSV.
        * __Seed Initializer__: Algoritmo usado para escolher protótipos de clusters iniciais.
            * __Random__: Escolhe uma semente aleatória a partir das anotações, uma para cada segmento diferente.
            * __Smooth Centroid__: Para cada segmento, combina todas as amostras anotadas para geral uma semente mais geral.

#### __Output__

1. __Output prefix__: Digite um nome para ser usado como prefixo dos resultados.

### Segment Inspector

Para uma discussão mais detalhada sobre o algoritmo watershed, por favor cheque a seguinte [seção](../../Inspector/Watershed/estudos_de_porosidade.md) do manual do GeoSlicer.

Este módulo provê múltiplos métodos para analisar uma imagem segmentada. Particularmente, algoritmos Watershed e Islands permite fragmentar a segmentação em diversas partições, ou diversos segmentos. Normalmente é aplicado a segmentação de espaço de poros para computar as métricas de cada elemento de poro. A entrada é um nodo de segmentação ou volume labelmap, uma região de interesse (definida por um nodo de segmentação) e a imagem/volume mestre. A saída é um labelmap onde cada partição (elemento de poro) está em uma cor diferente, uma tabela com parâmetros globais e uma tabela com as diferentes métricas para cada partição.

#### __Inputs__

1. __Selecionar__ single-shot (segmentação única) ou Batch (múltiplas amostras definidas por múltiplos projetos GeoSlicer).
2. __Segmentation__: Selecionar um nodo de segmentação ou um labelmap para ser inspecionado.
3. __Region__: Selecionar um nodo de segmentação para definir uma região de interesse (opcional).
4. __Image__: Selecionar a imagem/volume mestre ao qual a segmentação é relacionada.

#### __Parameters__

1. __Method__: Selecionar um método a ser aplicado. Com algoritmo island, a segmentação é fragmentada de acordo com conexões diretas. Com watershed, a segmentação é fragmentada de acordo com a transformada de distância e os parâmetros da seção _Advanced_.
2. __Size Filter__: Filtrar partições espúrias com eixo principal (feret_max) menor que o valor _Size Filter_.
3. __Smooth factor__: Fator de suavização, que é o desvio padrão do filtro gaussiano aplicado à transformada de distância. Conforme aumenta, menos partições serão criadas. Use valores menores para resultados mais confiáveis.
4. __Minimum distance__: Distância mínima separando picos em uma região de 2 * min_distance + 1 (i.e. picos são separados por no mínimo min_distance). Para encontrar o número máximo de picos, use min_distance = 0.
5. __Orientation line__: Selecionar a linha para ser usada para cálculo de ângulo de orientação.

#### __Output__

Digite um nome para ser usado como prefixo dos resultados (labelmap onde cada partição (elemento de poro) está em uma cor diferente, uma tabela com parâmetros globais e uma tabela com as diferentes métricas para cada partição).

#### Propriedades / Métricas:

1. __Label__: Identificador rotular da partição.
2. __mean__: Valor médio da imagem/volume de entrada dentro da região da partição (poro/grão).
3. __median__: Valor mediano da imagem/volume de entrada dentro da região da partição (poro/grão).
4. __stddev__:	Desvio padrão da imagem/volume de entrada dentro da região da partição (poro/grão).
5. __voxelCount__: Número total de pixels/voxels da região da partição (poro/grão).
6. __area__: Área total da partição (poro/grão). Unidade: mm^2.
7. __angle__: Ângulo em graus (entre 270 e 90) relacionado à linha de orientação (opcional; se nenhuma linha for selecionada, a orientação de referência é superior horizontal).
8. __max_feret__: Eixo de caliper de Feret máximo. Unidade: mm.
9. __min_feret__: Eixo de caliper de Feret mínimo. Unidade: mm.
10. __mean_feret__: Média entre os calipers mínimo e máximo.
11. __aspect_ratio__: 	min_feret / max_feret.
12. __elongation__:	max_feret / min_feret.
13. __eccentricity__:	sqrt(1 - min_feret / max_feret)	relacionado à elipse equivalente (0 <= e < 1), igual a 0 para círculos.
14. __ellipse_perimeter__: Perímetro da elipse equivalente (com eixo dado por caliper de Feret mínimo e máximo). Unidade: mm.
15. __ellipse_area__: Área da elipse equivalente (com eixo dado por caliper de Feret mínimo e máximo). Unidade: mm^2.
16. __ellipse_perimeter_over_ellipse_area__: Perímetro da elipse equivalente dividido pela área.
17. __perimeter__: Perímetro real da partição (poro/grão). Unidade: mm.
18. __perimeter_over_area__: Perímetro real dividido pela área da partição (poro/grão).
19. __gamma__: "Redondeza" de uma área calculada como 'gamma = perimeter / (2 * sqrt(PI * area))'.
20. __pore_size_class__: Símbolo/código/id da classe do poro.
21. __pore_size_class_label__: Rótulo da classe do poro.

#### Definição das classes de poro:

* __Microporo__: classe 0, max_feret menor que 0.062 mm.
* __Mesoporo mto pequeno__: classe 1, max_feret entre 0.062 e 0.125 mm.
* __Mesoporo pequeno__: classe 2, max_feret entre 0.125 e 0.25 mm.
* __Mesoporo médio__: classe 3, max_feret entre 0.25 e 0.5 mm.
* __Mesoporo grande__: classe 4, max_feret entre 0.5 e 1 mm.
* __Mesoporo muito grande__: classe 5, max_feret entre 1 e 4 mm.
* __Megaporo pequeno__: classe 6, max_feret entre 4 e 32 mm.
* __Megaporo grande__: classe 7, max_feret maior que 32mm.

### Label Map Editor

Realiza separação e aglutinação manual de objetos rotulados.

#### __Atalhos para ferramentas__

- m: Mesclar dois rótulos
- a: Dividir rótulo automaticamente usando watershed
- s: Dividir rótulo com uma linha reta
- c: Cortar rótulo no ponteiro do mouse
- z: Desfazer última edição
- x: Refazer edição desfeita
- Esc: Cancelar operação

## MicroTom

Esse módulo permite que usuários do _GeoSlicer_ usem algoritmos e métodos da biblioteca MicroTom, desenvolvida pela Petrobras.

__Métodos disponíveis__

* Pore Size Distribution
* Hierarchical Pore Size Distribution
* Mercury Injection capillary Pressure
* Stokes-Kabs Absolute Permeability on the Pore Scale

### Interface

#### __Inputs__

1. __Segmentation__: Selecione o labelmap ao qual o algoritmo de microtom será aplicado. Deve ser necessariamente um labelmap; nodos de segmentação não são aceitos (qualquer nodo de segmentação pode ser transformado em um labelmap na aba _Data_ clicando com o botão esquerdo do mouse no nodo).
2. __Region (SOI)__: Selecione um nodo de segmentação em que o primeiro segmento delimita a região de interesse onde a segmentação será realizada.
3. __Segments__: Selecione um segmento na lista para ser usado como o espaço de poro da rocha.

#### __Parameters__

1. __Select a Simulation__: Select one of the MicroTom algorithm in the list
2. __Store result at__: (optional) The user can define a specific folder to store the files.
3. __Execution Mode__: Local or Remote.
4. __Show (Jobs list)__: By clicking on "Show", the user can see a list of process sent to the remote cluster.

## Pore Network Environment

Ambiente para realizar operações de modelo de rede de poros (Pore Network Model).

Módulos:

- PN Extraction: Cria um modelo de rede de poros a partir de um volume binário ou rotulado.
- PN Simulation: Realiza simulações de fluxo monofásico ou bifásico em um PNM.
- Cycles Visualization: Visualiza passes de simulação bifásica.
- Production Prediction: Cria uma predição de produção com a equação de Buckley-Leverett a partir de resultados de Krel bifásico.