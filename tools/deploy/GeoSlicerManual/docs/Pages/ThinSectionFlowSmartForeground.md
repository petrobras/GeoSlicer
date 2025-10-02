## Smart Foreground

Efeito *Smart foreground* para segmentar a área útil da amostra em uma imagem ou volume. O passo-a-passo de utilização está dividido em duas etapas:

1.  **Operação**: considera útil toda área da imagem/volume que não corresponda às bordas.
2.  **Fragmentação (opcional)**: eventuais fissuras entre fragmentos da amostra também deixam de ser consideradas área útil. Disponível apenas para imagens 2D (lâminas) e recomendável apenas para lâminas de luz polarizada plana (PP).

### Operação

{{ video("segment_editor_smart_foreground_public.webm", caption="Vídeo: Primeiro Plano Inteligente. Lâmina adaptada de [Luo *et al.*, 2022](https://onlinelibrary.wiley.com/doi/10.1155/2022/8328764) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).") }}

1.  Defina a imagem de entrada e segmentação de saída conforme o [tutorial de uso do *Segment Editor*](./SegmentEditor.md). Criar segmentação/segmentos não é necessário caso prefira editar segmentos já existentes.
2.  Selecione o efeito *Smart foreground*.
3.  Selecione o segmento ao qual a operação será aplicada.
4.  Em *Operation*, selecione uma das operações:
    *   *Fill inside*: preenche o segmento sobre a área útil da amostra.
    *   *Erase outside*: exclui áreas já segmentadas sobre a área não-útil da amostra.
5.  Caso deseje aplicar a fragmentação (se disponível), prossiga com os passos abaixo. Caso contrário, certifique-se que a seção *Fragments* (abaixo de *Operation*) esteja indisponível ou que a opção *Split* esteja desmarcada, clique em *Apply* e aguarde o fim do processo.

### Fragmentação

6.  Em *Fragments*, marque a opção *Split*.
7.  Selecione uma das opções:
    *   *Keep all*: mantém todos os fragmentos.
    *   *Filter the largest*: mantém apenas os fragmentos de maior área. Digite a quantidade de fragmentos a preservar.
8.  Caso utilize a **versão pública do GeoSlicer**, um campo *Annotations* deve estar visível, e os passos a seguir deverão ser executados. Caso contrário, pule este passo.
    *   Adicione dois novos segmentos à segmentação de saída. Alternativamente, você pode criar uma nova segmentação com dois segmentos.
    *   Selecione um dos novos segmentos criados. Utilize efeitos de marcação como [Desenho (*Draw*)](./SegmentEditor.md#desenho), [Pintura (*Paint*)](./SegmentEditor.md#pintura) ou [Tesoura (*Scissors*)](./SegmentEditor.md#tesoura) para demarcar pequenas amostras da textura da rocha.
    *   Selecione o outro novo segmento. Demarque agora pequenas amostras da resina de poro na imagem.
    *   Retorne ao efeito *Smart foreground* e reselecione o segmento ao qual a operação será aplicada.
    *   Em *Annotations*, selecione a segmentação que contém os segmentos demarcados.
    *   Em *Texture samples* e *Resin samples*, selecione os segmentos que demarcam, respectivamente, a textura e a resina.
9.  Clique em *Apply* e aguarde o fim do processo.
