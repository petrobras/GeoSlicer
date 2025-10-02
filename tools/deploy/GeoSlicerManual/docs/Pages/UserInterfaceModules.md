# Módulos

O GeoSlicer é uma aplicação modular, ou seja, cada função específica adicionada ao _software_ é feita através de um novo
módulo. 
Isso permite que o GeoSlicer seja facilmente expandido e personalizado para atender a diferentes necessidades de
projeto. Inclusive o usuário pode desenvolver seus próprios módulos e integrá-los ao GeoSlicer.

### Design

Os módulos do GeoSlicer são desenvolvidos seguindo alguns padrões de design, que visam estabelecer uma interface coesa e
intuitiva independente do módulo. A seguir, vamos abordar esses padrões e como eles impactam a experiência do usuário.

### Entradas / Configuração / Saída

A grande maioria dos módulos é estruturada em três partes: entradas, configuração e saída. As entradas são os dados que
o módulo precisa para rodar a tarefa que ele implementa. A configuração são os parâmetros que o usuário pode ajustar para
personalizar a execução.
E a saída é o resultado da execução do módulo, normalmente sendo requisitado apenas um sufixo para o nome do nodo/dado
resultante. 

### Flows

Os fluxos de trabalho mais repetitivos e comuns são implementados na forma de fluxos (_flows_). Um fluxo é uma sequência
específica de módulos pré-configurados, que ao serem executados passo-a-passo, implementam um fluxo de trabalho. O GeoSlicer já tem alguns fluxos implementados:

- Lâminas Delgadas:
    - **Fluxo de Segmentação**: Fluxos implementados para PP, PP/PX e QEMSCAN. Realizam o fluxo completo de análise das lâminas com segmentação, particionamento e quantificação das imagens.
- Micro CT:
    - **Fluxo de Modelagem de Permeabilidade**: Fluxo executa todas as etapas até a modelagem de permeabilidade.
    - **Fluxo de Segmentação Microporosidade para Imagens Grandes**: Fluxo executa todas as etapas até a segmentação em imagens grandes.

### Custom

Alguns módulos são customizados para atender a necessidades específicas de um projeto. Nem sempre esses módulos vão seguir os padrões acima descritos, devido a alguma especificidade do problema ou característica da aplicação. Um exemplo é o módulo _Manual Segmentation_, que oferece uma gama de ferramentas para segmentação manual de imagens. Por ser extremamente interativo, esse módulo requer uma interface própria que permita que o usuário alterne entre as ferramentas facilmente.
