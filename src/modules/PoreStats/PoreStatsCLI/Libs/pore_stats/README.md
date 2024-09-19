# Estatísticas e propriedades de poros e partículas em seção delgada


Este repositório disponibiliza o *script* de cálculo de estatísticas e propriedades de poros e partículas (mais especificamente oóides) em imagens de seção delgada de rocha. Foi desenvolvido de modo a aproveitar alguns recursos do GeoSlicer e combinar com soluções próprias para a segmentação de poros e oóides e a geração de imagens e tabelas dos dados computados.


# Funcionamento


Veja [`workflow`](workflow/).


# Uso


## Dependências


O *script* requer o *PythonSlicer* para ser executado, para um aproveitamento apropriado dos recursos do GeoSlicer. Por isso, é necessário ter uma versão do GeoSlicer instalada.


Além disso, o `stardist`, um dos módulos requeridos, ainda não faz parte do *PythonSlicer* e deve ser instalado separadamente.


`<caminho-do-GeoSlicer>/bin/PythonSlicer -m pip install stardist`


## Dados


### Padrões testados


A princípio, o *script* foi desenvolvido para funcionar sobre as imagens dos poços RJS-661, RJS-702, TMT-1D e TVD-11D. Nos casos em que as versões de calcita tanto tingida quanto não tingida foram disponibilizados, apenas as tingidas foram consideradas.


### Formato esperado

Espera-se que as imagens de um mesmo poço estejam contidas em um mesmo diretório com seu nome. Ambas as versões de iluminação em polarização direta (PP ou c1) e polarização cruzada (PX ou c2) são necessárias, exceto para as imagens expecificadas no arquivo `not_use_px.csv`. As imagens devem ser nomeadas no padrão `<poço>_<profundidade-valor>(-índice-opcional)<profundidade-unidade>_<…>_c<1/2>.<extensão>`. Exemplo:

```
RJS-661
    |__ RJS-661_3009.50m_c1.jpg
    |__ RJS-661_3009.50m_c2.jpg
    |__ RJS-661_3013.00m_2.5x_c1.jpg
    |__ RJS-661_3013.00m_2.5x_c2.jpg
```


### Saída


No diretório de saída especificado no momento da execução, é criado um sub-diretório para cada tipo de instância abordado (atualmente poros e oóides). Dentro desses sub-diretórios, é criada uma pasta para cada imagem processada, herdando o nome da imagem. Dentro dessa pasta, são criados três arquivos:


* `AllStats_<nome-da-imagem>_<tipo-de-instância>.xlsx`: planilha contendo os valores das propriedades geológicas de cada instância detectada;
* `GroupsStats_<nome-da-imagem>_<tipo-de-instância>.xlsx`: agrupa as instâncias detectadas por similaridade de área e disponibliza diversas estatísticas descritivas calculadas sobre as propriedades desses grupos;
* `<nome-da-imagem>.png`: imagem que destaca as instâncias detectadas na imagem original colorindo-as aleatoriamente.


Em cada sub-diretório também é criada uma pasta `LAS`, contendo arquivos `.las` contendo estatísticas descritivas das instâncias de cada poço separadas por profundidade.


Exemplo:

```
RJS-661
    |__ ooids
    |   |__ LAS
    |   |   |_ las_max.las
    |   |   |_ las_mean.las
    |   |   |_ las_median.las
    |   |   |_ las_min.las
    |   |   |_ las_std.las
    |   |__ RJS-661_3009.50m_c1
    |       |__ AllStats_RJS-661_3009.50m_c1_ooids.xlsx
    |       |__ GroupsStats_RJS-661_3009.50m_c1_ooids.xlsx
    |       |__ RJS-661_3009.50m_c1.png
    |__ pores
        |__ LAS
        |   |_ las_max.las
        |   |_ las_mean.las
        |   |_ las_median.las
        |   |_ las_min.las
        |   |_ las_std.las
        |__ RJS-661_3009.50m_c1
            |__ AllStats_RJS-661_3009.50m_c1_pores.xlsx
            |__ GroupsStats_RJS-661_3009.50m_c1_pores.xlsx
            |__ RJS-661_3009.50m_c1.png
```


Opcionalmente, também se podem gerar imagens netCDF dos resultados. Elas estarão contidas no sub-diretório `netCDFs` no diretório de saída.


### Execução


```
<caminho-do-GeoSlicer>/bin/PythonSlicer pore_stats.py <diretório-entrada> <diretório-saída> [--algorithm {watershed,islands}] [--pixel-size TAMANHO_DO_PIXEL] [--min-size TAMANHO_MÍNIMO] [--sigma SIGMA] [--min-distance DISTÂNCIA_MÍNIMA] [--pore-model {unet,sbayes,bbayes}] [--reg-method {centralized,auto}] [--netcdf]

* <diretório-entrada>: caminho do diretório de entrada;
* <diretório-saída>: caminho do diretório de saída;
* --algorithm: algoritmo para separar os poros detectados em diferentes instâncias. "islands" os separa por simples conectividade de pixeis, enquanto "watershed" utiliza o algoritmo de mesmo nome. Padrão: "islands";
* --pixel-size: escala da imagem - tamanho do pixel em milímetros. Padrão: 1; 
* --min-size: mínimo tamanho (mm) do maior eixo (diâmetro máximo de Feret) de uma instância detectada para não ser descartada. Padrão: 0;
* --sigma: desvio padrão do filtro gaussiano aplicado à transformada de distância que precede a separação das instâncias. Ignorado para o algoritmo "islands". Padrão: 1;
* --min-distance: distância mínima (em pixeis) que separa picos nos segmentos a serem separados. Ignorado para o algoritmo "islands". Padrão: 5;
* --pore-model: modelo de segmentação binária de poros. Escolha entre "unet" (U-Net), "sbayes" (small-bayesian: modelo bayesiano de kernel pequeno small) ou "bbayes" (big-bayesian: modelo bayesiano de kernel grande), ou forneça o caminho do modelo diretamente (recomendado para versões de desenvolvimento (não-release) do GeoSlicer). Padrão: "unet";
* --max-frags: limita a quantidade máxima de fragmentos de rocha a serem analisados, do maior para o menor. Pode ser um número inteiro descrevendo a quantidade diretamente, "all" para considerar todos os fragmentos e "custom" para uma análise individual de cada imagem listada no arquivo "filter_images.csv" (use 0 para ignorar a imagem). Padrão: "custom";
* --keep-spurious: se especificado, detecções espúrias de poros não são removidas;
* --keep-residues: se especificado, bolhas e resíduos na resina de poro não são limpas;
* --use-px: opção de uso de imagem PX para auxiliar na limpeza da resina de poro. Se "none", apenas a imagem PP é usada. Se "all", ambas PP e PX são usadas. Se "custom", imagens que constem no arquivo "not_use_px.csv" não terão a imagem PX usada. Ignorado se --keep-residues for especificado. Padrão: "custom";
* --reg-method: método de registro das imagens PP e PX para "limpeza" da resina de poro na imagem. Se "centralized", as imagens serão sobrepostas de modo que o centro de cada compartilhará a mesma localização: recomendado quando as imagens parecem já estar naturalmente registradas. Se "auto", o algoritmo decidirá entre apenas centralizar as imagens como em "centralized" ou isolar a região precisa da rocha (descartar as bordas) antes: recomendado quando as imagens PP e PX têm dimensões diferentes e/ou não parecem se sobrepor naturalmente. Ignorado se --keep-residues for especificado. Padrão: "centralized";
* --no-images: se especificado, as imagens de saída ilustrando as instâncias detectadas não são geradas;
* --no-sheets: se especificado, as planilhas de propriedades e estatísticas não são geradas;
* --no-las: se especificado, os arquivos LAS de saída não são gerados;
* --seg-cli: caminho opcional do CLI de segmentação de poros a ser utilizado. Caso não seja especificado, é inferido automaticamente, o que é recomendado para versões release do GeoSlicer. Para versões de desenvolvimento, deve ser especificado. Padrão: inferir;
* --inspector-cli: caminho opcional do CLI de inspeção de segmento (separação e cálculo de propriedades/estatísticas das instâncias detectadas) de poros a ser utilizado. Caso não seja especificado, é inferido automaticamente, o que é recomendado para versões release do GeoSlicer. Para versões de desenvolvimento, deve ser especificado. Padrão: inferir;
* --netcdf: se especificado, salva os resultados das segmentações em um arquivo netCDF para cada imagem.
```

Durante a execução, um arquivo `checkpoint.txt` no diretório de saída é atualizado com a identificação da imagem atualmente em processamento. Caso a execução seja interrompida, a próxima execução retomará o processamento a partir desta.


### Recomendações


Seguem algumas dicas para executar o *script* sobre os lotes de imagens descritos [acima](#padroes-testados) ou similares:

* O *script* [`utils/isolate_data.py`](utils/isolate_data.py) transforma os lotes de imagens de seu formato original para o requerido.

`python utils/isolate_data.py <diretório-entrada> <diretório-saída>`

`<diretório-entrada>` precisa ser um diretório contendo as imagens de todos os poços separadas por sub-diretórios, cada um com o nome do respectivo poço.

* Durante os testes, normalmente esses parâmetros de entrada eram utilizados:
    * `--pore-model`: "bbayes";
    * `--pixel-size`: 0.00418 para o poço RJS-702 e 0.001379 para os demais;
    * `--reg-method`: "auto" para o poço RJS-702 e padrão ("centralized") para os demais;
    * valores padrão para os demais argumentos.


# Relatório geral


Considerando que os diretórios de saída de execuções feitas sobre diferentes poços estejam em um mesmo diretório, você pode executar o *script* [`utils/join_sheets.py`](utils/join_sheets.py) para gerar planilhas unificadas para todos os poços. Uma pasta `statistics` será gerada no diretório especificado, contendo as planilhas. 

`python utils/join_sheets.py <diretório>`

Exemplo (consulte [aqui](#saida) para melhor compreensão das nomenclaturas):

```
Diretório de resultados computados para cada poço
    |__ RJS-661
    |    |_ ...
    |__ RJS-702
    |    |_ ...
    |__ statistics
        |__ ooids
        |   |__ AllStats_ooids.xlsx
        |   |__ GroupsStats_ooids.xlsx
        |__ pores
            |__ AllStats_pores.xlsx
            |__ GroupsStats_pores.xlsx
```