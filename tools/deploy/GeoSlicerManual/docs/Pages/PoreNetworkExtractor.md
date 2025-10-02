## Extractor

Esse módulo é utilizado para extrair a rede de poros e ligações a partir de: uma segmentação individualizada dos poros (_Label Map Volume_) realizada por um algoritmo de _watershed_, gerando uma rede uniescalar; ou por um mapa de porosidades (_Scalar Volume_), que gerará um modelo multiescalar com poros resolvidos e não-resolvidos.


| ![Interface do módulo de Extração](../assets/images/PoreNetworkExtractor.png) |
|:-----------------------------------------------------------------------:|
| Figura 1: Interface do módulo de Extração. |

Após a extração, ficará disponível na interface do GeoSlicer: as tabelas de poros e gargantas e também os modelos de visualização da rede. As tabelas geradas serão os dados usados na etapa seguinte de simulação.

| ![Label Map](../assets/images/PoreNetworkExtractorLabelMap.png){ width=50% }![Rede Uniescalar](../assets/images/PoreNetworkExtractorRedeUniescalar.png){ width=50% } |
|:-----------------------------------------------------------------------:|
| Figura 1: A esquerda Label Map utilizado como entrada na extração e a direita rede uniescalar extraída. |

| ![Scalar](../assets/images/PoreNetworkExtractorScalar.png){ width=50% }![Rede Multiescalar](../assets/images/PoreNetworkExtractorRedeMultiescala.png){ width=50% } |
|:-----------------------------------------------------------------------:|
| Figura 2: A esquerda Scalar Volume utilizado como entrada na extração e a direita rede multiescalar extraída, onde azul representa poros resolvidos, e rosa representa os poros não-resolvidos. |

**Escala de Cores:**

**Esferas (Poros):**

*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:blue; vertical-align: middle;"></span> **Azul** - Poro resolvido
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:magenta; vertical-align: middle;"></span> **Magenta** - Poro não resolvido

**Cilindros (Gargantas):**

*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:green; vertical-align: middle;"></span> **Verde** - Garganta entre poros resolvidos
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:yellow; vertical-align: middle;"></span> **Amarelo** - Garganta entre um poro resolvido e um não resolvido
*   <span style="display:inline-block; width:15px; height:15px; border: 1px solid #555; background-color:red; vertical-align: middle;"></span> **Vermelho** - Garganta entre poros não resolvidos
