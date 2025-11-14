## <a id="qemscan-flow">Fluxo QEMSCAN</a>

Este fluxo é utilizado para calcular métricas de poro a partir de uma imagem QEMSCAN.

{{ video("thin_section_qemscan_flow.webm", caption="Video: Executando o fluxo QEMSCAN") }}

{{ include_markdown("FlowStepsLoadQemscan") }}
{{ include_markdown("FlowStepsSoi") }}
{{ include_markdown("FlowStepsAutoLabel") }}

Observação: como este fluxo não carrega uma foto de lâmina de referência, o algoritmo *watershed* usa apenas o segmento especificado como entrada.

{{ include_markdown("FlowStepsLabelEditor") }}
{{ include_markdown("FlowStepsFinish") }}
