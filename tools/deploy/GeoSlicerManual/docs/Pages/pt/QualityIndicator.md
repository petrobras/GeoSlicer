## Quality Indicator

Perfis de imagem de poço podem ser afetados por problemas durante a aquisição, como a excentricidade da ferramenta (quando a ferramenta não está centralizada no poço) e a espiralização (quando a ferramenta gira enquanto se move). Esses problemas introduzem artefatos nos dados que podem prejudicar a interpretação.

O módulo Indicador de Qualidade calcula um índice para quantificar a presença e a intensidade desses artefatos em uma imagem, permitindo ao usuário avaliar a qualidade dos dados.

### Teoria

O indicador é calculado com base na transformada de Fourier 2D da imagem de entrada, processada em janelas deslizantes ao longo da profundidade. O método calcula a média do espectro de amplitude dentro de uma banda de frequência específica, que é comumente associada aos efeitos de excentricidade e espiralização (comprimentos de onda verticais entre 4 e 100 metros e comprimento de onda horizontal de 360 graus).

O resultado é um valor normalizado entre 0 e 1:

-   Valores próximos de 0 indicam baixa presença de artefatos (alta qualidade).
-   Valores próximos de 1 indicam alta presença de artefatos (baixa qualidade).

### Como Usar

#### Entrada (Input)

-   **Tempo de Trânsito (Transit Time):** Selecione a imagem de entrada para a análise. Embora o rótulo sugira "Tempo de Trânsito", qualquer imagem de perfil pode ser usada. No entanto, os artefatos de excentricidade e espiralização são geralmente mais evidentes em imagens de tempo de trânsito.

#### Parâmetros (Parameters)

-   **Tamanho da janela (m) (Window size):** Define o tamanho (altura) da janela deslizante em metros usada para calcular o indicador ao longo do poço.
-   **Comprimento de onda mínimo (m) (Minimum wavelength):** O comprimento de onda vertical mínimo, em metros, a ser considerado como parte do efeito de espiralização.
-   **Comprimento de onda máximo (m) (Maximum wavelength):** O comprimento de onda vertical máximo, em metros, a ser considerado.

#### Configurações Avançadas (Advanced Settings)

-   **Fator de filtragem (Filtering factor):** Um fator multiplicativo para o filtro. Um valor de `0` não aplica nenhuma filtragem, enquanto `1` aplica a filtragem máxima.
-   **Passo do espectro da banda (Band spectrum step length):** Controla a suavidade da transição (roll-off) da banda do filtro no domínio da frequência. Valores maiores resultam em uma transição mais suave.

#### Saída (Output)

-   **Prefixo de saída (Output prefix):** Define o prefixo para o nome do resultado gerado.
-   **Saída como imagem (Output as image):** Controla o formato do resultado.
    -   **Marcado:** O resultado é uma imagem (com as mesmas dimensões da entrada) onde o valor de cada pixel é o indicador de qualidade (entre 0 e 1).
    -   **Desmarcado:** O resultado é uma tabela com duas colunas: `DEPTH` (Profundidade) e `QUALITY` (Qualidade), que pode ser visualizada como uma curva.

    !!! note "Nota sobre a Saída em Tabela"
        Para otimizar o desempenho, os dados na tabela são uma versão subamostrada (reduzida em 10 vezes) da curva de qualidade de resolução total. A saída como imagem contém os dados em resolução total.

#### Execução

-   **Apply:** Inicia o cálculo do indicador de qualidade.
-   **Cancel:** Interrompe um processo em andamento.
