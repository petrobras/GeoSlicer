# Qemscan Loader

O módulo QEMSCAN Loader foi projetado especificamente para carregar e processar imagens QEMSCAN dentro do ambiente de Seção Delgada do GeoSlicer. Este módulo simplifica o processo de importação e visualização de dados complexos do QEMSCAN, oferecendo recursos como configurações personalizáveis de tamanho de pixel e tabelas de cores integradas para identificação eficiente de minerais.

## Painéis e sua utilização

| ![Figura 1](../assets/images/thin_section/modulos/qemscan_loader/interface.png) |
|:-----------------------------------------------:|
| Figura 1: Apresentação do módulo Qemscan Loader. |

### Principais opções
A interface do módulo QEMSCAN Loader é composta por vários painéis, cada um projetado para simplificar o carregamento e o processamento de imagens QEMSCAN:

 - _Input file_: Este input permite selecionar o diretório que contém seus arquivos de imagem QEMSCAN.

 - _Lookup color table_: Permite aos usuários criar e aplicar seus próprios mapeamentos de cores aos dados minerais ou a escolha entre um conjunto de tabelas de cores .csv predefinidas para atribuir cores a diferentes minerais com base em sua composição.

 - _Add new_: Opção de permitir que o carregador procure um arquivo CSV no mesmo diretório do arquivo QEMSCAN que está sendo carregado. Você também tem a opção de caixa de seleção para utilizar a tabela de "Cores minerais padrão". **[Cores minerais padrão](../assets/data/Default mineral colors.csv)**

 - _Pixel size(mm)_: Seção para definir a razão em px/milímetros. Se a imagem complementar em RGB ja foi importada, o valor deverá ser correspondente.

 - _Load Qemscam_: Carregar _QEMSCANs_ .


## Fluxo

{{ video("thin_section_QEMSCAN_loader.webm", caption="QEMSCAN Loader") }}

Utilize o Módulo *QEMSCAN Loader* para carregar imagens QEMSCAN, conforme descrito nos passos abaixo:

1.  Use o botão *Add directories* para adicionar diretórios contendo dados QEMSCAN. Esses diretórios aparecerão na área *Data to be loaded* (uma busca por dados QEMSCAN nesses diretórios ocorrerá em subdiretórios abaixo em no máximo um nível). Pode-se também remover entradas indesejadas selecionando-as e clicando em *Remove*.
2.  Selecione a tabela de cores (*Lookup color table*). Pode-se selecionar a tabela padrão (*Default mineral colors*) ou adicionar uma nova tabela clicando no botão *Add new* e selecionando um arquivo CSV. Tem-se também a opção de fazer o carregador buscar por um arquivo CSV no mesmo diretório que o arquivo QEMSCAN sendo carregado. Também há a opção *Fill missing values from "Default mineral colors" lookup table* para preencher valores faltantes.
3.  Defina o tamanho do pixel (*Pixel size*) em milímetros.
4.  Clique no botão *Load QEMSCANs* e aguarde o carregamento ser finalizado. Os QEMSCANs carregados podem ser acessados na aba *Data*, dentro do diretório *QEMSCAN*.