# Core Environment

Ambiente para trabalhar com Tomografias Médicas de testemunhos (*Core CT*).

Módulos:

- Data
- Multicore
- Transforms (Multicore Transforms)
- Crop (Crop Volume)
- Segmentation

## Data

Módulo _GeoSlicer_ para visualizar os dados sendo trabalhados e suas propriedades.

## Multicore

Módulo _GeoSlicer_ para processar, orientar e extrair perfis tomográficos em lote.

Demo (versão antiga): [https://youtu.be/JBkeHx6obTY](https://youtu.be/JBkeHx6obTY)

Siga os passos abaixo para processar dados de core, orientar os cores e unwrap-os. Pode-se também exportar o resultados.

Números decimais usam ponto como separador, não vírgula.

### Process

1. Use o botão _Add directories_ para adicionar diretórios contendo dados de core. Esses diretórios aparecerão na área _Data to be processed_ (ao processar, uma busca por dados de core nesses diretórios ocorrá em subdiretórios abaixo em no máximo um nível). Pode-se também remover entradas indesejadas selecionando-as e clicando em _Remove_.

2. Escolha uma das maneiras de definir as produndidades do CoreCT: _Initial depth and core length_ ou _Core boundaries CSV file_. Para _Initial depth and core length_, insira a profundidade inicial (_Initial depth_) e o comprimento do core (_Core length_). Para _Core boundaries CSV file_, use o botão _..._ para adicionar o arquivo CSV contendo as boundaries do core (em metros). Um exemplo de arquivo CSV para dois cores seria:

   5000.00,  5000.90

   5000.90,  5001.80

   O CSV é um arquivo com duas colunas em que cada linha se refere a um core (em ordem de processamento, ver item 7), e as colunas se referem às profundidades limítrofes superior e inferior, sequencialmente.

3. Para _Core diameter_, insira o diâmetro aproximado do core (em milímetros).

4. Para _Core radial correction_, cheque para corrigir efeitos de atenuação CT transversais do core. Pode ser usado para corrigir efeitos como *beam hardening*. O objetivo é multiplicar um fator de correção a todas as fatias da imagem (fatias transversais, plano xy) para uniformizar os valores de atenuação em termos da coordenação radial. O fator de correção é calculado baseado na média de todas as fatias e depende apenas do raio relacionado ao centro das fatias.

5. Para _Smooth core surface_, cheque para analisar a superfície do core; ficará mais suave (antialiased) com essa opção ativada.

6. Para _Keep original volumes_, cheque para manter os dados carregados originais.

7. Clique no botão _Process cores_ e aguarde a finalização. A ordem de processamento é a seguintes: a ordem dos diretórios adicionados na área _Data to be loaded_, e cada subdiretório, se aplicável, é processado em ordem alfabética. Pode-se inspecionar os cores carregados na aba _Data_ do _Core Environment_, dentro do diretório _Core_.

#### __Detalhes sobre alinhamento e extração de cores__

Nas fatias dos dados de core originais, pode-se frequentemente encontrar três círculos, que são (do maior para o menor): a superfície exterior do *liner*, a superfície interior do *liner* e a superfície do core. A Transformada Circular de Hough é usada para detectar esses círculos, e então o menor é escolhido como representação da superfície do core, com informação sobre seu raio e posição. Usa-se a posição do círculo a partir das fatias para calcular a melhor linha que passa pelo centro do core (eixo longitudinal), usando SVD (decomposição em valores singulares). Isso permite construir um vetor unitário que deve ser rotacionado ao eixo Z applicando a matriz de transformação (rotação). Uma vez calculada, essa matriz de rotação é então aplicada ao dado. Uma matriz de translação também é usada para mover o centro do core à origem do sistema de coordenadas, e mais tarde, à sua profundidade configurada no eixo Z.

Após ser feito o alinhamento, todos os pontos fora de um cilindro envolvendo o core recebem o menor valor de intensidade do dado original. O raio desse cilindro é igual ao raio médio dos circulos do core detectados nas fatias

### Orient

1. Selecione o algoritmo de orientação em _Orientation algorithm_:
   
   - _Surface_ - a orientação é baseada no ângulo de corte da serra nas extremidades longitudinais do core. Esta opção funciona melhor se o ângulo de corte não for muito raso e as extremidades do core estiverem bem preservadas (ou seja, superfícies de corte limpas).
     
   - _Sinusoid_ - utiliza o perfil tomográfico para encontrar os padrões de sinusóides criados pelas camadas deposicionais/acamamento para orientação. Esta opção é boa se as camadas deposicionais estiverem bem pronunciadas no lote de cores.
     
   - _Surface + Sinusoid_ - se o algoritmo _Surface_ for capaz de encontrar um alinhamento, ele será usado, caso contrário, o algoritmo _Sinusoid_ será aplicado
   
2. Clique no botão _Orient cores_ e aguarde a conclusão. Os cores serão rotacionados ao longo de seu eixo longitudinal, de acordo com o algoritmo de orientação selecionado. O primeiro core (o de menor profundidade) dita a orientação dos subseqüentes.

### Unwrap (Perfil tomográfico)

1. Para _Unwrap radial depth_, insira um valor de 0 ao raio do core, em milímetros. De fora do core até o centro, ao longo do eixo radial, é a profundidade na qual o unwrap será gerado. Valores pequenos gerarão unwraps próximos à superfície do core.

2. Para _Well diameter_, insira o valor aproximado do diâmetro do poço (maior que o diâmetro do core) que será usado para projetar a image do core na parede do poço.

3. Clique _Unwrap cores_ e aguarde a finalização. Unwraps de cores individuais e o unwrap global do poço serão gerados. As imagens de unwrap preservam as escalas originais do core em todos os eixos. Portanto, o tamanho/upscaling do pixel não depende do raio do core, i.e. o ângulo delta usado no processo iterativo de coleta dos voxels do unwrap são definidos como pixel_size/radius.

Pode-se também realizar todos os passos acima clicando no botão _Apply all_.

### Export

Opcionalmente, pode-se exportar o sumário _Multicore_, as fatias centrais do core em cada eixo, e os unwraps do core clicando em seus respectivos botões na aba _Export_. Essa aba exporta um arquivo CSV de duas colunas, onde a primeira representa as profundidades e a segunda as intensidades de CT da imagem. Esse formado pode ser importado diretamente no software Techlog.

Outra maneira de exportar as imagens é usando o módulo _Export_ do _GeoSlicer_. É sugerível usar a extensão .nc pois tanto a imagem quanto o espaçamento/tamanho do pixel e a profundidade inicial são exportados.

## Multicore Transforms

Módulo _GeoSlicer_ para alterar orientação e profundidade de cores manualmente, conforme descrito nos passos abaixo:

1. Selecione cores a serem transformados na área _Available volumes_ e clique na seta verde para a direita para movê-los para a área _Selected volumes_, à direita. Pode-se também remover cores da área _Selected volumes_ usando a seta para a esquerda.

2. Ajuste a translação e a rotação conforme necessário. Pode-se prever essas mudanças em _Slice views_.

3. Clique em _Apply_ para salvar as mudanças. Clicar em _Cancel_ desfará a transformação.

## Crop Volume

Módulo _GeoSlicer_ para cortar um volume, conforme descrito nos passos abaixo:

1. Selecione o volume em _Volume to be cropped_.

2. Ajuste a posição e tamanho desejados da ROI nas slice views.

3. Clique em _Crop_ e aguarde a finalização. O volume cortado aparecerá no mesmo diretório que o volume original.

## Segmentation

### Manual Segmentation

1. Selecione/crie um nodo de segmentação de saída. O usuário pode criar uma nova segmentação ou editar uma segmentação previamente definida.
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

Este módulo provê múltiplos métodos para analisar uma imagem segmentada. Particularmente, algoritmos Watershed e Islands permite fragmentar a segmentação em diversas partições, ou diversos segmentos. Normalmente é aplicado a segmentação de espaço de poros  para computar as métricas de cada elemento de poro. A entrada é um nodo de segmentação ou volume labelmap, uma região de interesse (definida por um nodo de segmentação) e a imagem/volume mestre. A saída é um labelmap onde cada partição (elemento de poro) está em uma cor diferente, uma tabela com parâmetros globais e uma tabela com as diferentes métricas para cada partição.

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
19. __gamma__: "Redondeza"  de uma área calculada como 'gamma = perimeter / (2 * sqrt(PI * area))'.
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
