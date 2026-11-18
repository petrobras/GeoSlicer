"""Locating a report's segment in its labelmap, and framing it in the slice and 3D views."""

from unittest.mock import MagicMock

import numpy as np
import pytest
from scipy import ndimage
from scipy.spatial.transform import Rotation

from commons.slicer import segment_report_navigator as navigator
from commons.slicer.segment_report_navigator import (
    FRAME_MARGIN,
    LABELMAP_REPORT_ROLE,
    REPORT_LABELMAP_ROLE,
    SegmentLocator,
    camera_frame,
    index_to_ras,
    label_bounding_boxes,
    labelMapReport,
    linkReportToLabelMap,
    locate_label,
    reportLabelMap,
    slice_view_frame,
)


def nearest_voxel_brute_force(array, label, spacing):
    voxels = np.argwhere(array == label)
    centroid = voxels.mean(axis=0)
    distances = (((voxels - centroid) * spacing) ** 2).sum(axis=1)
    return voxels[distances == distances.min()], centroid


@pytest.fixture
def labelmap():
    """A ball, a ring around a ball of another label, and a C shape."""
    k, j, i = np.mgrid[0:30, 0:40, 0:50]
    array = np.zeros((30, 40, 50), dtype=np.int32)
    array[(k - 6) ** 2 + (j - 8) ** 2 + (i - 9) ** 2 <= 16] = 1
    radius = np.sqrt((j - 25) ** 2 + (i - 25) ** 2)
    array[(np.abs(k - 15) <= 2) & (radius >= 7) & (radius <= 10)] = 2
    array[(np.abs(k - 15) <= 2) & (radius <= 3)] = 3
    c_shape = (radius >= 5) & (radius <= 8) & (i >= 25)
    array[(k >= 22) & (k <= 27) & c_shape] = 4
    return array


@pytest.mark.parametrize("dtype", [np.int32, np.uint32, np.int16, np.float32])
def test_bounding_boxes_are_indexed_by_label(labelmap, dtype):
    boxes = label_bounding_boxes(labelmap.astype(dtype))

    assert len(boxes) == 4
    for label, box in enumerate(boxes, start=1):
        voxels = np.argwhere(labelmap == label)
        assert [(s.start, s.stop) for s in box] == list(zip(voxels.min(axis=0), voxels.max(axis=0) + 1))


@pytest.mark.parametrize("spacing", [(1.0, 1.0, 1.0), (2.5, 0.4, 0.7)])
@pytest.mark.parametrize("label", [1, 2, 3, 4])
def test_the_located_voxel_belongs_to_the_label_and_is_the_nearest_to_its_centroid(labelmap, label, spacing):
    box = label_bounding_boxes(labelmap)[label - 1]

    inside, _ = locate_label(labelmap, box, label, spacing)

    assert labelmap[tuple(inside)] == label
    nearest, centroid = nearest_voxel_brute_force(labelmap, label, np.array(spacing))
    if labelmap[tuple(np.rint(centroid).astype(int))] == label:
        np.testing.assert_array_equal(inside, np.rint(centroid))
    else:
        assert any((inside == voxel).all() for voxel in nearest)


def test_ring_centroid_falls_outside_the_ring(labelmap):
    """The case that needs the nearest-voxel search: the ring's centroid is in its hole, on label 3."""
    _, centroid = nearest_voxel_brute_force(labelmap, 2, np.ones(3))
    assert labelmap[tuple(np.rint(centroid).astype(int))] == 3


def test_corners_are_the_bounding_box_voxel_edges(labelmap):
    box = label_bounding_boxes(labelmap)[0]

    _, corners = locate_label(labelmap, box, 1, (1, 1, 1))

    voxels = np.argwhere(labelmap == 1)
    assert corners.shape == (8, 3)
    np.testing.assert_array_equal(corners.min(axis=0), voxels.min(axis=0) - 0.5)
    np.testing.assert_array_equal(corners.max(axis=0), voxels.max(axis=0) + 0.5)


def test_locate_works_on_single_slice_images():
    image = np.zeros((1, 20, 30), dtype=np.int32)
    rows, columns = np.mgrid[0:20, 0:30]
    image[0][(rows - 10) ** 2 + (columns - 15) ** 2 <= 25] = 1

    inside, corners = locate_label(image, label_bounding_boxes(image)[0], 1, (1.0, 0.5, 0.5))

    np.testing.assert_array_equal(inside, (0, 10, 15))
    np.testing.assert_array_equal(np.unique(corners[:, 0]), (-0.5, 0.5))


def test_index_to_ras_matches_the_ijk_to_ras_matrix():
    matrix = np.eye(4)
    matrix[:3, :3] = Rotation.from_euler("xyz", (10, 20, 30), degrees=True).as_matrix() @ np.diag((0.5, 0.6, 2.0))
    matrix[:3, 3] = (1, -2, 3)
    kji = np.array([[3, 2, 1], [0, 0, 0], [7.5, -0.5, 4]])

    ras = index_to_ras(kji, matrix)

    expected = [(matrix @ np.r_[point[::-1], 1])[:3] for point in kji]
    np.testing.assert_allclose(ras, expected)


def box_corners(low, high):
    return np.array([(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])])


@pytest.mark.parametrize("rotation", [(0, 0, 0), (35, -20, 60)])
@pytest.mark.parametrize("view_size", [(800, 600), (300, 900)])
def test_slice_view_contains_the_inside_point_and_fits_the_box(rotation, view_size):
    slice_to_ras = np.eye(4)
    slice_to_ras[:3, :3] = Rotation.from_euler("xyz", rotation, degrees=True).as_matrix()
    slice_to_ras[:3, 3] = (100, -50, 20)
    corners = box_corners((10, 20, 30), (14, 30, 33))
    inside = np.array((11.0, 21.0, 32.0))

    center, (fov_x, fov_y) = slice_view_frame(inside, corners, slice_to_ras, view_size)

    normal = slice_to_ras[:3, 2]
    assert np.dot(center - inside, normal) == pytest.approx(0), "the slice plane goes through the inside point"
    assert fov_x / fov_y == pytest.approx(view_size[0] / view_size[1])

    in_plane = (corners - center) @ slice_to_ras[:3, :2]
    assert np.all(np.abs(in_plane[:, 0]) <= fov_x / 2 / FRAME_MARGIN + 1e-9)
    assert np.all(np.abs(in_plane[:, 1]) <= fov_y / 2 / FRAME_MARGIN + 1e-9)
    # Tight: the box touches the margin along one of the axes
    assert max(np.abs(in_plane[:, 0]).max() / fov_x, np.abs(in_plane[:, 1]).max() / fov_y) == pytest.approx(
        1 / 2 / FRAME_MARGIN
    )


def test_slice_view_frames_tiny_segments_with_some_context():
    corners = box_corners((0, 0, 0), (0.1, 0.1, 0.1))

    _, (fov_x, fov_y) = slice_view_frame(np.zeros(3), corners, np.eye(4), (100, 100), min_extent=5)

    assert (fov_x, fov_y) == pytest.approx((5 * FRAME_MARGIN, 5 * FRAME_MARGIN))


@pytest.mark.parametrize("view_angle", [30, 60])
def test_camera_keeps_its_direction_and_sees_the_whole_box(view_angle):
    corners = box_corners((10, 20, 30), (16, 40, 33))
    position = np.array((500.0, 300.0, -200.0))
    focal_point = np.array((0.0, 10.0, 5.0))

    new_focal_point, new_position, parallel_scale = camera_frame(corners, position, focal_point, view_angle)

    np.testing.assert_allclose(new_focal_point, (13, 30, 31.5))
    old_direction = (position - focal_point) / np.linalg.norm(position - focal_point)
    new_direction = (new_position - new_focal_point) / np.linalg.norm(new_position - new_focal_point)
    np.testing.assert_allclose(new_direction, old_direction)

    view_axis = -new_direction
    to_corners = corners - new_position
    angles = np.degrees(np.arccos(to_corners @ view_axis / np.linalg.norm(to_corners, axis=1)))
    assert np.all(angles <= view_angle / 2)
    assert parallel_scale >= np.abs((corners - new_focal_point) @ np.cross(view_axis, (0, 0, 1))).max()


def make_node(node_id, class_name="vtkMRMLTableNode", attributes=None, references=None):
    """Mock MRML node with attributes and node references ({role: node ID}) that can be set later on."""
    node = MagicMock()
    node.attributes = dict(attributes or {})
    node.references = dict(references or {})
    node.GetID.return_value = node_id
    node.IsA.side_effect = lambda name: name == class_name
    node.GetAttribute.side_effect = node.attributes.get
    node.SetAttribute.side_effect = node.attributes.__setitem__
    node.GetNodeReferenceID.side_effect = node.references.get
    node.SetNodeReferenceID.side_effect = node.references.__setitem__
    return node


@pytest.fixture
def scene(monkeypatch):
    nodes = {}
    monkeypatch.setattr(navigator.slicer.mrmlScene, "GetNodeByID", lambda node_id: nodes.get(node_id))
    return nodes


def make_report(
    scene,
    report_attributes,
    labelmap_attributes,
    labelmap_class="vtkMRMLLabelMapVolumeNode",
    report_references=None,
    labelmap_references=None,
):
    report = make_node("vtkMRMLTableNode1", attributes=report_attributes, references=report_references)
    report.GetColumnIndex.side_effect = lambda name: 0 if name == "label" else -1
    scene["vtkMRMLTableNode1"] = report
    scene["vtkMRMLLabelMapVolumeNode1"] = make_node(
        "vtkMRMLLabelMapVolumeNode1", labelmap_class, labelmap_attributes, labelmap_references
    )
    return report


def test_a_report_leads_to_the_labelmap_that_points_back_to_it(scene):
    report = make_report(
        scene, {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode1"}, {"ResultReport": "vtkMRMLTableNode1"}
    )
    assert reportLabelMap(report) is scene["vtkMRMLLabelMapVolumeNode1"]


def test_a_report_whose_labelmap_has_no_back_reference_is_accepted(scene):
    report = make_report(scene, {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode1"}, {})
    assert reportLabelMap(report) is scene["vtkMRMLLabelMapVolumeNode1"]


@pytest.mark.parametrize(
    "report_attributes, labelmap_attributes, labelmap_class",
    [
        ({}, {}, "vtkMRMLLabelMapVolumeNode"),  # an unrelated table
        ({"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode1"}, {}, "vtkMRMLScalarVolumeNode"),  # mineralogy
        (
            {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode1"},
            {"ResultReport": "vtkMRMLTableNode2"},  # the labelmap has a newer report
            "vtkMRMLLabelMapVolumeNode",
        ),
    ],
)
def test_other_tables_are_ignored(scene, report_attributes, labelmap_attributes, labelmap_class):
    report = make_report(scene, report_attributes, labelmap_attributes, labelmap_class)
    assert reportLabelMap(report) is None


def test_node_references_link_report_and_labelmap(scene):
    report = make_report(
        scene,
        {},
        {},
        report_references={REPORT_LABELMAP_ROLE: "vtkMRMLLabelMapVolumeNode1"},
        labelmap_references={LABELMAP_REPORT_ROLE: "vtkMRMLTableNode1"},
    )
    labelmap = scene["vtkMRMLLabelMapVolumeNode1"]

    assert reportLabelMap(report) is labelmap
    assert labelMapReport(labelmap) is report


def test_node_references_win_over_stale_attributes(scene):
    """After an import that renamed node IDs, Slicer updated the references but not the attributes."""
    report = make_report(
        scene,
        {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode7"},
        {"ResultReport": "vtkMRMLTableNode7"},
        report_references={REPORT_LABELMAP_ROLE: "vtkMRMLLabelMapVolumeNode1"},
        labelmap_references={LABELMAP_REPORT_ROLE: "vtkMRMLTableNode1"},
    )
    scene["vtkMRMLLabelMapVolumeNode7"] = make_node("vtkMRMLLabelMapVolumeNode7", "vtkMRMLLabelMapVolumeNode")
    labelmap = scene["vtkMRMLLabelMapVolumeNode1"]

    assert reportLabelMap(report) is labelmap
    assert labelMapReport(labelmap) is report


def test_a_labelmap_referencing_a_newer_report_ignores_older_ones(scene):
    report = make_report(
        scene,
        {},
        {"ResultReport": "vtkMRMLTableNode1"},  # stale attribute
        report_references={REPORT_LABELMAP_ROLE: "vtkMRMLLabelMapVolumeNode1"},
        labelmap_references={LABELMAP_REPORT_ROLE: "vtkMRMLTableNode2"},
    )
    assert reportLabelMap(report) is None


def test_link_report_to_labelmap_writes_references_and_attributes():
    report = make_node("vtkMRMLTableNode3")
    labelmap = make_node("vtkMRMLLabelMapVolumeNode4", "vtkMRMLLabelMapVolumeNode")

    linkReportToLabelMap(report, labelmap)

    assert report.references == {REPORT_LABELMAP_ROLE: "vtkMRMLLabelMapVolumeNode4"}
    assert report.attributes == {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode4"}
    assert labelmap.references == {LABELMAP_REPORT_ROLE: "vtkMRMLTableNode3"}
    assert labelmap.attributes == {"ResultReport": "vtkMRMLTableNode3"}


def test_link_report_to_labelmap_can_skip_the_back_link():
    report = make_node("vtkMRMLTableNode3")
    labelmap = make_node("vtkMRMLLabelMapVolumeNode4", "vtkMRMLLabelMapVolumeNode")

    linkReportToLabelMap(report, labelmap, backLink=False)

    assert report.references == {REPORT_LABELMAP_ROLE: "vtkMRMLLabelMapVolumeNode4"}
    assert labelmap.references == {} and labelmap.attributes == {}


def test_tables_without_label_column_are_ignored(scene):
    report = make_report(scene, {"ReferenceVolumeNode": "vtkMRMLLabelMapVolumeNode1"}, {})
    report.GetColumnIndex.side_effect = lambda name: -1
    assert reportLabelMap(report) is None


def test_locator_reuses_bounding_boxes_until_the_image_changes(monkeypatch, labelmap):
    node = make_node("vtkMRMLLabelMapVolumeNode1", "vtkMRMLLabelMapVolumeNode")
    node.GetSpacing.return_value = (1.0, 1.0, 1.0)
    node.GetImageData.return_value.GetMTime.return_value = 100
    monkeypatch.setattr(navigator.slicer.util, "arrayFromVolume", lambda n: labelmap)
    scans = []
    monkeypatch.setattr(navigator, "label_bounding_boxes", lambda array: scans.append(1) or ndimage.find_objects(array))
    locator = SegmentLocator()

    assert labelmap[tuple(locator.locate(node, 2)[0])] == 2
    assert labelmap[tuple(locator.locate(node, 4)[0])] == 4
    assert len(scans) == 1

    labelmap[labelmap == 4] = 0
    node.GetImageData.return_value.GetMTime.return_value = 101

    assert locator.locate(node, 4) is None
    assert len(scans) == 2


@pytest.mark.parametrize("label", [0, -1, 99])
def test_locator_returns_none_for_absent_labels(monkeypatch, labelmap, label):
    node = make_node("vtkMRMLLabelMapVolumeNode1", "vtkMRMLLabelMapVolumeNode")
    monkeypatch.setattr(navigator.slicer.util, "arrayFromVolume", lambda n: labelmap)
    assert SegmentLocator().locate(node, label) is None
