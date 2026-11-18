"""The LBPM configuration must survive a round trip untouched: users edit these files by hand."""

from pathlib import Path

import pytest

from commons.lbpm.config import WaterflowConfig

SAMPLE = """Domain {
   Filename = "image.raw"
   ReadType = "8bit"              // data type
   N = 1, 2119, 5280              // size of original image
   nproc = 1, 1, 8    // process grid
   voxel_length = 1.0     // voxel length (in microns)
   BC = 4                         // boundary condition type (0 for periodic)
}

Color {
    tauA = 1.1;             // relaxation time for fluid A
    alpha = 2.00000e-03;           // controls the surface tension
    Restart = false          // initialize simulation from restart file?
    ComponentAffinity = -1.0, -0.9  // wetting condition
}
"""


def test_round_trip_is_byte_exact():
    config = WaterflowConfig.from_text(SAMPLE)
    assert config.to_text() == SAMPLE


def test_reads_typed_values():
    config = WaterflowConfig.from_text(SAMPLE)

    assert config.sections() == ["Domain", "Color"]
    assert config.get_string("Domain", "Filename") == "image.raw"
    assert config.domain_shape_zyx() == (5280, 2119, 1)
    assert config.domain_dtype() == "uint8"
    assert config.rank_count() == 8
    assert config.voxel_length_mm() == pytest.approx(0.001)
    assert config.get_float("Color", "alpha") == pytest.approx(0.002)
    assert config.get_bool("Color", "Restart") is False
    assert config.get_float_list("Color", "ComponentAffinity") == [-1.0, -0.9]


def test_editing_rewrites_only_the_value():
    config = WaterflowConfig.from_text(SAMPLE)
    config.set("Color", "alpha", 0.005)
    config.set("Domain", "Filename", "other.raw")

    changed = [
        (before, after) for before, after in zip(SAMPLE.splitlines(), config.to_text().splitlines()) if before != after
    ]

    assert len(changed) == 2
    assert '"other.raw"' in changed[0][1]
    # Alignment padding and the trailing comment are preserved.
    assert changed[1][1] == "    alpha = 0.005;           // controls the surface tension"


def test_new_key_is_added_to_its_section():
    config = WaterflowConfig.from_text(SAMPLE)
    config.set("Color", "beta", 0.95)

    lines = config.to_text().splitlines()
    beta = next(index for index, line in enumerate(lines) if "beta" in line)
    closing = next(index for index, line in enumerate(lines) if line.strip() == "}" and index > beta)

    assert beta < closing, "the new entry must land inside its own section"
    assert config.get_float("Color", "beta") == pytest.approx(0.95)


def test_missing_section_is_created():
    config = WaterflowConfig.from_text(SAMPLE)
    config.set("FlowAdaptor", "endpoint_threshold", 0.001)

    assert "FlowAdaptor {" in config.to_text()
    assert config.get_float("FlowAdaptor", "endpoint_threshold") == pytest.approx(0.001)


def test_defaults_are_runnable_once_an_image_is_set(tmp_path: Path):
    config = WaterflowConfig.default()
    assert config.validate() == ["Domain.Filename is not set: LBPM needs the input image file name."]

    config.set("Domain", "Filename", "image.raw")
    assert config.validate() == []

    written = config.write(tmp_path / "waterflow.db")
    assert WaterflowConfig.from_file(written).to_text() == config.to_text()


def test_validation_reports_an_inconsistent_decomposition():
    config = WaterflowConfig.default()
    config.set("Domain", "Filename", "image.raw")
    config.set("Domain", "N", [10, 10, 10])
    config.set("Domain", "n", [10, 10, 3])
    config.set("Domain", "nproc", [1, 1, 2])

    problems = config.validate()
    assert any("does not cover" in problem for problem in problems)
