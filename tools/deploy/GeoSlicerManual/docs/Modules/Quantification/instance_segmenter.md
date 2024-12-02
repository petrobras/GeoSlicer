# Image Log Instance Segmenter

## Introdução

A análise quantitativa de dados de perfis de imagens é de grande importância na indústria de óleo e gás. Esta análise se destaca na
caracterização de reservatórios que apresentam grande variabilidade de escalas de poros, como os carbonatos do pré-sal. Frequentemente,
apenas a porosidade matricial das rochas não é suficiente para caracterizar as propriedades de escoamento de fluidos nesses reservatórios.
De fato, a presença de regiões sujeitas a intensa carstificação e de rochas com porosidade vugular significativa governam o comportamento
dos fluidos nesses reservatórios. Por sua natureza e escala, os perfis de imagem se destacam como uma importante ferramenta para melhor
entendimento e caracterização mais acurada dessas rochas.

Entretanto, o uso quantitativo dessas imagens é um desafio devido ao grande número de artefatos como espiralamento, breakouts,
excentricidade, batentes, marcas de broca ou de amostragem, entre outros. Portanto, a correta interpretação, identificação e correção desses
artefatos é de crucial importância.

Neste contexto, são utilizadas técnicas de aprendizado de máquina e visão computacional para automatização e auxílio nos processos de
análise das imagens de perfis de poços.

Image Log Instance Segmenter é um módulo do GeoSlicer que realiza a segmentação por instância de artefatos de interesse em imagens de log.
Segmentação por instância significa que os objetos são separados individualmente uns dos outros, e não somente por classes. No GeoSlicer
estão disponíveis por ora a detecção de dois tipos de artefatos:

- Marcas de amostragem
- Batentes

Após executado, um modelo gera um nodo de segmentação (labelmap) e uma tabela com propriedades de cada instância detectada, que podem ser
analisadas utilizando-se o módulo Instance Editor, presente no ambiente Image Log.

## Marcas de amostragem

Para marcas de amostragem, é utilizada a [Mask-RCNN](https://github.com/matterport/Mask_RCNN), uma rede convolucional de alto desempenho designada para detecção por instância em
imagens tradicionais RGB. Apesar das imagens de perfil não possuírem os três canais RGB, a entrada da rede foi adaptada para analisar os
logs de Tempo de Trânsito e de Amplitude como dois canais de cores para o treinamento da rede.

Estão disponíveis dois modelos treinados para a detecção de marcas de amostragem: um modelo primário e um modelo secundário, de testes. O
objetivo de existir um modelo secundário é permitir que os usuários confrontem os dois modelos de modo a determinar qual é o melhor,
possibilitando o descarte do pior modelo e a inclusão de futuros modelos concorrentes em novas versões do GeoSlicer.

Este modelo gera uma tabela com as seguintes propriedades para cada marca de amostragem detectada:

- Depth (m): profundidade real em metros.

- N depth (m): profundidade nominal em metros.

- Desc: número de descida.

- Cond: condição da marca.

- Diam (cm): diâmetro equivalente, o diâmetro de um círculo com a mesma área de marca.
$$D = 2 \sqrt{\frac{area}{\pi}}$$

- Circularity: circularidade, uma medida de quão próxima de um círculo a marca é, quanto mais próximo de 1, dado pela equação:
$$C=\frac{4 \pi \times area}{perimetro^2}$$

- Solidity: solidez, uma medida da convexidade da marca, quanto mais próximo de 1, dada pela equação:
$$S=\frac{area}{area\text{_}convexa}$$

| ![Figura 1](area_vs_areaconvexa.png) |
|:-----------------------------------------------:|
| Figura 1: Área versus área convexa (em azul). |

- Azimuth: posição horizontal em graus ao longo da imagem, 0 a 360 graus.

- Label: identificador da instância na segmentação resultante.

## Batentes

Para os batentes, são utilizadas técnicas de visão computacional tradicional, que identificam marcas diagonais nas imagens de tempo de
trânsito, características dos batentes.

- Depth (m): profundidade real em metros.
- Steepness: medida em graus da inclinação do batente em relação ao eixo horizontal.
- Area (cm²): área em centímetros quadrados.
- Linearity: o quanto o batente se parece com uma linha reta.
- Label: o identificador da instância na segmentação resultante.
