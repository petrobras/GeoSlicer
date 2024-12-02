# Primeiros Passos

Como primeiros passos, vamos abordar um fluxo simples de segmentação que pode ser realizado tanto com imagens de lâminas
delgadas quanto com imagens de micro CT.

Para começar, abra o GeoSlicer e escolha um tipo de projeto na tela inicial. O ambiente escolhido precisa ser compatível
com o tipo de imagem que você usará de exemplo. Escolha **_Volumes_** para imagens de micro CT e **_Thin Section_** para
imagens de lâminas delgadas.

## 1. Abrir Imagem

O primeiro passo é abrir a imagem que você deseja segmentar. Ao selecionar uma ambiente no menu inicial, o módulo que
irá aparecer, no lado esquerdo, é o **_Loader_** daquele ambiente.

- Para micro CT veja essa etapa em [Abrir Imagem](open_image.md).
- Para lâminas delgadas veja essa etapa em [Abrir Imagem](open_image.md).

## 2. Segmentar Imagem

Após abrir a imagem, o próximo passo é segmentá-la. A segmentação é o processo de dividir a imagem em regiões de
interesse. A imagem a seguir mostra um exemplo de segmentação de uma lâmina em duas regiões, poro e não-poro. Essa
segmentação pode ser feita no módulo **_Segmentation -> Manual Segmentation_**.

- Para micro CT veja essa etapa em [Abrir Imagem](open_image.md).
- Para lâminas delgadas veja essa etapa em [Abrir Imagem](open_image.md).

Nessa etapa, você pode optar por criar uma segunda segmentação para representar a região de interesse, ou seja, a área
que
você de fato quer analisar. Normalmente esse passo é feito quando há alguma sujeira ou região que não interessa na
imagem.

## 3. Analisar Imagem

Uma vez feita a segmentação, você pode quantificar as regiões segmentadas, fazer analises como distribuição de tamanho
de poros.
Para isso, vamos focar na região de interesse que você segmentou como Poro. Utilize o **_Segment Inspector_** para
inspecionar a imagem.

O **_Segment Inspector_** funciona de forma similar para ambos os tipos de imagem. Ele faz o particionamento da região
de interesse
de acordo com a configuração que o usuário escolher. No caso, como vamos analisar a região porosa, ele vai particionar a
segmentaçao identificando as gargantas e separando os poros. Como resultado final, além da imagem particionada, você
obtêm uma tabela com diversas estatísticas sobre os poros (sufixo '_Report').


## 4. Exportar Resultados

Por fim, você pode exportar os resultados da análise. Além de simplesmente salvar o projeto no formato do GeoSlicer,
você pode exportar os resultados da análise em diversos formatos, como CSV, NetCDF e RAW. Assim você pode compartilhar
esses resultados ou até mesmo carregar em outro sofware. Para isso, utilize o módulo **_Exporter_**. Teste todos os
formatos para aprender como cada um se comporta.



