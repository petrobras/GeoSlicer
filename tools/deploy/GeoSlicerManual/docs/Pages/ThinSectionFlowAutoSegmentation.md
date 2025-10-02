## Segmenter

Módulo *Segmenter* para segmentar aumomaticamente uma imagem, conforme descrito nos passos abaixo:

1.  Entre na seção de segmentação *Smart-seg* do ambiente.
2.  Selecione o *Pre-trained models*.
3.  O modelo *Carbonate Multiphase(Unet)* foi utilizado como exemplo.
4.  Check Model inputs and outputs.
5.  Selecione um SOI (*Segment of interest*) criado previamente ao parâmetro *Region SOI*
6.  Selecione uma imagem PP (*Plane polarized light*) ao parâmetro *PP*
7.  Selecione uma imagem PX (*Crossed polarized light*) ao parâmetro *PX*
8.  Um prefixo para o nome da segmentação resultante é gerado mas esse pode ser modificado na area de *Output Prefix*.
9.  Clique em *Apply* e aguarde a finalização. Um nó de segmentação aparecerá e sua visualização poderá ser alterada no Explorer.

{{ video("thin_section_smart_seg.webm", caption="Video: Segmentação automática com modelo pré treinado") }}
