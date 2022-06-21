import re

from collections import defaultdict

import pandas as pd
import numpy as np

from ltrace.slicer.helpers import getCountForLabels


non_pores_pattern = re.compile(r"^(?:(?:Non[- ]?Pores?)|(?:Not[- ]?Pores?)|(?:Não[- ]Poros?))$", flags=re.IGNORECASE)
pores_pattern = re.compile(r"^(?:(?:Pores?)|(?:Poros?))$", flags=re.IGNORECASE)


def detect_pore_segment(segments):
    matches = []
    for label, name in segments.items():
        if non_pores_pattern.match(name):
            continue

        pattern_exists = pores_pattern.match(name)
        if pattern_exists:
            matches.append(label)
    return matches


class Segment:
    def __init__(self, name_en, name_pt) -> None:
        self.name_en = name_en
        self.name_pt = name_pt

    def match(self, description):
        return re.match(
            r"^(?:" + f"{self.name_en}" + "|" + f"{self.name_pt}" + ")( |$)", description, flags=re.IGNORECASE
        )


class Pore(Segment):
    def __init__(self) -> None:
        super().__init__("Pore", "Poro")

    def match(self, description):
        if non_pores_pattern.match(description):
            return False
        return pores_pattern.match(description)


class Mineral(Segment):
    def __init__(self, density, bulk_modulus, shear_modulus, name_en, name_pt) -> None:
        super().__init__(name_en, name_pt)

        self.density = density
        self.bulk_modulus = bulk_modulus
        self.shear_modulus = shear_modulus


phases = {
    "calcite": Mineral(density=2.71, bulk_modulus=70.2, shear_modulus=29.0, name_pt="Calcita", name_en="Calcite"),
    "dolomite": Mineral(density=2.87, bulk_modulus=76.4, shear_modulus=49.7, name_pt="Dolomita", name_en="Dolomite"),
    "clayminerals": Mineral(
        density=2.55, bulk_modulus=25.0, shear_modulus=9.0, name_pt="Mg-Argilominerais", name_en="Mg-Clay Minerals"
    ),
    "quartz": Mineral(density=2.65, bulk_modulus=37.0, shear_modulus=44.0, name_pt="Quartzo", name_en="Quartz"),
    "pore": Pore(),
    "other": Segment("Others", " Outros"),
}

qemscan_patterns = [
    ("Calcita", "calcite"),
    ("Dolomita", "dolomite"),
    ("Mg-Argilominerais", "clayminerals"),
    ("Poros", "pore"),
    ("Quartzo", "quartz"),
    ("Outros", "other"),  # hide others because it is weighted by using a relative total
]


def detect_qemscan(segments, segments_map):
    patterns = [p for p in qemscan_patterns]
    founds = defaultdict(int)
    for label, name in segments.items():
        found_idx = None
        for i, pattern in enumerate(patterns):
            phase = phases[pattern[1]]
            if phase.match(name):
                found_idx = i
                count = segments_map[label]["count"]
                founds[pattern[1]] += count
                break

        # group on others if not matched
        # note: segment_map has only nonzero segments
        if found_idx is None and label in segments_map:
            count = segments_map[label]["count"]
            founds["other"] += count

    return founds


def average_moduli(phase_vol_fraction, func):
    bulk = []
    shear = []
    vol_frac = []
    for key, v in phase_vol_fraction.items():
        try:
            phase = phases[key]
            if phase.bulk_modulus <= 0 or phase.shear_modulus <= 0:
                raise ValueError("bulk and shear modulus must be greater than 0")

            bulk.append(phase.bulk_modulus)
            shear.append(phase.shear_modulus)
            vol_frac.append(v)
        except (KeyError, AttributeError):
            pass

    assert len(vol_frac) == len(bulk)
    assert len(bulk) == len(shear)

    return func(vol_frac, bulk), func(vol_frac, shear)


def reuss_average_function(vol_frac, X):
    X_reuss = 1.0 / sum(f / x for f, x in zip(vol_frac, X))
    return X_reuss


def voigt_average_function(vol_frac, X):
    X_voigt = sum(f * x for f, x in zip(vol_frac, X))
    return X_voigt


def get_modulus_and_density(phase_volume, data: dict):
    relative_total = sum([v for v in phase_volume.values()])
    phase_vol_fraction = defaultdict(int)
    phase_vol_fraction.update({k: count / relative_total for k, count in phase_volume.items()})

    density = (
        phase_vol_fraction["calcite"] * phases["calcite"].density
        + phase_vol_fraction["quartz"] * phases["quartz"].density
        + phase_vol_fraction["clayminerals"] * phases["clayminerals"].density
        + phase_vol_fraction["dolomite"] * phases["dolomite"].density
        + phase_vol_fraction["pore"] * 1
    )

    phase_volume_mineral_mix = {k: v for k, v in phase_volume.items() if k != "pore"}
    relative_total_mineral_mix = sum([v for v in phase_volume_mineral_mix.values()])
    phase_vol_fraction_mineral_mix = defaultdict(int)
    phase_vol_fraction_mineral_mix.update(
        {k: count / relative_total_mineral_mix for k, count in phase_volume_mineral_mix.items()}
    )

    bulk_lower, shear_lower = average_moduli(phase_vol_fraction_mineral_mix, reuss_average_function)
    bulk_upper, shear_upper = average_moduli(phase_vol_fraction_mineral_mix, voigt_average_function)

    r_ = lambda v: np.round(v, decimals=5)

    data["Density (g/cm^3)"] = r_(density)
    data["Bulk modulus (Gpa) - Mineral mix (lower)"] = r_(bulk_lower)
    data["Bulk modulus (Gpa) - Mineral mix (upper)"] = r_(bulk_upper)
    data["Shear modulus (Gpa) - Mineral mix (lower)"] = r_(shear_lower)
    data["Shear modulus (Gpa) - Mineral mix (upper)"] = r_(shear_upper)


def generate_basic_petrophysics_output(target_labels, all_labels, segment_map):
    """Create report as a pandas.DataFrame and store it"""
    # segment_map = getCountForLabels(self.__label_map_node, self.__roi_node)

    # total_voxel_count = segment_map["total"]
    del segment_map["total"]
    SOI_voxel_count = sum([segment_map[k]["count"] for k in segment_map])

    data = {}

    pore_labels = detect_pore_segment(target_labels)
    if pore_labels:
        porosity = sum([segment_map[idx]["count"] for idx in pore_labels]) / SOI_voxel_count
        data["Porosity (%)"] = np.round(porosity, decimals=5) * 100

    phase_volume = detect_qemscan(all_labels, segment_map)
    if len(phase_volume) > 2 or (len(phase_volume) == 2 and "other" not in phase_volume):
        get_modulus_and_density(phase_volume, data)

    accumulated = 0
    # TODO make this round to 100%
    for key, volume in phase_volume.items():
        data[f"{key} (%)"] = np.round((volume / SOI_voxel_count), decimals=5) * 100
        accumulated += volume

    df = pd.DataFrame(
        data={"Properties": [key for key in data], "Values": [repr(val) for val in data.values()]}, dtype=str
    )

    return df
