# Multicore

Módulo _GeoSlicer_ para processar, orientar e desdobrar testemunhos em lotes.

## Painéis e sua utilização

| ![Figura 1](../../assets/images/Multicore.png) |
|:-----------------------------------------------:|
| Figura 1: Módulo Multicore. |

### Seleção de dados

- _Add directories_: Adiciona diretórios que contenham dados de _core_. Esses diretórios irão aparecer na lista _Data to be processed_. Durante a execução, a pesquisa pelos dados ocorrerá em apenas um nível abaixo.

- _Remove_: Remove diretórios da lista de pesquisa.

- _Depth control_: Escolha do método de configurar os limites do _core_:
    - _Initial depth and core length_:
        - _Initial depth (m)_: Profundidade do topo do _core_.
        - _Core length (cm)_: Comprimento do _core_.
    - _Core boundaries CSV file_:
        - _Core depth file_: Seletor de um arquivo CSV que contém os limites do core em metros. O arquivo deve ter duas colunas, sendo que cada linha corresponde a um core diferente, na ordem de processamento. As colunas devem indicar, respectivamente, os limites de profundidade superior e inferior.

- _Core diameter (inch)_: Diâmetro aproximado do _core_ em polegadas.

### Processamento
Marque a opção que desejar executar:

- _Core radial correction_: Corrige efeitos de atenuação dos _core CT_, como por exemplo _beam hardening_. Aplica um fator de correção para todas as fatias da imagem (imagens transversais, plano xy) para uniformizar a atenuação em termos de coordenadas radiais. O fator de correção é calculado com base na média de todas as fatias e depende apenas da distância radial em relação ao centro das fatias.

- _Smooth core surface_: Aplica uma suavização (_anti-aliasing_) na superfície do _core_.

- _Keep original volumes_: Salva o dado original sem correções e sem suavização.

- _Process cores_: Processa os cores nos diretórios na ordem em que foram adicionados. Após carregados, os dados podem ser visualizados no módulo _Explorer_ 

### Orientação
- _Orientation algorithm_: Escolha um algoritmo de orientação do _core_:
    - _Surface_: A orientação é baseada no ângulo de corte longitudinal das extremidades do _core_. Essa opção é melhor em casos em que o ângulo de corte não é raso e se as extremidades estão bem preservadas (superfícies de corte mais limpas)
        
    - _Sinusoid_: Utiliza o desenrolamento de _core_ para encontrar os padrões sinusoidais criados pelas camadas deposicionais para orientar os _cores_. Esta opção é boa se as camadas deposicionais estiverem bem pronunciadas no grupo de _cores_.
        
    - _Surface + Sinusoid_: Se o algoritmo _Surface_ for capaz de encontrar um alinhamento, ele será utilizado; caso contrário, o algoritmo _Sinusoid_ será aplicado no lugar.
   
- _Orient cores_: Aplica rotação no eixo longitudinal do _core_, de acordo com o algoritmo selecionado. O primeiro _core_ determina a orientação dos próximos.

### Unwrap
- _Unwrap radial depth (mm)_: insira um valor que varia de 0 até o raio do _core_, em milímetros. Do lado externo do _core_ até o centro, ao longo do eixo radial, é a profundidade na qual o desenrolamento será gerado. Use valores pequenos se desejar desenrolar próximo à superfície do _core_.

- _Well diameter_: Insira o diâmetro aproximado do poço (maior que o diâmetro do _core_) que será utilizado para projetar a imagem do core para a parede do poço.

- _Unwrap cores_: Gera as imagens desenroladas do core. As imagens preservam a escala do core em todos os eixos. Desse modo o tamanho do pixel e upscaling não dependem do raio do _core_. O ângulo delta usado no processo iterativo de coleta de voxels desenrolados são definidos como tamanho_do_pixel/raio.

### Apply all
Aplica todos os passos de processamento, orientação e desenrolamento.

## Problemas Comuns

### "Could not detect core geometry"

O erro "Could not detect core geometry" ocorre no módulo `Multicore` quando a interface de linha de comando `CoreGeometryCLI` falha ao detectar uma geometria de testemunho válida no volume fornecido. Isso acontece porque a CLI não consegue encontrar feições circulares (representando o testemunho) nas fatias do volume usando técnicas de processamento de imagem.

Principais razões para este erro ocorrer:

### 1. **Nenhum Círculo de Testemunho Detectável no Volume**
   - A imagem do volume não contém uma estrutura de testemunho cilíndrica clara que possa ser identificada via detecção de círculos de Hough.
   - Causas possíveis:
     - O testemunho está obscurecido, danificado ou possui geometria irregular que não forma círculos detectáveis nas seções transversais.
     - Baixa qualidade de imagem, ruído ou artefatos impedem que a detecção de bordas funcione corretamente.

### 2. **Parâmetro de Raio do Testemunho Incorreto**
   - O valor de `coreRadius` passado para a CLI é impreciso, fazendo com que o intervalo do raio de busca (mín/máx) não corresponda ao tamanho real do testemunho na imagem.
   - O raio de busca é calculado como `[coreRadius - 3mm, coreRadius + 3mm]` em pixels. Se o raio real do testemunho estiver fora desse intervalo, nenhum círculo será detectado.
   - Os usuários devem verificar se o raio do testemunho corresponde às dimensões físicas da amostra carregando o volume original e medindo o raio.

### 3. **Fatias Válidas Insuficientes para Análise**
   - A CLI descarta 20 fatias de cada extremidade do volume para evitar "pontas de testemunho destruídas", e então amostra a cada 5ª fatia.
   - Se o volume tiver muito poucas fatias (ex: <40 no total), pode não haver fatias restantes para analisar após descartar as extremidades.
   - Se todas as fatias amostradas falharem na detecção de geometria (ex: devido à má qualidade de imagem nessas fatias), a lista de resultados permanece vazia.

### 4. **Filtragem de Detecção de Círculos**
   - Círculos detectados são filtrados se o centro deles estiver muito próximo do centro da imagem (dentro de 10% da dimensão mínima da imagem a partir do centro). Isso serve para evitar falsos positivos de artefatos centrais.
   - Se todos os círculos detectados forem filtrados por essa condição, nenhuma geometria válida será registrada.


### Passos de Solução de Problemas para Usuários
- **Verifique os Dados de Entrada**: Garanta que o volume seja uma imagem de testemunho válida com seções transversais circulares claras. Verifique as dimensões e o espaçamento do volume.
- **Ajuste o Raio do Testemunho**: Forneça um raio de testemunho preciso em metros. Se não tiver certeza, tente uma faixa de valores.
- **Verifique a Qualidade do Volume**: Carregue apenas a imagem original do testemunho para confirmar se ele está visível e não obscurecido.

Se o erro persistir, o volume pode não ser adequado para detecção automatizada da geometria do testemunho, e intervenção manual ou módulos alternativos podem ser necessários.