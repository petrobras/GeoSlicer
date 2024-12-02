
## Explore

Fluxo para o obtenção de um mapa de porosidade a partir de um volume escalar.

```mermaid
%%{
  init: {
    'themeVariables': {
      'lineColor': '#c4c4c4'
    }
  }
}%%
flowchart LR
    Iniciar --> Importar
    Importar --> Segmentacao
    Segmentacao --> Modelagem
    Modelagem --> Resultados
    
    click Segmentacao "../../Segmentation/segmentation.html" "teste de imagem"
    style Iniciar fill:#808080,stroke:#333,stroke-width:1px,color:#fff;
    style Importar fill:#6d8873,stroke:#333,stroke-width:1px,color:#fff;
    style Segmentacao fill:#5a9b87,stroke:#333,stroke-width:1px,color:#fff;
    style Modelagem fill:#45ae97,stroke:#333,stroke-width:1px,color:#fff;
    style Resultados fill:#2ea67e,stroke:#333,stroke-width:1px,color:#fff;

    Segmentacao["Segmentação"]
```

1. Inicie o Geoslicer no ambiente MicroCT a partir da interface do aplicativo.

2. Selecione o volume de entrada clicando em "Escolher pasta" ou "Escolher arquivo" e escolha os dados de importação desejados entre as opções disponíveis. Sugerimos testar primeiro os parâmetros padrão.

3. Selecione o volume de entrada clicando em "Input:" Ajuste os parâmetros para diferentes efeitos de segmentação, como "Múltiplos Limiares," "Remoção de Fronteira," e "Expandir Segmentos." Ajuste as configurações para obter os resultados de segmentação desejados, usando o feedback da interface e as ferramentas de visualização.

4. Revise e refine os dados segmentados. Ajuste os limites da segmentação, mescle ou divida segmentos, e aplique outras modificações para aprimorar o modelo de porosidade usando as ferramentas fornecidas.


5. Salve o mapa de porosidade ou exporte o volume com as tabelas de parametros.

## Saiba Mais...
```mermaid
%%{init: { 'logLevel': 'debug', 'theme': 'default','themeVariables': {
            'git0': '#808080',
            'git1': '#6d8873',
            'git2': '#5a9b87',
            'git3': '#45ae97',
            'git4': '#2ea67e',
            'git5': '#ffff00',
            'git6': '#ff00ff',
            'git7': '#00ffff',
            'gitBranchLabel0': '#ffffff',
            'gitBranchLabel1': '#ffffff',
            'gitBranchLabel2': '#ffffff',
            'gitBranchLabel3': '#ffffff',
            'gitBranchLabel4': '#ffffff',
            'gitBranchLabel5': '#ffffff',
            'gitBranchLabel6': '#ffffff',
            'gitBranchLabel7': '#ffffff',
            'gitBranchLabel8': '#ffffff',
            'gitBranchLabel9': '#ffffff',
            'commitLabelColor': '#afafaf',
              'commitLabelBackground': '#0000',
              'commitLabelFontSize': '13px'
       }, 'gitGraph': {'showBranches': true, 'showCommitLabel':true,'mainBranchName': 'Inicio'}} }%%
      gitGraph LR:
        commit id:"Inicio"
        commit id:"Micro CT  ."
        branch "Importar"
        commit id:"Aba de Dados"
        commit id:"Aba de Importação"
        commit id:"Selecionar Arquivo"
        commit id:"Parâmetros"
        commit id:"Carregar  ."
        branch "Segmentação"
        commit id:"Aba de Segmentação"
        commit id:"Adicionar novo nó de segmentação"
        commit id:"Criar pelo menos 4 segmentos"
        commit id:"Adicionar ROI  ."
        branch Modelagem
        commit id:"Aba de Modelagem"
        commit id:"Segmentação"
        commit id:"Selecionar volume"
        commit id:"Selecionar segmentação"
        commit id:"Aplicar  ."
        branch Resultados
        commit id:"Gráficos"
        commit id:"Imagens"
        commit id:"Tabelas"
        commit id:"Relatórios"
```
#### [Inicio](../../Bem Vindo/welcome) 
Inicie o Geoslicer no ambiente MicroCT a partir da interface do aplicativo.

#### [Importar(TODO)](../../Bem Vindo/welcome)
Selecione o volume de entrada clicando em "Escolher pasta" ou "Escolher arquivo" e escolha os dados de importação desejados entre as opções disponíveis. Sugerimos testar primeiro os parâmetros padrão.

#### [Segmentação](../../Segmentation/segmentation.md)
Selecione o volume de entrada clicando em "Entrada:" Ajuste os parâmetros para diferentes efeitos de segmentação, como:
 
 1. Múltiplos Limiares(TODO)
 2. Remoção de Fronteira(TODO)
 3. Expandir Segmentos(TODO)
  
Ajuste as configurações para obter os resultados de segmentação desejados, usando o feedback da interface e as ferramentas de visualização.

#### [Modelagem(TODO)](../../Bem Vindo/welcome)
 Revise e refine os dados segmentados. Ajuste os limites da segmentação, mescle ou divida segmentos, e aplique outras modificações para aprimorar o modelo de segmentação usando as ferramentas fornecidas.(TODO)

#### [Resultados(TODO)](../../Bem Vindo/welcome)
Salve o projeto ou exporte o volume segmentado. Os resultados podem ser exibidos como:

 1. Imagem(Screenshot)(TODO)
 2. Graficos(Charts)(TODO)
 3. Servidos atraves de Relatórios (Streamlit)(TODO)

## Ainda tem perguntas?

#### [Entre em contato](https://www.ltrace.com.br/contact/)
