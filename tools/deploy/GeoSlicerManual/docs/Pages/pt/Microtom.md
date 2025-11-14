# MicroTom

O módulo **MicroTom** integra a biblioteca de simulação MicroTom, desenvolvida pela Petrobras, ao *GeoSlicer*. Ele oferece um conjunto de ferramentas avançadas para análise de meios porosos, permitindo a caracterização detalhada de propriedades petrofísicas a partir de imagens digitais.

A seguir, são descritos os principais métodos disponíveis:

- **PNM Complete Workflow**: Executa o fluxo de trabalho completo do modelo de rede de poros (Pore Network Model), desde a extração da rede até a simulação de propriedades e geração de um relatório interativo.
- **Pore Size Distribution**: Calcula a distribuição do tamanho dos poros com base no método das esferas máximas inscritas em um meio poroso binário. O segmento selecionado é considerada como o espaço poroso.
- **Hierarchical Pore Size Distribution**: Analisa a distribuição de poros em materiais com estrutura hierárquica, que apresentam poros interconectados em diferentes escalas (microporos, mesoporos e macroporos).
- **Mercury Injection Capillary Pressure**: Simula a curva de pressão capilar por injeção de mercúrio. O cálculo é baseado nos raios das máximas esferas que preenchem o meio poroso binário e estão conectadas a uma face de entrada.
- **Incompressible Drainage Capillary Pressure**: Calcula a curva de pressão capilar durante o processo de drenagem primária, considerando um fluido umectante incompressível. Neste método, a saturação de água irredutível (Swi) é diferente de zero, pois parte da fase umectante fica aprisionada com o aumento da pressão capilar.
- **Imbibition Capillary Pressure**: Calcula a curva de pressão capilar durante o processo de embebição. O cálculo assume que não há aprisionamento da fase não-umectante (Sor = 0), que é totalmente deslocada à medida que a pressão capilar diminui.
- **Incompressible Imbibition Capillary Pressure**: Simula a curva de pressão capilar de embebição considerando o aprisionamento da fase não-umectante (Sor ≠ 0) à medida que a pressão capilar diminui.
- **Absolute Permeability**: Calcula a permeabilidade absoluta do meio poroso por meio de uma simulação de escoamento de Stokes.
- **Absolute Permeability - Representative Elementary Volume**: Executa o cálculo de permeabilidade absoluta em múltiplos subvolumes para análise de Volume Elementar Representativo (REV).
- **Absolute Permeability - Darcy FOAM**: Lê um campo de permeabilidade e configura um caso de simulação no OpenFOAM para o solver DarcyBR.
- **Relative Permeability**: Calcula a permeabilidade relativa bifásica utilizando o método Lattice Boltzmann (LBM) a partir de uma imagem binária segmentada.
