# Simulação de Permeabilidade Relativa (Krel)

<div class="content-wrapper">
    <div class="text-content">
        <h2>Simulação única de Krel (animação)</h2>
        <p>O fluxo abaixo permite simular e obter uma animação dos processos de <b>Drenagem</b> e <b>Embibição</b>:</p>
        <ol>
            <li>
            <p><b>Carregue</b> o volume no qual deseja executar a simulação;</p>
            </li>
            <li>
            <p>Realize a <b>Segmentação Manual</b> utilizando um dos segmentos para designar a região porosa da rocha;</p>
            </li>
            <li>
            <p>Separe os segmentos utilizando a aba <b>Inspector</b>, delimitando assim a região de cada um dos poros;</p>
            </li>
            <li>
            <p>Utilize a aba <b>Extraction</b><a href="../Modulos/PNExtraction.html"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a> para obter a rede de poros e ligações a partir do volume LabelMap gerado;</p>
            </li>
            <li>
            <p>Na aba <b>Simulation</b><a href="../Modulos/PNSimulation.html"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>, escolha a tabela de poros, no seletor Simulation selecione <b>"Two-phase"</b><a href="../Modulos/PNSimulation.html#two-phase"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
            </li>
            <li>
            <p>Marque a opção <b>"Create animation node"</b> na caixa "Simulation options"<a href="../Modulos/PNSimulation.html#simulation-options"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a> e clique no botão <b>"Apply"</b>;</p>
            </li>
			<li>
            <p>Ao finalizar a simulação, vá até a aba <b>"Cycles Visualization"</b> e selecione o nó de animação para visualizar o ciclo e a curva gerada;</p>
            </li>
        </ol>
    </div>
    <div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../../assets/videos/pnm_krel_animation.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Fluxo para simulação de permeabilidade relativa com animação.</p>
    </div>
</div>


<div class="content-wrapper">
    <div class="text-content">
        <h2 id=teste-de-sensibilidade>Teste de Sensibilidade</h2>
        <p>O fluxo abaixo permite que o usuário simule e obtenha uma nuvem de curvas de Krel na qual ele pode fazer diferentes análises para determinar as propriedades que são mais sensíveis:</p>
        <ol>
            <li>
            <p><b>Carregue</b> o volume no qual deseja executar a simulação;</p>
            </li>
            <li>
            <p>Realize a <b>Segmentação Manual</b> utilizando um dos segmentos para designar a região porosa da rocha;</p>
            </li>
            <li>
            <p>Separe os segmentos utilizando a aba <b>Inspector</b>, delimitando assim a região de cada um dos poros;</p>
            </li>
            <li>
            <p>Utilize a aba <b>Extraction</b><a href="../Modulos/PNExtraction.html"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a> para obter a rede de poros e ligações a partir do volume LabelMap gerado;</p>
            </li>
            <li>
            <p>Na aba <b>Simulation</b><a href="../Modulos/PNSimulation.html"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>, escolha a tabela de poros, no seletor Simulation selecione <b>"Two-phase"</b><a href="../Modulos/PNSimulation.html#two-phase"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
            </li>
            <li>
            <p>Selecione múltiplos valores para alguns parâmetros clicando no botão <b>"Multi"</b> (como fizemos para o centro das distribuições dos ângulos de contato no vídeo) - Você pode encontrar mais informações sobre os parâmetros na seção <b>"Two-phase"</b><a href="../Modulos/PNSimulation.html#two-phase"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
			</li>
            <li>
            <p>(Opcional) Salve os parâmetros selecionados usando a seção <b>"Save parameters"</b><a href="../Modulos/PNSimulation.html#salvarcarregar-tabela-de-selecao-de-parametros"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
			</li>
			<li>
			<p>Clique no botão <b>"Apply"</b> para rodar as várias simulações;</p>
            </li>
			<li>
            <p>Ao finalizar a execução, vá até a aba <b>"Krel EDA"</b> e selecione a tabela de parâmetros gerada para fazer diferentes análises usando os recursos de visualização da interface (nuvem de curvas, correlações de parâmetros e resultados, etc);</p>
            </li>
        </ol>
    </div>
	<div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../../assets/videos/pnm_sensibility.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Fluxo para Teste de Sensibilidade (variando parâmetros para múltiplas simulações Krel).</p>
    </div>
</div>


<div class="content-wrapper">
    <div class="text-content">
        <h2>Estimativa de Produção</h2>
        <p>O fluxo abaixo permite que o usuário simule e obtenha uma nuvem de curvas de Krel, em uma amostra de escala única:</p>
        <ol>
            <li>
            <p><b>Carregue</b> o volume no qual deseja executar a simulação;</p>
            </li>
            <li>
            <p>Realize a <b>Segmentação Manual</b> utilizando um dos segmentos para designar a região porosa da rocha;</p>
            </li>
            <li>
            <p>Separe os segmentos utilizando a aba <b>Inspector</b>, delimitando assim a região de cada um dos poros;</p>
            </li>
            <li>
            <p>Utilize a aba <b>Extraction</b><a href="../Modulos/PNExtraction.html"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a> para obter a rede de poros e ligações a partir do volume LabelMap gerado;</p>
            </li>
			<li>
            <p>Selecione múltiplos valores para alguns parâmetros clicando no botão <b>"Multi"</b> (como fizemos para o centro das distribuições dos ângulos de contato no vídeo) - Você pode encontrar mais informações sobre os parâmetros na seção <b>"Two-phase"</b><a href="../Modulos/PNSimulation.html#two-phase"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
			</li>
            <li>
            <p>(Opcional) Salve os parâmetros selecionados usando a seção <b>"Save parameters"</b><a href="../Modulos/PNSimulation.html#salvarcarregar-tabela-de-selecao-de-parametros"><img alt="Know More" src="../../assets/icons/saiba_mais.svg" class="know-more-icon"></a>;</p>
			</li>
			<li>
			<p>Clique no botão <b>"Apply"</b> para rodar as várias simulações;</p>
            </li>
			<li>
            <p>
			Ao finalizar a execução, vá até a aba <b>"Production Prediction"</b> e selecione a tabela de parâmetros gerada na simulação; Duas opções são disponíveis nessa interface: 
			<ul>
			<li>A primeira delas "Single Krel" é uma análise de cada simulação individual;</li>
			<li>A segunda "Sensitivity test" é uma estimativa da produção levando em conta todas as simulações feitas;</li>
			</ul>
			</p>
            </li>
        </ol>
    </div>
	<div class="video-wrapper">
        <video class="floating-video" controls>
            <source src="../../assets/videos/pnm_production.webm" type="video/webm">
            Sorry, your browser does not support the video tag.
        </video>
        <p class="video-caption">Video: Fluxo da estimativa de produção.</p>
    </div>
</div>

