"""Source backends: geometry sniffing, sampling arithmetic and partial reads."""

import numpy as np
import pytest

from commons.slicer.virtual.sources.base import sample_factor, sampled_shape, window_slices
from commons.slicer.virtual.sources.factory import open_source, source_class_for
from commons.slicer.virtual.sources.images import ImageStackSource, is_image_candidate
from commons.slicer.virtual.sources.metadata import raw_geometry_from_name, spacing_from_name
from commons.slicer.virtual.sources.raw import RawSource
from commons.slicer.virtual.sources.tables import TableSource, sniff_separator


def test_raw_geometry_is_read_from_the_filename_convention():
    geometry = raw_geometry_from_name("PUC_EORS200_LIMPA_P_BIN_0001_2119_5280_01000nm.raw")
    shape, dtype, is_labelmap, spacing = geometry

    assert shape == (5280, 2119, 1)  # ZYX, from the X_Y_Z in the name
    assert dtype == "uint8"
    assert is_labelmap is True
    assert spacing == pytest.approx(0.001)  # 1000 nm in millimeters


def test_spacing_only_convention():
    assert spacing_from_name("SEP9D_520700_SAT_AL_38400nm_small.nc") == pytest.approx(0.0384)
    assert spacing_from_name("no_convention_here.tif") is None


def test_sampling_factor_targets_the_in_plane_size():
    # A thin slab: driven by the largest in-plane axis, not by the long Z extent.
    assert sample_factor((5280, 2119, 1), target=192) == 12
    assert sampled_shape((5280, 2119, 1), 12) == (440, 177, 1)

    # A cube: the voxel budget raises the factor beyond what the in-plane target alone would give.
    assert sample_factor((1000, 1000, 1000), target=192, max_voxels=8_000_000) == 6
    assert sample_factor((100, 100, 100), target=192) == 1


def test_window_slices_are_clamped():
    assert window_slices((10, 10, 10), (2, 2, 2), (99, 4, 4), 2) == (
        slice(2, 10, 2),
        slice(2, 6, 2),
        slice(2, 6, 2),
    )


def test_raw_source_reads_a_strided_window(tmp_path):
    array = np.arange(4 * 5 * 6, dtype=np.uint8).reshape(4, 5, 6)
    path = tmp_path / "volume.raw"
    array.tofile(path)

    source = RawSource(path, shape_zyx=(4, 5, 6), dtype="uint8")
    info = source.describe()
    assert info.shape_zyx == (4, 5, 6)
    assert info.node_class == "vtkMRMLScalarVolumeNode"

    window = source.read_window(factor=2)
    assert window.shape == (2, 3, 3)
    np.testing.assert_array_equal(window, array[::2, ::2, ::2])


def test_raw_source_refuses_an_inconsistent_geometry(tmp_path):
    path = tmp_path / "volume.raw"
    path.write_bytes(bytes(10))

    with pytest.raises(Exception) as error:
        RawSource(path, shape_zyx=(4, 5, 6), dtype="uint8").describe()
    assert "bytes" in str(error.value)


def test_table_source_sniffs_whitespace_separated_logs(tmp_path):
    path = tmp_path / "timelog.csv"
    path.write_text("sw krw krn\n0.99 0.12 0.005\n0.89 0.10 0.014\n")

    assert sniff_separator(path) == r"\s+"

    source = TableSource(path)
    info = source.describe()
    assert info.columns == ("sw", "krw", "krn")
    assert info.rows == 2

    sample = source.read_rows(limit=1)
    assert len(sample) == 1
    assert sample["krw"].iloc[0] == pytest.approx(0.12)


def test_image_stack_skips_the_junk_next_to_real_planes(tmp_path):
    import tifffile

    for index in (55, 56, 60):  # sparse numbering, as reconstructions produce
        tifffile.imwrite((tmp_path / f"scan_{index:06d}.tif").as_posix(), np.full((8, 12), index, dtype=np.uint16))

    (tmp_path / "Thumbs.db").write_bytes(b"junk")
    (tmp_path / "scan_000057.tif.old").write_bytes(b"junk")
    (tmp_path / ".hidden.tif").write_bytes(b"junk")

    assert not is_image_candidate(tmp_path / "Thumbs.db")
    assert not is_image_candidate(tmp_path / "scan_000057.tif.old")

    source = ImageStackSource(tmp_path)
    info = source.describe()
    assert info.shape_zyx == (3, 8, 12)

    planes = source.read_window(factor=1)
    assert [int(plane[0, 0]) for plane in planes] == [55, 56, 60]


def test_factory_picks_a_backend_by_content(tmp_path):
    table = tmp_path / "log.csv"
    table.write_text("a b\n1 2\n")
    assert source_class_for(table) is TableSource

    with open_source(table) as source:
        assert source.describe().kind == "table"
