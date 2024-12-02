# MicroTom

Este módulo permite que usuários do _GeoSlicer_ usem algoritmos e métodos da biblioteca MicroTom, desenvolvida pela
Petrobras.

__Métodos disponíveis__

* Distribuição do tamanho dos poros
* Distribuição hierárquica do tamanho dos poros
* Pressão capilar de injeção de mercúrio
* Permeabilidade absoluta de Stokes-Kabs na escala dos poros

## Interface

### Entrada

1. __Segmentação__: Selecione um labelmap no qual o algoritmo microtom será aplicado. Deve ser um labelmap, nó de
   segmentação não é aceito (qualquer nó de segmentação pode ser transformado em um labelmap na aba _Dados_ clicando com
   o botão esquerdo no nó. ).
2. __Região (SOI)__: Selecione uma nota de segmentação onde o primeiro segmento delimita a região de interesse onde a
   segmentação será realizada.
3. __Segmentos__: Selecione um segmento na lista para ser usado como o espaço poroso da rocha.

