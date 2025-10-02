# Guia de Instalação

A seguir, os passos para instalação do GeoSlicer. Observe atentamente os itens
destacados, são dicas para contornar algumas situações comuns.

## Pré-requisitos

O GeoSlicer roda em qualquer computador Windows ou Linux lançado nos últimos 5
anos. Computadores mais antigos podem funcionar (dependendo principalmente dos
recursos gráficos). Os requisitos **mínimos** são:

- Sistema Operacional: Windows 10 ou Ubuntu 20.04 LTS
- RAM: 8 GB
- Resolução de tela: 1024x768 (recomendamos 1280x1024 ou superior)
- Placa de vídeo: 4 GB de RAM, suporte a OpenGL 3.2 (recomendamos pelo menos o dobro do tamanho do maior dado que será utilizado)
- Armazenamento: > 15GB de espaço livre em disco. Recomendamos um SSD para melhor desempenho.

!!! tip
    Dê preferência para discos SSD e locais, evite discos de rede (NAS). Ter mais de 15GB livres para
    armazenar o software e os dados utilizados no experimento.

## Instalação

#### 1. Preparação

Escolha um disco para instalação, dê preferência para discos locais e que sejam SSD.

!!! tip
    (Opcional) Instale a ferramenta 7zip. O instalador do GeoSlicer detecta a presença dessa
    e a utiliza para fazer a descompressão da instalação com mais eficiência. Como o
    GeoSlicer é uma aplicação grande, a descompressão é um processo oneroso e que se for
    realizado pela ferramenta nativa do Windows irá demorar mais.

#### 2. Download

Baixe o instalador do GeoSlicer. Se você tem acesso a um ambiente privado com a versão fechada do GeoSlicer,
como a Petrobrás, você pode baixar via o [sharepoint](https://petrobrasbr.sharepoint.com.mcas.ms/teams/LTRACE/SitePages/Home.aspx) da LTrace ou diretamente no Teams, entrando em contato
com algum membro da equipe da LTrace. Caso queira baixar a versão opensource, acesse o link [GeoSlicer Installer](https://objectstorage.sa-saopaulo-1.oraclecloud.com/p/KV_6G_jhvYnygJs-FLigs706yoMdiOaYsBnUMvoP3RjnJ2CJlsZMmobRXPyKoc1t/n/grrjnyzvhu1t/b/General_ltrace_files/o/GeoSlicer/builds/windows/GeoSlicer-2.4.10-public.exe).

#### 3. Instalação

Execute o instalador do GeoSlicer (GeoSlicer-*.exe) e ele irá pedir o local da instalação. Selecione
um lugar no disco escolhido na etapa de preparação (Passo 1) e clique em Extrair.

Em seguida a descompressão dos arquivos começa, e você poderá acompanhar o progresso da
instalação. Caso você tenha instalado o 7zip, uma tela similar a essa irá aparecer para você. Do
contrário, será a barra de progresso nativa do sistema operacional.

#### 3. Execução

Após finalizada a instalação, vá até a pasta que foi escolhida no passo anterior, e execute o
GeoSlicer.exe. Essa primeira execução faz a configuração da aplicação.

Na primeira execução, após concluir a configuração da aplicação o GeoSlicer irá reiniciar para
finalizar a instalação. Nas versões abaixo da 2.5 essa etapa é automática, mas não se assuste,
após esse reinicio a aplicação está pronta para ser usada.