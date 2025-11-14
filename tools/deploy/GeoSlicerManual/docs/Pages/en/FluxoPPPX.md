## <a id="pp-flow">PP/PX Flow</a>

This flow is used to calculate pore metrics from a PP (plane polarization) image and a PX (cross polarization) image.

{{ video("thin_section_pp_px_flow.webm", caption="Video: Executing the PP/PX flow") }}

{{ include_markdown("FlowStepsLoadPpPx") }}
{{ include_markdown("FlowStepsScale") }}
{{ include_markdown("FlowStepsRegister") }}
{{ include_markdown("FlowStepsSoi") }}
{{ include_markdown("FlowStepsSmartSeg") }}
{{ include_markdown("FlowStepsManualSeg") }}
{{ include_markdown("FlowStepsAutoLabel") }}
{{ include_markdown("FlowStepsLabelEditor") }}
{{ include_markdown("FlowStepsFinish") }}