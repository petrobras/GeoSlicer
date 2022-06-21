# Ambiente Thin Section

Ambiente para trabalhar com seções delgadas.

Módulos:

- Data
- Loader (Thin Section Loader)
- QEMSCAN Loader
- Crop (Crop Volume)
- Registration (Thin Section Registration)
- Segmentation

## Data

Módulo _GeoSlicer_ para visualizar os dados sendo trabalhados e suas propriedades.

## Thin Section Loader

Módulo _GeoSlicer_ para carregar imagens de seção delgada em lotes, conforme descrito nos passos abaixo:

1. Use o botão _Add directories_ para adicionar diretórios contendo dados de seção delgada. Esses diretórios apareceção na área _Data to be loaded_ (uma busca por dados de seção delgada nesses diretórios ocorrerá em subdiretórios abaixo em no máximo um nível). Pode-se também remover entradas indesejadas selecionando-as e clicando em _Remove_.

2. Defina o tamanho do pixel (_Pixel size_) em milímetros.

3. Opcionalmente, ative _Try to automatically detect pixel size_. Se funcionar, o tamanho de pixel detectado substituirá o valor configurado em _Pixel size_.

4. Clique no botão _Load thin sections_ e aguarde o carregamento ser finalizado. As imagens carregadas podem ser acessadas na aba _Data_, dentro do diretório _Thin Section_.

## QEMSCAN Loader

Módulo _GeoSlicer_ para carregar imagens QEMSCAN em lotes, conforme descrito nos passos abaixo:

1. Use o botão _Add directories_ para adicionar diretórios contendo dados QEMSCAN. Esses diretórios aparecerão na área _Data to be loaded_ (uma busca por dados QEMSCAN nesses diretórios ocorrerá em subdiretórios abaixo em no máximo um nível). Pode-se também remover entradas indesejadas selecionando-as e clicando em _Remove_.

2. Selecione a tabela de cores (_Lookup color table_). Pode-se selecionar a tabela padrão (_Default mineral colors_) ou adicionar uma nova tabela clicando no botão _Add new_ e selecionando um arquivo CSV. Tem-se também a opção de fazer o carregador buscar por um arquivo CSV no mesmo diretório que o arquivo QEMSCAN sendo carregado. Também há a opção _Fill missing values from "Default mineral colors" lookup table_ para preencher valores faltantes.

3. Defina o tamanho do pixel (_Pixel size_) em milímetros.

4. Clique no botão _Load QEMSCANs_ e aguarde o carregamento ser finalizado. Os QEMSCANs carregados podem ser acessados na aba _Data_, dentro do diretório _QEMSCAN_.

## Crop Volume

Módulo _GeoSlicer_ para cortar um volume, conforme descrito nos passos abaixo:

1. Selecione o volume em _Volume to be cropped_.

2. Ajuste a posição e tamanho desejados da ROI nas slice views.

3. Clique em _Crop_ e aguarde a finalização. O volume cortado aparecerá no mesmo diretório que o volume original.

## Image Tools

Módulo _GeoSlicer_ que permite manipulação de imagens, conforme descrito abaixo:

1. Selecione a imagem em _Input image_.

2. Selecione a ferramenta em _Tool_ e faça as mudanças desejadas.

3. Clique no botão _Apply_ para confirmar as mudanças. Essas mudanças não são permanentes e podem ser desfeitas clicando no botão _Undo_; e serão descartadas se o módulo for deixado sem serem salvas ou for clicado o botão _Reset_ (isso reverterá a imagem ao seu último estado salvo). Mudanças podem ser tornadas permanentes clicando no botão _Save_ (isso alterará a imagem e não pode ser desfeito).

## Thin Section Registration

Módulo _GeoSlicer_ para registrar imagens de seção delgada e QEMSCAN, conforme descrito nos passos abaixo:

1. Clique no botão _Select images to register_. Uma janela de diálogo aparecerá que permite a seleção da imagem fixa (_Fixed image_) e a imagem móvel (_Moving image_). Após selecionar as imagens desejadas, clique no botão _Apply_ para iniciar o registro.

2. Adicione Landmarks (pontos de ancoragem) às imagens clicando em _Add_ na seção _Landmarks_. Arraste os Landmarks conforme desejado para match  as mesmas localizações em ambas as imagens. Pode-se usar as várias ferramentas da seção _Visualization_ e a ferramenta window/level localizada na barra de ferramentas para auxiliá-lo nessa tarefa.

3. Após concluir a colocação dos Landmarks, pode-se clicar no botão _Finish registration_. Transformações serão aplicadas à imagem móvel para corresponder à imagem fixa, e o resultado será salvo em uma nova imagem transformada no mesmo diretório da imagem móvel. Pode-se também cancelo todo o processo de registro clicando no botão _Cancel registration_.

## Segmentation

### Manual Segmentation

1. Selecione o nodo (?) de segmentação de saída. O usuário pode criar uma nova segmentação ou editar uma segmentação previamente definida.
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