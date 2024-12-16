# Módulo Multiscale Post Processing

Módulo para extração de dados após simulação Multiscale.

| ![Figura 1](MultiscalePostProcessing.png) |
|:-----------------------------------------------:|
| Figura 1: Módulo Multiscale Post Processing. |

## Métodos

### Porosity per Realization 
Produz uma tabela com a porcentagem de porosidade de cada fatia de um volume, em todos os volumes de uma sequência.
#### Dados de entrada e Parâmetros
1. _Volume Resultado_: Volume para calculo da porosidade. Se o volume for um proxy para uma sequência de volumes, a porosidade irá ser calculada para todos as realizações.
2. _Imagem de treinamento:_ Volume extra incluído nos cálculos e adicionado à tabela como referência.
3. _Pore segment Value_: Valor a ser considerado como poro em volumes escalares (dado contínuo)
4. _Pore segment_: Segmento a ser considerado como poro em Labelmaps (dado discreto).

</br>

### Pore Size distribution
Recalcula a distribuição do tamanho de poro para frequência.
#### Dados de entrada e Parâmetros
1. _PSD Sequence Table_: Tabela ou proxy de sequência de tabelas resultante do módulo Microtom.
2. _PSD TI Table_: Tabela resultado do microtom para a imagem de treinamento.