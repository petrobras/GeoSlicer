# Modelagem de Permeabilidade

Este módulo estima um perfil de permeabilidade contínuo (uma curva 1D) a partir de uma imagem de perfil de poço (2D) que foi previamente segmentada. O método utiliza também um perfil de porosidade e dados de permeabilidade de plugs (amostras) para calibrar o modelo. É um método especialmente útil para reservatórios de dupla porosidade.

O processo se baseia no trabalho de Menezes de Jesus, C., et al. (2016).

## Entradas e Saídas

- **Entradas Principais:**
    1.  **Imagem de Perfil Segmentada (2D):** Uma imagem da parede do poço onde cada pixel foi classificado em um tipo de rocha ou poro (ex: "microporosidade", "macroporosidade", "vug", "rocha sólida"). O conjunto de classes é definido pelo usuário durante a etapa de segmentação.
    2.  **Perfil de Porosidade (1D):** Um perfil de poço contínuo (curva) que representa a porosidade total ao longo da profundidade.
    3.  **Medidas de Permeabilidade de Plugs (pontual):** Medidas de laboratório em amostras de rocha, usadas como referência para calibrar o modelo.
- **Saída:**
    - **Perfil de Permeabilidade Modelado (1D):** Uma nova tabela contendo um perfil contínuo (curva) de permeabilidade versus profundidade, com o mesmo intervalo de profundidade da imagem de entrada.

## Teoria

A permeabilidade ($K$) em cada profundidade é calculada como uma soma ponderada, onde a contribuição de cada classe de segmento é levada em conta. A fórmula é:

$$ K = (A_1 \cdot F_1 \cdot \Phi^{B_1}) + (A_2 \cdot F_2 \cdot \Phi^{B_2}) + \dots + (A_n \cdot F_n \cdot \Phi^{B_n}) + (A_m \cdot F_m \cdot \Phi) $$

Onde, para cada profundidade:

- **$A$ e $B$**: Parâmetros de calibração, otimizados pelo modelo para que o resultado se ajuste às medidas de referência (plugs).
- **$F_n$**: Fração da classe de segmento *n* (ex: a fração de "microporosidade" naquela profundidade da imagem).
- **$F_m$**: Fração do segmento definido como "Macroporo". Para esta classe, o expoente da porosidade é fixado em 1, diferenciando-a das demais.
- **$\Phi$**: Porosidade total (lida do perfil de porosidade de entrada).

## Como Usar

!!! note "Nota Importante sobre os Dados"
    Para garantir resultados corretos, os dados de entrada devem atender aos seguintes requisitos:

    *   **Unidades de Profundidade:** Todos os perfis de entrada (perfis de poço e medidas de plugs) devem usar **milímetros (mm)** como unidade de profundidade. A tabela de saída também será gerada com profundidades em milímetros.
    *   **Intervalo de Cálculo e Interpolação:** O cálculo é realizado apenas no intervalo de profundidade onde o perfil de porosidade e a imagem segmentada **se sobrepõem**. O perfil de porosidade será interpolado para corresponder às profundidades exatas da imagem, e quaisquer valores ausentes (NaN) no perfil de porosidade serão ignorados.

1.  **Imagens de Entrada:**
    *   **Perfis de poço (.las):** Selecione a tabela que contém os perfis de poço (importada via [Image Log Import](./ImageLogImport.md)).
    *   **Perfil de Porosidade:** Na lista, escolha qual coluna da tabela corresponde ao perfil de porosidade (curva 1D).
    *   **Imagem Segmentada:** Selecione a imagem de perfil de poço 2D que já foi segmentada em classes.

2.  **Parâmetros:**
    *   **Segmento de Macroporo:** Dentre as classes presentes na sua imagem segmentada, selecione aquela que representa os macroporos. Esta classe terá um tratamento diferenciado na fórmula, como descrito na seção de Teoria.
    *   **Segmento Ignorado/nulo:** Selecione uma classe da sua imagem segmentada que deva ser desconsiderada no cálculo (ex: uma classe "incerteza" ou de má qualidade de imagem).

3.  **Permeabilidade de Referência:**
    *   **Medidas de Plugs:** Selecione a tabela que contém as medidas de permeabilidade de plugs.
    *   **Perfil de Permeabilidade de Plugs:** Escolha qual coluna da tabela de plugs corresponde aos valores de permeabilidade.

4.  **Otimização de Kds (Avançado):**
    *   Esta seção permite ao usuário inserir pontos de calibração manuais para forçar o modelo a passar por valores específicos em certas profundidades. Isso é útil para corrigir erros em zonas de interesse.

5.  **Saída:**
    *   **Nome da Saída:** Defina o nome para a tabela de saída que conterá o perfil de permeabilidade calculado.

6.  **Aplicar:**
    *   Clique em "Apply" para iniciar o cálculo. O resultado será uma nova tabela com as colunas "DEPTH" e o perfil de permeabilidade modelado.

---
*Referência: Menezes de Jesus, C., Compan, A. L. M. and Surmas, R., Permeability Estimation Using Ultrasonic Borehole Image Logs in Dual-Porosity Carbonate Reservoirs, 2016.*
