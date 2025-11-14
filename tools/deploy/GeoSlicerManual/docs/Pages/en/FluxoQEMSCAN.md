## <a id="qemscan-flow">QEMSCAN Flow</a>

This flow is used to calculate pore metrics from a QEMSCAN image.

{{ video("thin_section_qemscan_flow.webm", caption="Video: Executando o fluxo QEMSCAN") }}

{{ include_markdown("FlowStepsLoadQemscan") }}
{{ include_markdown("FlowStepsSoi") }}
{{ include_markdown("FlowStepsAutoLabel") }}

Note: as this flow does not load a reference thin section image, the *watershed* algorithm only uses the specified segment as input.

{{ include_markdown("FlowStepsLabelEditor") }}
{{ include_markdown("FlowStepsFinish") }}