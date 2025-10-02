## ImageLog Export

O módulo **Exportador de Perfis de Imagem** é utilizado para exportar dados de perfis de poço, como volumes escalares, segmentações e tabelas, para formatos de arquivo padrão da indústria.

A principal finalidade deste módulo é permitir que os dados processados ou gerados no GeoSlicer sejam facilmente transferidos para outros softwares especializados em análise de perfis de poço, como Techlog ou Geolog. Ele garante que os dados sejam convertidos para formatos compatíveis, preservando a estrutura e as informações essenciais.

### Como Usar

1.  **Selecione os Dados:** Na árvore da hierarquia de dados, selecione os itens (volumes, segmentações ou tabelas) que você deseja exportar. Você pode selecionar múltiplos itens.
    * **Dados associados**: Caso um item selecionado possua algum dado associado, a opção **Associated data** ficará disponível e permitirá escolher os tipos de dados para serem exportados juntos. Atualmente apenas os dados de **Proportions** está diponível.
2.  **Escolha o Formato de Exportação:**
    *   **Well log:** Defina o formato de saída para quaisquer dados de perfil selecionados (ex: `LAS`, `DLIS`, `CSV`).
    *   **Table:** Defina o formato de saída para as tabelas selecionadas, se houver.
3.  **Ignore a estrutura de diretórios (Opcional):** Marque a opção **Ignore directory structure** se desejar que todos os arquivos sejam salvos diretamente no diretório de exportação, sem recriar a estrutura de pastas da hierarquia do projeto.
4.  **Selecione o Diretório de Exportação:** No campo **Export directory**, escolha a pasta onde os arquivos serão salvos.
5.  **Clique em Export:** Pressione o botão **Export** para iniciar o processo.

### Formatos de Saída

#### Perfis de Poço (Well Log)

-   **DLIS:** Formato padrão da indústria para dados de perfilagem de poços.
-   **CSV (matrix format):** Exporta os dados em um formato de planilha "larga", em que cada linha representa um único valor de profundidade dado na primeira coluna, enquanto as demais colunas representam valores naquela profundidade. Exemplo de CSV em matriz:
    ```
    MD,Volume[0],Volume[1]
    10.0,50,60
    10.1,52,62
    ```
-   **CSV (Techlog format):** Gera um arquivo CSV em um formato específico, otimizado para importação no software Techlog. É um formato "planificado", em que vários valores na mesma profundidade são armazenados como várias linhas. Exemplo de CSV Techlog:
    ```
    depth,intensity
    m,HU
    10.0,50
    10.0,60
    10.1,52
    10.1,62
    ```
-   **LAS:** Outro formato de texto padrão amplamente utilizado para dados de perfis de poço.
-   **LAS (for Geolog):** Uma variação do formato LAS, ajustada para melhor compatibilidade com o software Geolog.

#### Tabelas (Table)

-   **CSV:** Formato padrão de valores separados por vírgula, compatível com a maioria dos softwares de planilhas e análise de dados.