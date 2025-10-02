## Fluxo QEMSCAN

Este fluxo é utilizado para calcular métricas de poro a partir de uma imagem QEMSCAN.

{{ video("thin_section_qemscan_flow.webm", caption="Video: Executando o fluxo QEMSCAN") }}

{% include-markdown "./FlowStepsLoadQemscan.md" %}
{% include-markdown "./FlowStepsSoi.md" %}
{% include-markdown "./FlowStepsAutoLabel.md" %}

Observação: como este fluxo não carrega uma foto de lâmina de referência, o algoritmo *watershed* usa apenas o segmento especificado como entrada.

{% include-markdown "./FlowStepsLabelEditor.md" %}
{% include-markdown "./FlowStepsFinish.md" %}
