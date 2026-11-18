"""The case geometry sidecar: what carries an image's placement into a simulation's results."""

import json

import pytest

from commons.lbpm.geometry import GEOMETRY_NAME, CaseGeometry


class FakeImageData:
    def __init__(self, dimensions):
        self.dimensions = dimensions

    def GetDimensions(self):
        return self.dimensions


class FakeVolumeNode:
    def __init__(self, origin, spacing, dimensions, name="rock"):
        self._origin, self._spacing, self._dimensions, self._name = origin, spacing, dimensions, name

    def GetOrigin(self):
        return self._origin

    def GetSpacing(self):
        return self._spacing

    def GetImageData(self):
        return FakeImageData(self._dimensions)

    def GetName(self):
        return self._name


def test_placement_is_read_from_a_volume_node_in_the_source_convention():
    # A centred (5280, 2119, 1) image of 1 um voxels, as Micro CT Import produces it.
    node = FakeVolumeNode(origin=(0.0, 1.059, -2.6395), spacing=(0.001, 0.001, 0.001), dimensions=(1, 2119, 5280))

    geometry = CaseGeometry.from_volume_node(node)

    assert geometry.origin_zyx == pytest.approx((-2.6395, -1.059, 0.0))
    assert geometry.spacing_zyx == pytest.approx((0.001, 0.001, 0.001))
    assert geometry.shape_zyx == (5280, 2119, 1)
    assert geometry.source == "rock"


def test_anisotropic_spacing_survives_even_though_lbpm_cannot_express_it():
    node = FakeVolumeNode(origin=(0.0, 0.0, 0.0), spacing=(0.001, 0.002, 0.004), dimensions=(4, 4, 4))

    assert CaseGeometry.from_volume_node(node).spacing_zyx == pytest.approx((0.004, 0.002, 0.001))


def test_round_trip_through_the_sidecar(tmp_path):
    geometry = CaseGeometry(origin_zyx=(-2.6395, -1.059, 0.0), spacing_zyx=(0.001,) * 3, shape_zyx=(5280, 2119, 1))
    path = geometry.write(tmp_path)

    assert path.name == GEOMETRY_NAME
    assert CaseGeometry.read(tmp_path) == geometry


def test_the_sidecar_is_found_from_a_frame_folder(tmp_path):
    """A frame folder sits two levels below the case: <case>/sim001/vis10000."""
    geometry = CaseGeometry(origin_zyx=(1.0, 2.0, 3.0), spacing_zyx=(0.001,) * 3)
    geometry.write(tmp_path)

    frame = tmp_path / "sim001" / "vis10000"
    frame.mkdir(parents=True)

    assert CaseGeometry.find(frame) == geometry
    assert CaseGeometry.find(frame / "00000.h5") == geometry
    assert CaseGeometry.find(tmp_path / "a" / "b" / "c" / "d") is None


def test_a_placement_for_a_different_image_is_not_applied():
    geometry = CaseGeometry(origin_zyx=(0.0,) * 3, spacing_zyx=(0.001,) * 3, shape_zyx=(100, 100, 100))

    assert geometry.matches((100, 100, 100))
    assert not geometry.matches((200, 100, 100))
    # Nothing recorded about the shape means nothing to contradict.
    assert CaseGeometry(origin_zyx=(0.0,) * 3, spacing_zyx=(0.001,) * 3).matches((7, 8, 9))


def test_an_unreadable_sidecar_is_ignored_rather_than_raising(tmp_path):
    (tmp_path / GEOMETRY_NAME).write_text("{not json")
    assert CaseGeometry.read(tmp_path) is None

    (tmp_path / GEOMETRY_NAME).write_text(json.dumps({"spacing_zyx": [1, 1, 1]}))
    assert CaseGeometry.read(tmp_path) is None
