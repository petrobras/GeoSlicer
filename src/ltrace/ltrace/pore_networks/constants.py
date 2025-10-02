IJKTORAS = (1, 1, 1)

PNF_TIMEOUT = 36000

MODELS_STR = {
    "model1": "Model 1 (equal angles)",
    "model2": "Model 2 (constant diference)",
    "model3": "Model 3 (Morrow curve)",
}

RCTRL_OPTIONS = [
    "rMax",
    "rMin",
    "rand",
]

PORE_FILL_ALGS = [
    "blunt1",
    "blunt2",
    "oren1",
    "oren2",
]

PORE_SCALE_DISTRBUTION_METHOD = [
    "corr",
    "rMin",
    "rMax",
    "rand",
]

# PN_PROPERTIES are property name : number of columns
PN_PROPERTIES = {
    "pore.all": 1,
    "pore.coords": 3,
    "pore.equivalent_diameter": 1,
    "pore.extended_diameter": 1,
    "pore.geometric_centroid": 3,
    "pore.global_peak": 3,
    "pore.inscribed_diameter": 1,
    "pore.local_peak": 3,
    "pore.phase": 1,
    "pore.subresolution_porosity": 1,
    "pore.region_label": 1,
    "pore.region_volume": 1,
    "pore.shape_factor": 1,
    "pore.surface_area": 1,
    "pore.volume": 1,
    "pore.xmax": 1,
    "pore.xmin": 1,
    "pore.ymax": 1,
    "pore.ymin": 1,
    "pore.zmax": 1,
    "pore.zmin": 1,
    "throat.all": 1,
    "throat.area_full": 1,
    "throat.conns": 2,
    "throat.conns_0_length": 1,
    "throat.conns_1_length": 1,
    "throat.cross_sectional_area": 1,
    "throat.direct_length": 1,
    "throat.equivalent_diameter": 1,
    "throat.global_peak": 3,
    "throat.inscribed_diameter": 1,
    "throat.mid_length": 1,
    "throat.perimeter": 1,
    "throat.phases": 2,
    "throat.shape_factor": 1,
    "throat.total_length": 1,
    "throat.subresolution_porosity": 1,
}
