# Introdução

O GeoSlicer consegue abrir diversos tipos de arquivos, dentre eles, RAW, TIFF, PNG, JPG são os principais quando se
trata de imagens 2D para lâminas delgadas. Para imagens 3D, o GeoSlicer consegue abrir arquivos em formato NetCDF, RAW e
até mesmo
diretórios com imagens 2D (PNG, JPG, TIFF) compondo um volume 3D.

## Abrir Imagem

Cada tipo de projeto carrega em seu ambiente um módulo específico para carregamento de imagens. Em todos os ambientes, o
módulo que irá aparecer primeiro no lado esquerdo da tela é o **_Loader_** principal daquele ambiente. Alguns ambientes
possuem mais
de um módulo de carregamento, como o ambiente de **_Thin Section_** que possui o **_Loader_** e o **_QEMSCAN Loader_**.

Os módulos de carregamento existentes são:

- **_Thin Section_**:
    - **_Loader_**: Carrega imagens de lâminas delgadas.
    - **_QEMSCAN Loader_**: Carrega imagens de lâminas delgadas obtidas por QEMSCAN.
- **_Volumes_**:
    - **_Micro CT Loader_**: Carrega imagens de micro CT.
- **_Well Log_**:
    - **_Loader_**: Carrega imagens de perfis de poços
    - **_Importer_**: Carrega perfis de poços em CSV, JPG, PNG e TIFF.
- **_Core_**:
    - **_Multicore_**: Carrega imagens de testemunhos de poços em lote.
- **_Multiscale_**:
    - **_Loader_**: Carrega imagens de perfis de poços
    - **_Importer_**: Carrega perfis de poços em CSV, JPG, PNG e TIFF.
    - **_Micro CT Loader_**: Carrega imagens de micro CT.
    - **_Core Photograph Loader_**: Carrega a imagem central das fotografias das caixas centrais e construa um volume
      com a imagem completa do núcleo.