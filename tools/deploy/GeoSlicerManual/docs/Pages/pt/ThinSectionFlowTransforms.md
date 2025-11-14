## Recorte de Volume

{{ video("thin_section_crop.webm", caption="Video: Recorte de Volume") }}

Módulo *Crop* para cortar um volume, conforme descrito nos passos abaixo:

1.  Selecione o volume em *Volume to be cropped*.
2.  Ajuste a posição e tamanho desejados da ROI nas slice views.
3.  Clique em *Crop* e aguarde a finalização. O volume cortado aparecerá no mesmo diretório que o volume original.

## Ferramentas de imagem

{{ video("thin_section_image_tools.webm", caption="Video: Ferramentas de imagem") }}

Módulo *Ferramentas de imagem* que permite manipulação de imagens, conforme descrito abaixo:

1.  Selecione a imagem em *Input image*.
2.  Selecione a ferramenta em *Tool* e faça as mudanças desejadas.
3.  Clique no botão *Apply* para confirmar as mudanças. Essas mudanças não são permanentes e podem ser desfeitas clicando no botão *Undo*; e serão descartadas se o módulo for deixado sem serem salvas ou for clicado o botão *Reset* (isso reverterá a imagem ao seu último estado salvo). Mudanças podem ser tornadas permanentes clicando no botão *Save* (isso alterará a imagem e não pode ser desfeito).

## Registro

{{ video("thin_section_manual_registration.webm", caption="Video: Registro") }}

Módulo *Register* para registrar imagens de seção delgada e QEMSCAN, conforme descrito nos passos abaixo:

1.  Clique no botão *Select images to register*. Uma janela de diálogo aparecerá que permite a seleção da imagem fixa (*Fixed image*) e a imagem móvel (*Moving image*). Após selecionar as imagens desejadas, clique no botão *Apply* para iniciar o registro.
2.  Adicione Landmarks (pontos de ancoragem) às imagens clicando em *Add* na seção *Landmarks*. Arraste os Landmarks conforme desejado para match as mesmas localizações em ambas as imagens. Pode-se usar as várias ferramentas da seção *Visualization* e a ferramenta window/level localizada na barra de ferramentas para auxiliá-lo nessa tarefa.
3.  Após concluir a colocação dos Landmarks, pode-se clicar no botão *Finish registration*. Transformações serão aplicadas à imagem móvel para corresponder à imagem fixa, e o resultado será salvo em uma nova imagem transformada no mesmo diretório da imagem móvel. Pode-se também cancelo todo o processo de registro clicando no botão *Cancel registration*.
