# Transformar Imagem

<div class="content-wrapper">
    <div class="text-content">
        <h2 id="qemscan-loader">Recorte de Volume</h2>
        <p>Módulo <em>Crop</em> para cortar um volume, conforme descrito nos passos abaixo:</p>
        <ol>
          <li>
          <p>Selecione o volume em <em>Volume to be cropped</em>.</p>
          </li>
          <li>
          <p>Ajuste a posição e tamanho desejados da ROI nas slice views.</p>
          </li>
          <li>
          <p>Clique em <em>Crop</em> e aguarde a finalização. O volume cortado aparecerá no mesmo diretório que o volume original.</p>
          </li>
          </ol>
    </div>
    <div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../assets/videos/thin_section_crop.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Recorte de Volume</p>
    </div>
</div>

 <div class="content-wrapper">
    <div class="text-content">
        <h2 id="qemscan-loader">Ferramentas de imagem</h2>
        <p>Módulo <em>Ferramentas de imagem</em> que permite manipulação de imagens, conforme descrito abaixo:</p>
        <ol>
          <li>
          <p>Selecione a imagem em <em>Input image</em>.</p>
          </li>
          <li>
          <p>Selecione a ferramenta em <em>Tool</em> e faça as mudanças desejadas.</p>
          </li>
          <li>
          <p>Clique no botão <em>Apply</em> para confirmar as mudanças. Essas mudanças não são permanentes e podem ser desfeitas clicando no botão <em>Undo</em>; e serão descartadas se o módulo for deixado sem serem salvas ou for clicado o botão <em>Reset</em> (isso reverterá a imagem ao seu último estado salvo). Mudanças podem ser tornadas permanentes clicando no botão <em>Save</em> (isso alterará a imagem e não pode ser desfeito).</p>
          </li>
        </ol>
    </div>
    <div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../assets/videos/thin_section_image_tools.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Ferramentas de imagem</p>
    </div>
</div>


<div class="content-wrapper">
    <div class="text-content">
        <h2 id="qemscan-loader">Registro</h2>
        <p>Módulo <em>Register</em> para registrar imagens de seção delgada e QEMSCAN, conforme descrito nos passos abaixo:</p>
        <ol>
          <li>
          <p>Clique no botão <em>Select images to register</em>. Uma janela de diálogo aparecerá que permite a seleção da imagem fixa (<em>Fixed image</em>) e a imagem móvel (<em>Moving image</em>). Após selecionar as imagens desejadas, clique no botão <em>Apply</em> para iniciar o registro.</p>
          </li>
          <li>
          <p>Adicione Landmarks (pontos de ancoragem) às imagens clicando em <em>Add</em> na seção <em>Landmarks</em>. Arraste os Landmarks conforme desejado para match  as mesmas localizações em ambas as imagens. Pode-se usar as várias ferramentas da seção <em>Visualization</em> e a ferramenta window/level localizada na barra de ferramentas para auxiliá-lo nessa tarefa.</p>
          </li>
          <li>
          <p>Após concluir a colocação dos Landmarks, pode-se clicar no botão <em>Finish registration</em>. Transformações serão aplicadas à imagem móvel para corresponder à imagem fixa, e o resultado será salvo em uma nova imagem transformada no mesmo diretório da imagem móvel. Pode-se também cancelo todo o processo de registro clicando no botão <em>Cancel registration</em>.</p>
          </li>
        </ol>
    </div>
    <div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../assets/videos/thin_section_manual_registration.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Registro</p>
    </div>
</div>
