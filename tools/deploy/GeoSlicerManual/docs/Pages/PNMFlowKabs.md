## Simulação de Permeabilidade Absoluta (Kabs)

### Simulação Kabs em escala única

{{ video("pnm_kabs.webm", caption="Video: Fluxo para simulação de permeabilidade absoluta.") }}

O fluxo abaixo permite simular e obter um estimado da permeabilidade absoluta, em uma amostra de escala única, considerando todos os poros como resolvidos:

1.  **Carregue** o volume no qual deseja executar a simulação;
2.  Realize a **Segmentação Manual** utilizando um dos segmentos para designar a região porosa da rocha;
3.  Separe os segmentos utilizando a aba **Inspector**, delimitando assim a região de cada um dos poros;
4.  Utilize a aba [**Extraction**](./PoreNetworkExtractor.md) para obter a rede de poros e ligações a partir do volume LabelMap gerado;
5.  Na aba [**Simulation**](./PoreNetworkSimulation.md#one-phase) para rodar a simulação de Kabs;
