## Attribute Tools

O módulo Attribute Tools fornece ferramentas para editar atributos da imagem. Esses atributos podem ser inspecionados na aba "Attributes" do módulo Explorer.

### Import PCR from file

Esta ferramenta permite ao usuário importar um arquivo PCR e associá-lo a um volume. O arquivo PCR contém informações que são particularmente úteis para certas análises, como o mapeamento de porosidade a partir da saturação.

Embora as informações de PCR sejam geralmente importadas junto com os dados da imagem (por exemplo, através do **MicroCT Import** ou **NetCDF Loader**), esta ferramenta é útil quando os dados de PCR precisam ser importados separadamente ou atualizados.

#### Como usar

1.  **Selecione uma ferramenta**: No menu suspenso "Tool", selecione "Import PCR from file".
2.  **Input Volume**: Selecione o nó de volume ao qual você deseja associar os dados de PCR.
3.  **PCR File**: Clique no ícone do navegador de arquivos para selecionar o arquivo `.pcr` do seu computador.
4.  **Validação do Arquivo**: Após selecionar um arquivo, o módulo irá validá-lo.
    -   Se o arquivo for um arquivo PCR válido, ele exibirá os valores mínimo e máximo encontrados no arquivo.
    -   Se o arquivo não for válido ou não existir, uma mensagem de erro será exibida.
5.  **Importação**: Assim que um volume válido e um arquivo PCR válido forem selecionados, o botão "Import PCR" será habilitado. Clique nele para importar os dados.
6.  Uma mensagem de sucesso aparecerá após a conclusão da importação. As informações de PCR agora estão armazenadas nos metadados do nó de volume. Você pode verificar isso navegando até o módulo Explorer, selecionando o volume e inspecionando a aba `Attributes`.