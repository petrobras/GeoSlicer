<div class="content-wrapper">
    <div class="text-content">
        <p>Efeito <em>Smart foreground</em> para segmentar a área útil da amostra em uma imagem ou volume. O passo-a-passo de utilização está dividido em duas etapas:</p>
        <ol>
            <li>
            <p><b>Operação</b>: considera útil toda área da imagem/volume que não corresponda às bordas.</p>
            </li>
            <li>
            <p><b>Fragmentação (opcional)</b>: eventuais fissuras entre fragmentos da amostra também deixam de ser consideradas área útil. Disponível apenas para imagens 2D (lâminas) e recomendável apenas para lâminas de luz polarizada plana (PP).</p>
            </li>
        </ol>
        <header><h3>Operação</h3></header>
        <ol>
            <li>
            <p>Defina a imagem de entrada e segmentação de saída conforme o <a href="../manual_segmentation.html" style="color: #007bff;">tutorial de uso do <em>Segment Editor</em></a>. Criar segmentação/segmentos não é necessário caso prefira editar segmentos já existentes.</p>
            </li>
            <li>
            <p>Selecione o efeito <em>Smart foreground</em>.</p>
            </li>
            <li>
            <p>Selecione o segmento ao qual a operação será aplicada.</p>
            </li>
            <li>
            <p>Em <em>Operation</em>, selecione uma das operações:</p>
            </li>
            <ul>
                <li>
                <p><em>Fill inside</em>: preenche o segmento sobre a área útil da amostra.</p>
                </li>
                <li>
                <p><em>Erase outside</em>: exclui áreas já segmentadas sobre a área não-útil da amostra.</p>
                </li>
            </ul>
            <li>
            <p>Caso deseje aplicar a fragmentação (se disponível), prossiga com os passos abaixo. Caso contrário, certifique-se que a seção <em>Fragments</em> (abaixo de <em>Operation</em>) esteja indisponível ou que a opção <em>Split</em> esteja desmarcada, clique em <em>Apply</em> e aguarde o fim do processo.</p>
            </li>
        </ol>
        <header><h3>Fragmentação</h3></header>
        <ol start="6">
            <li>
            <p>Em <em>Fragments</em>, marque a opção <em>Split</em>.</p>
            </li>
            <li>
            <p>Selecione uma das opções:</p>
            </li>
            <ul>
                <li>
                <p><em>Keep all</em>: mantém todos os fragmentos.</p>
                </li>
                <li>
                <p><em>Filter the largest</em>: mantém apenas os fragmentos de maior área. Digite a quantidade de fragmentos a preservar.</p>
                </li>
            </ul>
            <li>
            <p> Caso utilize a <b>versão pública do GeoSlicer</b>, um campo <em>Annotations</em> deve estar visível, e os passos a seguir deverão ser executados. Caso contrário, pule este passo. 
            </li>
            <ul>
                <li>
                <p>Adicione dois novos segmentos à segmentação de saída. Alternativamente, você pode criar uma nova segmentação com dois segmentos.</p>
                </li>
                <li>
                <p>Selecione um dos novos segmentos criados. Utilize efeitos de marcação como <a href="../../../../Modules/Thin_section/SegmentEditor.html#desenho" style="color: #007bff;">Desenho (<em>Draw</em>)</a>, <a href="../../../../Modules/Thin_section/SegmentEditor.html#pintura" style="color: #007bff;">Pintura (<em>Paint</em>)</a> ou <a href="../../../../Modules/Thin_section/SegmentEditor.html#tesoura" style="color: #007bff;">Tesoura (<em>Scissors</em>)</a> para demarcar pequenas amostras da textura da rocha. Veja mais informações em <a href="../../../../Modules/Segmenter/Semiauto/semiauto.html" style="color: #007bff;">Treinamento de modelo</a>.</p> <!-- Futuramente, quando houver uma página sobre o uso da interface do Model Training, será melhor referenciar para ela-->
                </li>
                <li>
                <p>Selecione o outro novo segmento. Demarque agora pequenas amostras da resina de poro na imagem.</p>
                </li>
                <li>
                <p>Retorne ao efeito <em>Smart foreground</em> e reselecione o segmento ao qual a operação será aplicada.
                <li>
                <p>Em <em>Annotations</em>, selecione a segmentação que contém os segmentos demarcados.</p>
                </li>
                <li>
                <p>Em <em>Texture samples</em> e <em>Resin samples</em>, selecione os segmentos que demarcam, respectivamente, a textura e a resina.</p>
                </li>
            </ul>
            <li>
            <p>Clique em <em>Apply</em> e aguarde o fim do processo.</p></p>
            </li>
        </ol>
    </div>
    <div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../../../../assets/videos/segment_editor_smart_foreground_public.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Vídeo: Primeiro Plano Inteligente. Lâmina adaptada de <a href="https://onlinelibrary.wiley.com/doi/10.1155/2022/8328764" style="color: #007bff;">Luo <em>et al.</em>, 2022</a> (<a href="https://creativecommons.org/licenses/by/4.0/" style="color: #007bff;">CC BY 4.0</a>).</p>
    </div>
</div>