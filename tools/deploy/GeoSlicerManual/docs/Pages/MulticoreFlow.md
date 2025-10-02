# Exemplo de utilização do ambiente Core

Este tutorial demonstra como usar os módulos [Multicore](../Core/Multicore.md) e [Multicore Transforms](../Core/MulticoreTransforms.md) para importar e manipular dados de testemunhos (ou "cores"). O exemplo utiliza dados fornecidos por [Digital Porous Media](https://digitalporousmedia.org/published-datasets/tapis/projects/drp.project.published/drp.project.published.DRP-102/).

## Importação e Processamento
A importação de dados de testemunho é realizada no módulo **Multicore**, onde o usuário seleciona as pastas contendo os dados. Para configurar a profundidade e o volume dos **cores** a serem gerados, é necessário preencher os campos _Initial depth_ (Profundidade inicial) e _Core length_ (Comprimento do core). O campo _Core diameter_ (Diâmetro do core) será usado para a remoção do invólucro do core. Após o preenchimento desses campos, basta clicar em **Process Core**.

{{ video("core_process.webm", caption="Video: Importação de testemunhos removendo invólucros automaticamente") }}

## Correção do Posicionamento e Rotação
Depois de importar os **cores**, é possível corrigir a posição vertical no módulo **Multicore Transforms**, ajustando para que os testemunhos fiquem alinhados corretamente. Essa correção pode ser feita de forma manual ou para grupos de cores, conforme necessário.

{{ video("core_transforms.webm", caption="Video: Correção da posição vertical dos testemunhos") }}

## Orientação Automática dos Cores
Além da correção manual da orientação, o módulo **Multicore** oferece a opção de ajustar automaticamente a orientação dos **cores**. Atualmente, três métodos de correção estão disponíveis para facilitar esse processo.

{{ video("core_orient.webm", caption="Video: Correção automática dos testemunhos") }}

## Desenrolamento do Core (Unwrap)
Finalmente, após o alinhamento dos **cores**, o perfil do poço pode ser extraído utilizando a ferramenta de **unwrap** (desenrolamento), que permite visualizar e analisar o poço de forma contínua.

{{ video("core_unwrap.webm", caption="Video: Extração do perfil tomográfico ") }}
