# Instructions to create new models

The models used at this CLI are created and trained using the pytorch library.

After the training procedure, it's necessary to save some metadata and the `model_state_dict` of the network, in the format shown bellow:

```python
saved_model = {
	"title": "Name shown in Geoslicer (str)",
  
  "model_state_dict": "Model weights (OrderedDict[str, torch.Tensor])",
  
  "config": {
  
    "meta": {
      "kind": "torch",  # kind is one of ["torch", ...]
      "is_segmentation_model": "whether this models performs segmentation or regression (bool)",
      "spatial_dims": "model output dimensions (int)",
      "input_roi_shape": "model dimensions (Optional[int])",
      "pixels_per_mm": "model dimensions (Optional[int])",
      
      "inputs": OrderedDict([
        ("input_1", {
          "spatial_dims": "variable_1 dimensions (int)",
          "n_channels": "variable_1 expected number of channels (int)",
        }),
        ("input_2", {
          "spatial_dims": "variable_2 dimensions (int)",
          "n_channels": "variable_2 expected number of channels (int)",
        }),
      ]),
      
      "pre_processed_inputs": OrderedDict([
        ("pre_processed_input_1", {
          "spatial_dims": "variable_1 dimensions (Optional[int])",
          "n_channels": "variable_1 expected number of channels (Optional[int])",
        }),
      ]),
      
      "outputs": OrderedDict([
        ("output_1", {
          "spatial_dims": "variable_1 dimensions (int)",
          "n_channels": "variable_1 expected number of channels (int)",
          # below ones are needed if this output is a segmentation
          "class_indices": "Class numbers that will appear in GeoSlicer [0,1,2]->[*class_indices]; i.e.: [1,2,3]. GeoSlicer does not like zero indexed meaningful labels (Sequence[int])",
          "class_names": "Array of colors in the hex format. Example: '#00FF00' (Sequence[str])",
          "class_colors": "Array with the labels of each mineral (Sequence[str])",
        }),
      ]),
    },
  
    "model": {
      "name": "Model class name (str)"
      "params": "Keywords used to build model using the class named above (Dict[str, Any])"
    },
    
    "transforms": {
      "pre_processing_transforms": [
        # chain of transforms applied to volumes before using model. Example:
        {
          "name": "ConcatenateTransform",
          "params": {
            "key_groups": {
              "pre_processed_input_1": ["input_1", "input_2"],
            },
            "axis": 0,
          },
        },
        {
          "name": "MinMaxTransform",
          "params": {
            "key": "pre_processed_input_1",
            "move_from": (0, 255),
            "move_to": (0, 1),
          },
        }
      ],
      
      "post_processing_transforms": [
        # chain of transforms applied to model outputs. Example:
        {
          "name": "ArgmaxTransform",
          "params": {
            "key": "output_1",
            "dim": 1,
            "dtype": "int8",
            "keepdim": True,
            "first_label": 1,
            "batch_dim": True,
          }
        }
      ]
    },
    
  }
}

torch.save(saved_model, 'model_name.pth')
```

For composed models you must first generate the `saved_model` dict for each model and then use the follwing format so create the right
.pth file:

python
```
saved_composed_model = {
	"title": "Name shown in Geoslicer (str)",
  
  "models_to_compose": # Dict with saved_model dicts to be composed (OrderedDict[str, Dict]). Ex:
    OrderedDict(
        [
            ("pore_model", pore_model),
            ("mineral_model", mineral_model),
        ]
    )

  "config": {
  
    "inference_combination": # describe how to combine all the inferences on a single oputput. Ex:
        [ 
          {"model_index": 1, "take": [1, 2, 3, 5]},
          {"model_index": 0, "take": [4]},
        ]


    "meta": {
      "kind": "torch",  # kind is one of ["torch", ...]
      "is_segmentation_model": "whether this models performs segmentation or regression (bool)",
      "spatial_dims": "model output dimensions (int)",
      "input_roi_shape": "model dimensions (Optional[int])",
      "pixels_per_mm": "model dimensions (Optional[int])",
      
      "inputs": OrderedDict([
        ("input_1", {
          "spatial_dims": "variable_1 dimensions (int)",
          "n_channels": "variable_1 expected number of channels (int)",
        }),
        ("input_2", {
          "spatial_dims": "variable_2 dimensions (int)",
          "n_channels": "variable_2 expected number of channels (int)",
        }),
      ]),
      
      "outputs": OrderedDict([
        ("output_1", {
          "spatial_dims": "variable_1 dimensions (int)",
          "n_channels": "variable_1 expected number of channels (int)",
          # below ones are needed if this output is a segmentation
          "class_indices": "Class numbers that will appear in GeoSlicer [0,1,2]->[*class_indices]; i.e.: [1,2,3]. GeoSlicer does not like zero indexed meaningful labels (Sequence[int])",
          "class_names": "Array of colors in the hex format. Example: '#00FF00' (Sequence[str])",
          "class_colors": "Array with the labels of each mineral (Sequence[str])",
        }),
      ]),
    },

  }
}


torch.save(saved_composed_model, 'composed_model_name.pth')
```

After generated the `.pth` file in the above format, it's necessary to put it in one of the following folders: 

`src/ltrace/ltrace/assets/trained_models/*Env`

The module will load the trained models only in the correct Geoslicer environment.

To change a trained model's .pth properties mannualy, use:

```python
saved_model = torch.load('old_model.pth')
saved_model[''] = 6
torch.save(saved_model, 'new_model.pth')
```
