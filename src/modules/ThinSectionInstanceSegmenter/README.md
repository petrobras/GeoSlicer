# ThinSection Instance Segmenter

Para atualizar um modelo de segmentação de instância no geoslicer é necessário apenas copiar um arquivo de pesos ".pth" que foram treinados com a biblioteca mmdet para a pasta "slicerltrace/src/ltrace/ltrace/assets/trained_models".

A configuração do modelo já é normalmente salva junto com o arquivo de pesos, e pode ser conferida em:
```python
import torch
model = torch.load("new_model.pth")
config = model["meta"]["cfg"]
print(config)
```
Algumas vezes, os imports podem falhar durante a inferencia, nesses casos é necessário adaptar o config no dicionário, eliminando a dependencia deles.

É esperado também que algumas variáveis sejam definidas nesse dicionário, afim de que apareçam na interface do Geoslicer da maneira correta. Assim as seguintes entradas são esperadas para qualquer modelo de segmentação de instância:

```python
model = {
	*"title": "Mask R-CNN (str)",
   	*"config": {
		"meta": {
			"kind": "torch",  # kind is one of ["torch", ...]
			"is_segmentation_model": False "whether this models performs segmentation or regression (bool)",
			"is_instance_seg_model": True "whether this models performs instance segmentation (bool)",
		},
    },
	"meta": {
		"epoch", 
		"iter", 
		"cfg", 
		"seed", 
		"experiment_name", 
		"time", 
		"mmengine_version", 
		"dataset_meta"
	}
	"state_dict", 
	"message_hub", 
	"optimizer",
```

As entradas com "*" precisam ser adicionadas manualmente.
