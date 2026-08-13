## Histograms Per Depth

O módulo **PSD Per Depth** permite, partindo da imagem de saída do módulo Histograms Per Depth - onde o valor de cada pixel representa o tamanho de poro naquela posição -, visualizar a distribuição de tamanho de poros na forma de uma série de histogramas, dispostos ao longo das profundidades.

### Painéis e sua utilização

| ![Figura 1](../../assets/images/PSDPerDepth1.png) |
| :-----------------------------------------------: |
|  Figura 1: Apresentação do módulo Histograms Per Depth.  |

#### A interface do módulo Histograms Per Depth é organizada em algumas seções:

1. **Input:**
    
    - **Input PSD Image:** imagem de saída do módulo Histograms Per Depth - onde o valor de cada pixel representa o tamanho de poro naquela posição. Ao selecionar uma imagem, ele é automaticamente aberta em uma nova vista caso ainda não esteja sendo exibida (imagem da esquerda na _Figura 2)_.

2. **Parameters:**
    
    - __Presets__: Diferentes combinações dos parâmetros abaixo (depth intervals, number of bins, horizontal scale) podem ser salvas e carregadas como presets.
    - __Depth intervals (m)__: O intervalo de profundidades sobre o qual cada histograma será calculado. Por exemplo, se uma imagem de entrada tem 10m e _Depth Intervals_ tem o valor 2m, o cálculo resultará em 5 histogramas - o primeiro cobrindo 0-1m, o segundo 2-3m, ..., até 8-9m.
    - __Smooth ON/OFF__: Aplicação opcional de um filtro Savitzky-Golay para suavização dos histogramas.
    - __Smooth degree__: Grau de suavização dos histogramas.
    - __Log X axis__: Alterna a escala horizontal dos histogramas entre modo linear e logarítmico. O eixo horizontal representa os tamanhos de poro em mm.


    Advanced (modifique com cautela):

    - __Internal binning in log scale__: Por uma razão geométrica, a distribuição dos tamanhos de poro é mais diversa para valores menores (muitos círculos pequenos ocupam a mesma área de um círculo grande...). Por isso, os tamanhos de poro são, por padrão, distribuídos de forma logarítmica, proporcionando melhor resolução para poros pequenos.
    - __Number of histogram bins__: Controla a resolução horizontal dos histogramas - quanto mais bins, maior a resolução. O eixo horizontal representa os tamanhos de poro em mm. O aumento da resolução para uma valor além do padrão aumenta o tempo de cálculo.
    
    - __Reload Preset Values__: Restaura os valores dos Parâmetros para os do preset atualmente selecionado.
    - __Reload Default Values__: Restaura os valores dos Parâmetros para os padrões do módulo.

    Binning interno em escala logarítmica: 

3. **Output:**

    Define o prefixo para o nó de saída. Por padrão o prefixo recebe o mesmo nome do nó de segmentação de entrada com o sufixo `_PSDPerDepth`.

### Saída

| ![Figura 2](../../assets/images/PSDPerDepth2.png) |
| :-----------------------------------------------: |
|  Figura 2: Resultado de um cálculo do Histograms Per Depth, exibido como histogramas na vista da direita. Na vista da esquerda vemos a imagem de input. Na vista central, o resultado de um cálculo de Histograms Per Depth, exibido como histogramas. À direita, outra vista gerada pelo botão Create New (a partir desse momento, essa vista será atualizada a cada alteração de parâmetro, enquanto a vista central permanecerá como está). Na vista à esquerda vemos a imagem PSD de input. |

Após a execução bem-sucedida, o módulo gerará e exibirá em uma nova vista uma imagem composta por uma série de histogramas (_Figura 2_, na vista central), conforme os parâmetros definidos no módulo. Toda alteração em um parâmetro aciona automaticamente o recálculo dos histogramas.

Clicar em Create New gera uma nova vista de histogramas. A partir desse momento, as alterações nos parâmetros serão aplicadas apenas a essa nova vista — permitindo ao usuário fazer comparações.