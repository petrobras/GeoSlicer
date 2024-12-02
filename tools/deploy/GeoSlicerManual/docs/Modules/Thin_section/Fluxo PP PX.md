<div class="content-wrapper" markdown="1">
<div class="text-content" markdown="1">
<h1>Fluxo PP/PX</h1>
<p>Este fluxo é utilizado para calcular métricas de poro a partir de uma imagem PP (polarização plana) e uma imagem PX (polarização cruzada).</p>
<p><a href="../../Outros/fluxos.md">Saiba mais sobre fluxos</a></p>
<div markdown="1">
{% include-markdown "../FlowSteps/load_pp_px.md" %}
{% include-markdown "../FlowSteps/scale.md" %}
{% include-markdown "../FlowSteps/register.md" %}
{% include-markdown "../FlowSteps/soi.md" %}
{% include-markdown "../FlowSteps/smartseg.md" %}
{% include-markdown "../FlowSteps/manual_seg.md" %}
{% include-markdown "../FlowSteps/auto_label.md" %}
{% include-markdown "../FlowSteps/label_editor.md" %}
{% include-markdown "../FlowSteps/finish.md" %}
</div>
</div>
<div class="video-wrapper">
<video class="floating-video" controls>
<source src="../../assets/videos/thin_section_pp_px_flow.webm" type="video/webm">
Sorry, your browser does not support the video tag.
</video>
<p class="video-caption">Video: Executando o fluxo PP/PX</p>
</div>
</div>
