## Interactive Segmenter

O módulo **Interactive Segmenter** fornece uma ferramenta de segmentação supervisionada para imagens 3D com uma pré-visualização em tempo real. Ele permite que os usuários anotem uma pequena porção de uma imagem e vejam o resultado da segmentação ser atualizado instantaneamente em uma visualização paralela, facilitando um treinamento de modelo rápido e intuitivo.

### Uso

O fluxo de trabalho foi projetado para ser interativo, fornecendo feedback imediato sobre as anotações do usuário.

#### Passo 1: Selecionar Imagem de Entrada

1.  Na seção **Input**, selecione o volume que você deseja segmentar usando o seletor **Input Image**.
2.  Se a imagem for muito grande (por exemplo, maior que 700³ voxels), é recomendado recortar a imagem primeiro para obter um melhor desempenho. Você pode recortar a imagem usando o módulo Crop. A segmentação pode ser aplicada à imagem completa, sem recortes, posteriormente.

#### Passo 2: Iniciar Anotação

1.  Clique no botão **Start Annotation**.
2.  O layout da tela mudará para uma visualização lado a lado. A visualização da esquerda é para anotação, e a da direita exibirá a pré-visualização da segmentação em tempo real.
3.  O módulo começará a calcular um cache de características em segundo plano. Uma barra de progresso indicará o status. As ferramentas de anotação serão habilitadas assim que este processo for concluído.

| ![Layout](/assets/images/InteractiveSegmenter.png) |
|:---:|
| Figura 1: Layout lado a lado para anotação (esquerda) e pré-visualização (direita). |

#### Passo 3: Anotar a Imagem

1.  Use as ferramentas simplificadas do **Segment Editor** na seção **Annotation** para criar segmentos e desenhar anotações na imagem na **visualização da esquerda**. As principais ferramentas disponíveis são `Paint`, `Draw` e `Erase`.
2.  Conforme você anota, um modelo Random Forest é treinado em segundo plano. O resultado da segmentação será atualizado em tempo real na **visualização da direita**.
3.  Crie pelo menos dois segmentos e forneça exemplos para cada um para obter um resultado significativo.

!!! note "Dica"
    Anote várias características da imagem para um resultado melhor. Inclua as fronteiras entre os segmentos esperados e outras regiões potencialmente ambíguas. Itere corrigindo quaisquer regiões classificadas incorretamente que você veja na pré-visualização.

#### Passo 4: Ajustar o Conjunto de Características (Opcional)

1.  Na seção **Annotation**, você pode selecionar um **Feature Set** no menu suspenso. Esses pré-ajustes controlam o conjunto de características da imagem usadas para treinar o classificador, afetando a suavidade e o detalhe do resultado da segmentação.
2.  Os pré-ajustes disponíveis são:
    *   **Sharp**: Prioriza detalhes finos.
    *   **Balanced**: Um bom ponto de partida para a maioria das imagens.
    *   **Smooth**: Cria um resultado mais suave, ignorando pequenas variações.
    *   **Extra Smooth**: Resultados ainda mais suaves.
    *   **Complete**: Usa todas as características disponíveis.
3.  Mudar o pré-ajuste irá acionar um novo treinamento do modelo, e a pré-visualização será atualizada de acordo.

#### Passo 5: Aplicar à Imagem Completa

1.  Quando estiver satisfeito com a pré-visualização, vá para a seção **Output**.
2.  (Opcional) Se você deseja aplicar a segmentação a uma imagem diferente (por exemplo, o volume original, sem recortes), selecione-a no seletor **Inference Image**. Se nenhuma imagem for selecionada, a imagem de entrada original será usada.
3.  Clique no botão **Apply to Full Image**. O modelo treinado será aplicado a todo o volume selecionado.
4.  Uma barra de progresso mostrará o status da segmentação completa. Quando concluído, o layout lado a lado será fechado e um novo nó de segmentação será adicionado à cena.

Para interromper a sessão interativa a qualquer momento, clique no botão **Cancel**. Suas anotações serão salvas em um nó de segmentação, e você poderá retomar a sessão mais tarde, iniciando o módulo novamente com a mesma imagem de entrada.

### Método

O Interactive Segmenter usa um classificador **Random Forest**, um algoritmo de aprendizado de máquina que constrói múltiplas árvores de decisão para fazer uma predição robusta para cada voxel. O classificador é treinado em um conjunto de características de imagem calculadas a partir do volume de entrada.

#### Características

As seguintes características são calculadas a partir da imagem de entrada para treinar o modelo. O usuário pode escolher quais características usar através dos pré-ajustes do **Feature Set**.

*   **Raw Image**: A intensidade original do voxel.
*   **Gaussian Filter**: Uma versão suavizada da imagem. O módulo calcula isso com quatro valores de `sigma` diferentes (1, 2, 4 e 8), criando características que capturam informações em diferentes escalas.
*   **Window Variance**: A variância local das intensidades dos voxels dentro de uma janela 3D. Isso é útil para a discriminação de texturas. O módulo calcula isso com três tamanhos de janela diferentes (5x5x5, 9x9x9 e 13x13x13).

#### Pré-ajustes de Características

Os pré-ajustes combinam essas características para alcançar resultados diferentes:

*   **Sharp**: Raw Image, Gaussian (sigma=1, 2), Window Variance (5x5x5).
*   **Balanced**: Raw Image, Gaussian (sigma=1, 2, 4), Window Variance (5x5x5, 9x9x9).
*   **Smooth**: Gaussian (sigma=1, 2, 4, 8), Window Variance (5x5x5, 9x9x9).
*   **Extra Smooth**: Gaussian (sigma=2, 4, 8), Window Variance (5x5x5, 9x9x9).
*   **Complete**: Todas as características calculadas.

### Módulos Relacionados

Para tarefas de segmentação mais avançadas, considere o módulo [AI Segmenter](/Volumes/Segmentation/Segmentation.md#ai-segmenter). Ele também usa um classificador Random Forest, mas oferece mais opções de características e diferentes métodos de treinamento, embora não forneça uma pré-visualização em tempo real.