## Módulo SinGAN

O Módulo _SinGAN_ oferece uma interface para a utilização dos modelos SinGAN dentro do GeoSlicer...


### Painéis e sua utilização

| ![Figura 1](../../assets/images/SinGANModule.png) |
|:-----------------------------------------------:|
| Figura 1: Apresentação do módulo SinGAN. |

### Parâmetros

#### Configuração do modelo:

 - _Select Model_: Escolha do modelo a ser utilizado. Apenas modelos válidos são listados, dentro do diretório de modelos de SinGAN configurado pelo usuário.
 
 - _Create TI from model_: Reconstrói a imagem de treinamento como um volume dentro do _Geoslicer_

#### Imagem condicionante

 - _Hard Data Image_: Seleciona a imagem condicionante a ser usada durante a geração.

 - _Choose scale to use HD_: Caso selecionado a imagem condicionante é injetada apenas na escala escolhida. Se desabilitado, a imagem é injetada na primeira escala disponível e depois redimensionada para as próximas escalas.

 - _Create Hard Data preview_: Cria uma prévia da imagem condicionante nas escalas de injeção.

#### BIG IMAGE:
 - _Select a method_: Escolha o método de geração de grandes imagens.
    1. _Generation patch on gpu_:Todo o processamento é realizado inteiramente na RAM e na GPU, sem divisão em patches nem gravação em disco.
    2. _Patch Inference_: Gera a imagem processando-a em pequenos pedaços (patches), utilizando o disco para armazenar dados intermediários. É ideal para imagens muito grandes que não cabem na memória RAM.
    3. _Early crop_: Gera a imagem recursivamente, redimensionando a imagem de entrada para cada escala e extraindo o *patch* correspondente.
    4. _By chunks_: Divide a imagem em blocos (chunks) maiores definidos pelo usuário, processando cada um individualmente. É uma abordagem para lidar com imagens grandes, oferecendo um balanço entre o uso de memória e o tempo de processamento.
    
 - _Set number of chunk_: Define o número de blocos em cada dimensão no método _By chunks_ 

#### Output
 - _Number of realizations_: Números de imagens a serem geradas.
 
 - _Output Prefix_: Nome dos volumes gerados

 - _Save_: Forma que as imagens simuladas serão salvas no Geoslicer.
    1. _As Large Image node_: Um _large image node_ vai ser automaticamente adicionado. Acesse [Big Image](/Volumes/BigImage/BigImage.md) para mais informações sobre sse _node_.
    1. _As volume_: É gerado um volume individual para cada realização. Apenas para o método _Generation patch on cpu_.
    An individual volume is generated for each realization. Available when there is enough memory to load output image.
    2. _As sequence_: É gerado uma sequência de volumes que contém todas as realizações. Opção só é disponível para mais de uma realização e para o método _Generation patch on cpu_.
    3. _As NetCDF files_: As imagens geradas são salvas como arquivos .nc. Obrigatório para grandes imagens.
 - _Export directory_: Diretório que as imagens NetCDF serão salvas.

