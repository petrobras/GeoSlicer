<div class="content-wrapper" markdown="1">
<div class="text-content" markdown="1">
<h1>Fluxo QEMSCAN</h1>
<p>Este fluxo é utilizado para calcular métricas de poro a partir de uma imagem QEMSCAN.</p>
<p><a href="../../Outros/fluxos.md">Saiba mais sobre fluxos</a></p>
<div markdown="1">
{% include-markdown "../FlowSteps/load_qemscan.md" %}
{% include-markdown "../FlowSteps/soi.md" %}
{% include-markdown "../FlowSteps/auto_label.md" %}

Observação: como este fluxo não carrega uma foto de lâmina de referência, o algoritmo *watershed* usa apenas o segmento especificado como entrada.

{% include-markdown "../FlowSteps/label_editor.md" %}
{% include-markdown "../FlowSteps/finish.md" %}
</div>
</div>
<div class="video-wrapper">
<video class="floating-video" controls>
<source src="../../assets/videos/thin_section_qemscan_flow.webm" type="video/webm">
Sorry, your browser does not support the video tag.
</video>
<p class="video-caption">Video: Executando o fluxo QEMSCAN</p>
</div>
</div>
