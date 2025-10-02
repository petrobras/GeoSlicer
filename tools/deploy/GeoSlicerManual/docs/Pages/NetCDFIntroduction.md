O módulo **NetCDF** fornece um conjunto de ferramentas para trabalhar com o formato de arquivo NetCDF (`.nc`), que é usado no GeoSlicer para armazenar múltiplos volumes, segmentações e tabelas em um único arquivo autocontido.

A principal vantagem de usar o formato NetCDF é a capacidade de agrupar dados relacionados em um único arquivo. Por exemplo, você pode salvar um volume de imagem original e múltiplas segmentações ou análises (como tabelas de porosidade) juntos. Isso mantém todos os dados do seu projeto organizados e portáteis, facilitando o compartilhamento e o arquivamento.

Além disso, o NetCDF é um formato de dados padrão e autodescritivo, amplamente utilizado em aplicações científicas. Isso significa que os arquivos `.nc` gerados pelo GeoSlicer podem ser facilmente abertos e processados por outras ferramentas e bibliotecas externas, como `xarray` e `netCDF4` em Python, permitindo fluxos de trabalho de análise personalizados.

### Funcionalidades

O módulo é dividido em três abas principais:

- **Import:** Permite carregar dados de um arquivo NetCDF (`.nc`) ou HDF5 (`.h5`, `.hdf5`) para a cena.
- **Save:** Permite salvar novas imagens ou tabelas de uma pasta de projeto de volta ao arquivo NetCDF original de onde foram importadas. Esta operação modifica o arquivo existente.
- **Export:** Permite exportar um ou mais itens da cena para um **novo** arquivo NetCDF.

### Integração com Outros Módulos

Os arquivos NetCDF integram-se com outros módulos do GeoSlicer para fluxos de trabalho avançados:

-   É possível importar um arquivo NetCDF usando o [**Carregador de Micro CT**](./MicroCTImport.md).
-   Para arquivos NetCDF que contêm imagens muito grandes para caber na memória, você pode usar o módulo [**Big Image**](./LoadBigImage.md) para visualizá-los e processá-los de forma eficiente.
