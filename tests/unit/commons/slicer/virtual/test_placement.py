"""Where a deferred node lands in space.

The invariant under test is the one a user checks by eye: a sample, the full-resolution data it was taken
from, and the eagerly loaded copy of that same data all occupy the same physical box.
"""

import pytest

from commons.slicer.virtual.nodes.base import apply_geometry, centered_origin_zyx
from commons.slicer.virtual.sources.base import CLASS_SCALAR_VOLUME, KIND_VOLUME, SourceInfo, sample_factor


class FakeVolumeNode:
    """The three calls ``apply_geometry`` makes, plus the RAS bounds Slicer would derive from them."""

    def __init__(self, dimensions_zyx):
        self.dimensions_zyx = tuple(dimensions_zyx)
        self.spacing = (1.0, 1.0, 1.0)
        self.origin = (0.0, 0.0, 0.0)
        self.directions = None

    def SetSpacing(self, x, y, z):
        self.spacing = (x, y, z)

    def SetOrigin(self, x, y, z):
        self.origin = (x, y, z)

    def SetIJKToRASDirections(self, *values):
        self.directions = values

    def bounds(self):
        """RAS bounds, matching ``vtkMRMLVolumeNode.GetRASBounds`` for the ``(-1, -1, 1)`` directions."""
        box = []
        for axis, (size, direction) in enumerate(zip(reversed(self.dimensions_zyx), (-1, -1, 1))):
            step = self.spacing[axis]
            first = self.origin[axis]
            last = first + direction * (size - 1) * step
            box += [round(min(first, last) - step / 2, 9), round(max(first, last) + step / 2, 9)]
        return box


def info_for(shape_zyx, spacing=0.001, origin_zyx=None):
    return SourceInfo(
        kind=KIND_VOLUME,
        node_class=CLASS_SCALAR_VOLUME,
        shape_zyx=shape_zyx,
        dtype="uint8",
        spacing_zyx=(spacing, spacing, spacing),
        origin_zyx=origin_zyx,
    )


def place(shape_zyx, sampled_zyx, factor, info=None, **options):
    node = FakeVolumeNode(sampled_zyx)
    apply_geometry(node, info or info_for(shape_zyx), factor=factor, sampled_shape_zyx=sampled_zyx, **options)
    return node


def test_a_source_without_an_origin_is_centered_like_an_imported_image():
    """GeoSlicer centres images on import, so data whose file records no origin lands centred too."""
    shape = (5280, 2119, 1)
    node = place(shape, shape, 1)

    assert node.origin == pytest.approx((0.0, 1.059, -2.6395))
    assert node.bounds() == pytest.approx([-0.0005, 0.0005, -1.0595, 1.0595, -2.64, 2.64])
    assert node.directions == (-1, 0, 0, 0, -1, 0, 0, 0, 1)


def test_centered_origin_matches_slicers_centering_transform():
    # AddCenteringTransform makes the voxel *centres* symmetric about the origin.
    assert centered_origin_zyx((5280, 2119, 1), (0.001, 0.001, 0.001)) == pytest.approx((-2.6395, -1.059, 0.0))
    assert centered_origin_zyx((1, 1, 1), (0.5, 0.5, 0.5)) == pytest.approx((0.0, 0.0, 0.0))


def test_a_preview_occupies_exactly_the_same_box_as_the_full_resolution_data():
    """The promise made to the user: loading full resolution changes the detail, not the geometry."""
    shape = (5280, 2119, 1)
    factor = sample_factor(shape, target=192)
    sampled = (440, 177, 1)

    preview = place(shape, sampled, factor)
    full = place(shape, shape, 1)

    assert preview.bounds() == pytest.approx(full.bounds())


def test_an_axis_too_thin_to_decimate_keeps_its_thickness():
    """LBPM's quasi-2D domains are one voxel thick; a factor of 12 must not inflate that to twelve."""
    preview = place((5280, 2119, 1), (440, 177, 1), 12)

    assert preview.spacing[0] == pytest.approx(0.001)  # X, undecimated
    assert preview.spacing[2] == pytest.approx(0.012)  # Z, decimated by 12


def test_an_origin_recorded_by_the_source_is_used_as_it_is():
    """A NetCDF file knows where it sits; nothing may override it."""
    shape = (10, 20, 30)
    info = info_for(shape, spacing=0.1, origin_zyx=(1.0, 2.0, 3.0))

    node = place(shape, shape, 1, info=info)

    assert node.origin == pytest.approx((-3.0, -2.0, 1.0))  # (-x, -y, z), as commons.slicer.netcdf writes it


def test_a_cropped_window_is_placed_at_its_own_offset():
    """A crop covers the box its own voxels cover — whatever stride it was read with."""
    shape = (10, 20, 30)
    info = info_for(shape, spacing=0.1, origin_zyx=(0.0, 0.0, 0.0))
    window = (8, 10, 10)
    offset = (2, 4, 6)

    strided = place(shape, (4, 5, 5), 2, info=info, origin_offset_zyx=offset, window_zyx=window)
    dense = place(shape, window, 1, info=info, origin_offset_zyx=offset, window_zyx=window)

    assert strided.spacing == pytest.approx((0.2, 0.2, 0.2))
    assert strided.bounds() == pytest.approx(dense.bounds())
    # Z: voxels 2..9 of a 0.1 mm grid starting at the origin, so the box runs 0.15 to 0.95.
    assert strided.bounds()[4:] == pytest.approx([0.15, 0.95])
