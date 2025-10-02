## Simulação de Permeabilidade Relativa (Krel)

### Simulação única de Krel (animação)
{{ video("pnm_krel_animation.webm", caption="Video: Fluxo para simulação de permeabilidade relativa com animação.") }}

O fluxo abaixo permite simular e obter uma animação dos processos de **Drenagem** e **Embibição**:

1.  **Carregue** o volume no qual deseja executar a simulação;
2.  Realize a **Segmentação Manual** utilizando um dos segmentos para designar a região porosa da rocha;
3.  Separe os segmentos utilizando a aba **Inspector**, delimitando assim a região de cada um dos poros;
4.  Utilize a aba **[Extraction](./PoreNetworkExtractor.md)** para obter a rede de poros e ligações a partir do volume LabelMap gerado;
5.  Na aba **[Simulation](./PoreNetworkSimulation.md#two-phase)**;
6.  Marque a opção **"Create animation node"** na caixa **["Simulation options"](./PoreNetworkSimulation.md#simulation-options)** e clique no botão **"Apply"**;
7.  Ao finalizar a simulação, vá até a aba **"Cycles Visualization"** e selecione o nó de animação para visualizar o ciclo e a curva gerada;

### Teste de Sensibilidade
{{ video("pnm_sensibility.webm", caption="Video: Fluxo para Teste de Sensibilidade (variando parâmetros para múltiplas simulações Krel).") }}

O fluxo abaixo permite que o usuário simule e obtenha uma nuvem de curvas de Krel na qual ele pode fazer diferentes análises para determinar as propriedades que são mais sensíveis:

1.  **Carregue** o volume no qual deseja executar a simulação;
2.  Realize a **Segmentação Manual** utilizando um dos segmentos para designar a região porosa da rocha;
3.  Separe os segmentos utilizando a aba **Inspector**, delimitando assim a região de cada um dos poros;
4.  Utilize a aba **Extraction** para obter a rede de poros e ligações a partir do volume LabelMap gerado;
5.  Na aba **Simulation**, escolha a tabela de poros, no seletor Simulation selecione **"Two-phase"**;
6.  Selecione múltiplos valores para alguns parâmetros clicando no botão **"Multi"** (como fizemos para o centro das distribuições dos ângulos de contato no vídeo) - Você pode encontrar mais informações sobre os parâmetros na seção **"Two-phase"**;
7.  (Opcional) Salve os parâmetros selecionados usando a seção **"Save parameters"**;
8.  Clique no botão **"Apply"** para rodar as várias simulações;
9.  Ao finalizar a execução, vá até a aba **"Krel EDA"** e selecione a tabela de parâmetros gerada para fazer diferentes análises usando os recursos de visualização da interface (nuvem de curvas, correlações de parâmetros e resultados, etc);

### Estimativa de Produção
{{ video("pnm_production.webm", caption="Video: Fluxo da estimativa de produção.") }}

O fluxo abaixo permite que o usuário simule e obtenha uma nuvem de curvas de Krel, em uma amostra de escala única:

1.  **Carregue** o volume no qual deseja executar a simulação;
2.  Realize a **Segmentação Manual** utilizando um dos segmentos para designar a região porosa da rocha;
3.  Separe os segmentos utilizando a aba **Inspector**, delimitando assim a região de cada um dos poros;
4.  Utilize a aba **Extraction** para obter a rede de poros e ligações a partir do volume LabelMap gerado;
5.  Selecione múltiplos valores para alguns parâmetros clicando no botão **"Multi"** (como fizemos para o centro das distribuições dos ângulos de contato no vídeo) - Você pode encontrar mais informações sobre os parâmetros na seção **"Two-phase"**;
6.  (Opcional) Salve os parâmetros selecionados usando a seção **"Save parameters"**;
7.  Clique no botão **"Apply"** para rodar as várias simulações;
8.  Ao finalizar a execução, vá até a aba **"Production Prediction"** e selecione a tabela de parâmetros gerada na simulação; Duas opções são disponíveis nessa interface:
    *   A primeira delas "Single Krel" é uma análise de cada simulação individual;
    *   A segunda "Sensitivity test" é uma estimativa da produção levando em conta todas as simulações feitas;