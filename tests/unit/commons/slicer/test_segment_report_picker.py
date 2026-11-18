"""Pick mode's pure parts: the tooltip summary, the label under a point and the label to row map."""

import numpy as np
import pytest

from commons.slicer.segment_report_picker import (
    format_value,
    label_at,
    label_rows,
    segment_summary,
    split_unit,
)


@pytest.mark.parametrize(
    "column, expected",
    [
        ("area (mm^2)", ("area", "mm²")),
        ("volume (mm^3)", ("volume", "mm³")),
        ("perimeter_over_area (1/mm)", ("perimeter_over_area", "1/mm")),
        ("label", ("label", "")),
    ],
)
def test_split_unit(column, expected):
    assert split_unit(column) == expected


@pytest.mark.parametrize(
    "text, expected",
    [("0.123456789", "0.1235"), ("12345.6", "1.235e+04"), ("42", "42"), ("Mesoporo médio", "Mesoporo médio")],
)
def test_format_value(text, expected):
    assert format_value(text) == expected


def test_2d_summary_shows_the_main_2d_columns_with_units():
    row = {
        "label": "7",
        "voxelCount": "120",
        "area (mm^2)": "0.0123456",
        "max_feret (mm)": "0.2",
        "min_feret (mm)": "0.1",
        "aspect_ratio": "0.5",
        "eccentricity": "0.866",
        "pore_size_class": "Mesoporo pequeno",
    }

    summary = segment_summary(7, row)

    assert summary.startswith("<b>Segment 7</b> &middot; Mesoporo pequeno")
    for expected in ("area", "0.01235", "mm²", "max_feret", "min_feret", "aspect_ratio"):
        assert expected in summary
    for hidden in ("voxelCount", "eccentricity", "volume"):
        assert hidden not in summary
    assert summary.index("area") < summary.index("max_feret") < summary.index("min_feret")
    assert "Ctrl+click" in summary


def test_3d_summary_shows_the_main_3d_columns():
    row = {
        "label": "3",
        "volume (mm^3)": "1.5",
        "max_feret (mm)": "2",
        "sphere_diameter_from_volume (mm)": "1.42",
        "aspect_ratio": "0.4",
        "elongation": "0.3",
        "flatness": "0.2",
        "ellipsoid_area (mm^2)": "9",
        "coordination_number": "4",
        "pore_size_class": "Mesoporo grande",
    }

    summary = segment_summary(3, row)

    for expected in ("volume", "mm³", "sphere_diameter_from_volume", "elongation", "flatness", "coordination_number"):
        assert expected in summary
    assert "ellipsoid_area" not in summary
    assert "min_feret" not in summary


def test_summary_skips_missing_values_and_escapes_text():
    row = {"label": "1", "area (mm^2)": "nan", "max_feret (mm)": "0.5", "pore_size_class": "<b>&</b>"}

    summary = segment_summary(1, row)

    assert "area" not in summary
    assert "&lt;b&gt;&amp;&lt;/b&gt;" in summary


def test_label_at_maps_ras_points_to_voxels():
    array = np.zeros((4, 5, 6), dtype=np.int32)  # (k, j, i)
    array[2, 3, 4] = 9
    ijk_to_ras = np.diag((0.5, 2.0, 3.0, 1.0))
    ijk_to_ras[:3, 3] = (10, 20, 30)
    ras_to_ijk = np.linalg.inv(ijk_to_ras)

    center = (ijk_to_ras @ (4, 3, 2, 1))[:3]
    assert label_at(array, ras_to_ijk, center) == 9
    assert label_at(array, ras_to_ijk, center + (0.2, 0.9, 1.4)) == 9  # still inside that voxel
    assert label_at(array, ras_to_ijk, center + (0.3, 0, 0)) == 0  # the next voxel
    assert label_at(array, ras_to_ijk, (0, 0, 0)) == 0  # outside the labelmap


def test_label_rows_maps_each_label_to_its_first_row():
    assert label_rows([3, 1, 2, 1]) == {3: 0, 1: 1, 2: 2}
    assert label_rows(["5", "label", "6.0"]) == {5: 0, 6: 2}
    assert label_rows(np.array([10, 20], dtype=np.int32)) == {10: 0, 20: 1}
