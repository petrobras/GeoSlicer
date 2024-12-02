PARAMETERS = {
    "enforced_swi_1": {
        "display_name": "Min SWi",
        "tooltip": "Minimum SWi (water fraction)",
        "dtype": "multifloat",
        "default_value": 0.0,
        "layout": "cycle_1",
    },
    "enforced_pc_1": {
        "display_name": "Final cycle Pc (kPa)",
        "dtype": "multifloat",
        "default_value": 200000.0,
        "layout": "cycle_1",
        "conversion_factor": 1000,
    },
    "enforced_steps_1": {
        "display_name": "Sw step length",
        "dtype": "multifloat",
        "default_value": 0.005,
        "layout": "cycle_1",
    },
    "enforced_swi_2": {
        "display_name": "Max SW",
        "tooltip": "Maximum SW (water fraction)",
        "dtype": "multifloat",
        "default_value": 1.0,
        "layout": "cycle_2",
    },
    "enforced_pc_2": {
        "display_name": "Final cycle Pc (kPa)",
        "dtype": "multifloat",
        "default_value": -200000.0,
        "layout": "cycle_2",
        "conversion_factor": 1000,
    },
    "enforced_steps_2": {
        "display_name": "Sw step length",
        "dtype": "multifloat",
        "default_value": 0.005,
        "layout": "cycle_2",
    },
    "inject_1": {
        "display_name": "Inject from",
        "dtype": "checkbox",
        "layout": "cycle_1",
        "true_value": "T",
        "false_value": "F",
        "default_values": {"left": True, "right": False},
    },
    "inject_2": {
        "display_name": "Inject from",
        "dtype": "checkbox",
        "layout": "cycle_2",
        "true_value": "T",
        "false_value": "F",
        "default_values": {"left": True, "right": False},
    },
    "produce_1": {
        "display_name": "Produce from",
        "dtype": "checkbox",
        "layout": "cycle_1",
        "true_value": "T",
        "false_value": "F",
        "default_values": {"left": False, "right": True},
    },
    "produce_2": {
        "display_name": "Produce from",
        "dtype": "checkbox",
        "layout": "cycle_2",
        "true_value": "T",
        "false_value": "F",
        "default_values": {"left": False, "right": True},
    },
    "seed": {
        "display_name": "Simulation seed",
        "layout": "options",
        "dtype": "singleint",
        "default_value": 0,
    },
    "calc_box_lower_boundary": {
        "display_name": "Lower box boundary",
        "layout": "options",
        "dtype": "singlefloat",
        "default_value": 0.1,
    },
    "calc_box_upper_boundary": {
        "display_name": "Upper box boundary",
        "layout": "options",
        "dtype": "singlefloat",
        "default_value": 0.9,
    },
    "subresolution_volume": {
        "display_name": "Subresolution volume",
        "layout": "options",
        "dtype": "singlefloat",
        "default_value": 0.0,
    },
    "water_viscosity": {
        "display_name": "Viscosity (cP)",
        "dtype": "multifloat",
        "default_value": 1.0,
        "layout": "water_parameters",
        "conversion_factor": 1,
    },
    "water_resistivity": {
        "display_name": "Resistivity (Ohm*m)",
        "dtype": "multifloat",
        "default_value": 1.2,
        "layout": "water_parameters",
        "hidden": True,
    },
    "water_density": {
        "display_name": "Density (kg/m3)",
        "dtype": "multifloat",
        "default_value": 1000.0,
        "layout": "water_parameters",
    },
    "oil_viscosity": {
        "display_name": "Viscosity (cP)",
        "dtype": "multifloat",
        "default_value": 10.0,
        "min_value": 1.0,
        "max_value": 600.0,
        "layout": "oil_parameters",
        "conversion_factor": 1,
    },
    "oil_resistivity": {
        "display_name": "Resistivity (Ohm*m)",
        "dtype": "multifloat",
        "default_value": 1000.0,
        "layout": "oil_parameters",
        "hidden": True,
    },
    "oil_density": {
        "display_name": "Density (kg/m3)",
        "dtype": "multifloat",
        "default_value": 900.0,
        "layout": "oil_parameters",
    },
    "clay_resistivity": {
        "display_name": "Resistivity (Ohm*m)",
        "dtype": "multifloat",
        "default_value": 2.0,
        "layout": "clay_parameters",
        "hidden": True,
    },
    "interfacial_tension": {
        "display_name": "Interfacial tension (mN/m)",
        "dtype": "multifloat",
        "default_value": 30.0,
        "layout": "fluid_properties",
        "step_spacing": "logarithmic",
    },
    "pore_fill_algorithm": {
        "display_name": "Algorithm",
        "layout": "pore_fill",
        "dtype": "combobox",
        "default_value": 1,
        "display_names": {
            "blunt1": "blunt1",
            "blunt2": "blunt2",
            "oren1": "oren1",
            "oren2": "oren2",
        },
    },
    "run_third_cycle": {
        "display_name": "Calculate Amott Wettability",
        "layout": "options",
        "dtype": "checkbox",
        "true_value": "",
        "false_value": "//",
        "default_values": {"": True},
    },
    "create_sequence": {
        "display_name": "Create animation node",
        "layout": "options",
        "dtype": "singlecheckbox",
        "true_value": "T",
        "false_value": "F",
        "default_value": False,
    },
    "create_ca_distributions": {
        "display_name": "Create CA distribution nodes",
        "layout": "options",
        "dtype": "singlecheckbox",
        "true_value": "T",
        "false_value": "F",
        "default_value": False,
    },
    "keep_temporary": {
        "display_name": "Keep temporary files",
        "layout": "options",
        "dtype": "singlecheckbox",
        "true_value": "T",
        "false_value": "F",
        "default_value": False,
    },
    "max_subprocesses": {
        "display_name": "Max subprocesses",
        "layout": "options",
        "dtype": "integerspinbox",
        "minimum_value": 1,
        "maximum_value": 256,
        "default_value": 8,
    },
    "timeout_enabled": {
        "display_name": "Enable timeout",
        "layout": "options",
        "dtype": "singlecheckbox",
        "true_value": "T",
        "false_value": "F",
        "default_value": True,
    },
}

for i, default in enumerate((0.0, 0.5, 1.0, 2.0, 5.0, 10.0)):
    PARAMETERS[f"pore_fill_weight_a{i+1}"] = {
        "display_name": f"Weight A{i+1}",
        "layout": "pore_fill",
        "dtype": "singlefloat",
        "default_value": default,
    }

PARAMETERS["frac_contact_angle_fraction"] = {
    "display_name": "Fraction",
    "dtype": "multifloat",
    "default_value": 0.0,
    "layout": "frac",
}
PARAMETERS["frac_contact_angle_volbased"] = {
    "display_name": "Fraction distribution",
    "layout": "frac",
    "dtype": "combobox",
    "default_value": 0,
    "display_names": {
        "Pore volume based": "T",
        "Quantitative split between pores": "F",
    },
}
PARAMETERS["frac_contact_angle_corrdiam"] = {
    "display_name": "Correlation diameter",
    "dtype": "multifloat",
    "default_value": 7.0,
    "layout": "frac",
}
PARAMETERS["frac_contact_method"] = {
    "display_name": "Fraction correlation",
    "layout": "frac",
    "dtype": "combobox",
    "default_value": 0,
    "display_names": {
        "Random": "rand",
        "Spatially correlated": "corr",
        "Smaller pores": "rMin",
        "Larger pores": "rMax",
    },
}
PARAMETERS["second_contact_fraction"] = {
    "display_name": "Fraction",
    "dtype": "multifloat",
    "default_value": 0.0,
    "layout": "second",
}
PARAMETERS["oilInWCluster"] = {
    "display_name": "oilInWCluster",
    "dtype": "combobox",
    "default_value": 0,
    "display_names": {
        "True": "T",
        "False": "F",
    },
    "layout": "frac",
}
PARAMETERS["frac_cluster_count"] = {
    "display_name": "Cluster count center",
    "tooltip": "Number of elements in each cluster",
    "dtype": "singleint",
    "default_value": 20.0,
    "min_value": 0,
    "max_value": 10000,
    "layout": "frac",
}
PARAMETERS["frac_cluster_count_range"] = {
    "display_name": "Cluster count range",
    "dtype": "singleint",
    "default_value": 10.0,
    "min_value": 0,
    "max_value": 10000,
    "layout": "frac",
}
PARAMETERS["frac_cluster_count_del"] = {
    "display_name": "Delta",
    "dtype": "multifloat",
    "default_value": -1.0,
    "layout": "frac",
}
PARAMETERS["frac_cluster_count_eta"] = {
    "display_name": "Gamma",
    "dtype": "multifloat",
    "default_value": -1.0,
    "layout": "frac",
}
PARAMETERS["frac_cluster_count_rctrl"] = {
    "display_name": "Cluster correlation",
    "layout": "frac",
    "dtype": "combobox",
    "default_value": 0,
    "display_names": {
        "Uncorrelated": "rand",
        "Positive radius": "rMax",
        "Negative radius": "rMin",
    },
}

for i in ("init", "second", "equil", "frac"):
    PARAMETERS[f"{i}_contact_model"] = {
        "display_name": "Model",
        "layout": i,
        "dtype": "combobox",
        "default_value": 2,
        "display_names": {
            "Model 1 (equal angles)": "1",
            "Model 2 (constant difference)": "2",
            "Model 3 (Morrow curve)": "3",
        },
    }
    PARAMETERS[f"{i}_contact_angle"] = {
        "display_name": "CA center (deg)",
        "tooltip": "Contact angle distribution center (degrees)",
        "dtype": "multifloat",
        "default_value": 20.0,
        "min_value": 0.0,
        "max_value": 180.0,
        "layout": i,
    }
    PARAMETERS[f"{i}_contact_angle_range"] = {
        "display_name": "CA range (deg)",
        "tooltip": "Contact angle distribution range (degrees)",
        "dtype": "multifloat",
        "default_value": 10.0,
        "min_value": 0.0,
        "max_value": 180.0,
        "layout": i,
    }
    PARAMETERS[f"{i}_contact_angle_del"] = {
        "display_name": "Delta",
        "dtype": "multifloat",
        "default_value": -1.0,
        "layout": i,
    }
    PARAMETERS[f"{i}_contact_angle_eta"] = {
        "display_name": "Gamma",
        "dtype": "multifloat",
        "default_value": -1.0,
        "layout": i,
    }
    PARAMETERS[f"{i}_contact_angle_rctrl"] = {
        "display_name": "CA correlation",
        "tooltip": "Contact angle correlation",
        "layout": i,
        "dtype": "combobox",
        "default_value": 0,
        "display_names": {
            "Uncorrelated": "rand",
            "Positive radius": "rMax",
            "Negative radius": "rMin",
        },
    }
    PARAMETERS[f"{i}_contact_angle_separation"] = {
        "display_name": "Separation (degrees)",
        "dtype": "multifloat",
        "default_value": 25.2,
        "layout": i,
    }

del PARAMETERS["second_contact_model"]
del PARAMETERS["second_contact_angle_separation"]

# del PARAMETERS["frac_contact_model"]
del PARAMETERS["frac_contact_angle_separation"]
