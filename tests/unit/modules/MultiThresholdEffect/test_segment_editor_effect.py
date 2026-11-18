import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import numpy as np
import pytest


MODULE_NAME = "MultiThresholdEffect.MultiThresholdEffectLib.SegmentEditorEffect"


@pytest.fixture
def effect(monkeypatch):
    effects_module = ModuleType("SegmentEditorEffects")
    effects_module.__all__ = ["AbstractScriptedSegmentEditorEffect"]
    effects_module.AbstractScriptedSegmentEditorEffect = type("AbstractScriptedSegmentEditorEffect", (), {})
    effects_module.__path__ = []
    threshold_effect_module = ModuleType("SegmentEditorEffects.SegmentEditorThresholdEffect")
    threshold_effect_module.PreviewPipeline = object
    monkeypatch.setitem(sys.modules, "SegmentEditorEffects", effects_module)
    monkeypatch.setitem(sys.modules, "SegmentEditorEffects.SegmentEditorThresholdEffect", threshold_effect_module)

    monkeypatch.setitem(sys.modules, MODULE_NAME, None)
    del sys.modules[MODULE_NAME]
    module = importlib.import_module(MODULE_NAME)

    monkeypatch.setattr(module, "getVolumeNullValue", lambda node: None)
    instance = module.SegmentEditorEffect.__new__(module.SegmentEditorEffect)
    instance.table = MagicMock()
    instance.scriptedEffect = MagicMock()
    instance.drawTable = MagicMock()
    return module, instance


@pytest.fixture
def source_volume(effect, monkeypatch):
    """Wires the effect to a source volume whose voxel array can be set by the test."""
    module, instance = effect
    instance.scriptedEffect.parameterSetNode.return_value.GetSourceVolumeNode.return_value = object()

    def setArray(array):
        monkeypatch.setattr(module.slicer.util, "arrayFromVolume", MagicMock(return_value=array))

    return setArray


@pytest.mark.parametrize("percent", [0, 100])
def test_on_proportion_edited_rejects_out_of_range_values(effect, caplog, percent):
    _, instance = effect

    instance.onProportionEdited(0, percent)

    assert "Segment proportion must be between 0 and 100." in caplog.text
    instance.table.item.assert_not_called()
    instance.drawTable.assert_called_once()


def test_on_proportion_edited_requires_a_source_volume(effect, caplog):
    _, instance = effect
    instance.scriptedEffect.parameterSetNode.return_value.GetSourceVolumeNode.return_value = None

    instance.onProportionEdited(0, 15)

    assert "Source volume node is not available." in caplog.text
    instance.table.item.assert_not_called()


@pytest.mark.parametrize(
    "array, expected",
    [
        (np.arange(100), 34),
        (np.arange(100, dtype=np.float64) + 0.5, 34.5),
        (np.arange(100, dtype=np.int16) - 50, -16),
    ],
)
def test_on_proportion_edited_moves_segment_max(effect, source_volume, array, expected):
    module, instance = effect
    source_volume(array)
    # Segment 1 starts at the 20th voxel; its max must leave it holding 15% of the voxels.
    instance.ranges = [[array[0], array[10]], [array[20], array[50]], [array[50], array[99]]]
    target_cell = MagicMock()
    instance.table.item.return_value = target_cell

    instance.onProportionEdited(1, 15)

    instance.table.item.assert_called_once_with(1, 1)
    target_cell.setData.assert_called_once_with(module.ps.QtCore.Qt.ItemDataRole.EditRole, expected)


def test_on_proportion_edited_moves_max_for_single_segment(effect, source_volume):
    module, instance = effect
    source_volume(np.arange(100))
    instance.ranges = [[10, 99]]
    target_cell = MagicMock()
    instance.table.item.return_value = target_cell

    instance.onProportionEdited(0, 15)

    instance.table.item.assert_called_once_with(0, 1)
    target_cell.setData.assert_called_once_with(module.ps.QtCore.Qt.ItemDataRole.EditRole, 24)


def test_on_proportion_edited_moves_min_of_last_segment(effect, source_volume):
    module, instance = effect
    source_volume(np.arange(100))
    instance.ranges = [[0, 50], [50, 99]]
    target_cell = MagicMock()
    instance.table.item.return_value = target_cell

    instance.onProportionEdited(1, 15)

    instance.table.item.assert_called_once_with(1, 0)
    target_cell.setData.assert_called_once_with(module.ps.QtCore.Qt.ItemDataRole.EditRole, 85)


def test_on_proportion_edited_ignores_null_voxels(effect, source_volume, monkeypatch):
    module, instance = effect
    source_volume(np.array([-1] * 5 + list(range(100))))
    monkeypatch.setattr(module, "getVolumeNullValue", lambda node: -1)
    instance.ranges = [[0, 50], [50, 99]]
    target_cell = MagicMock()
    instance.table.item.return_value = target_cell

    instance.onProportionEdited(0, 15)

    target_cell.setData.assert_called_once_with(module.ps.QtCore.Qt.ItemDataRole.EditRole, 14)


def test_on_proportion_edited_ignores_nan_voxels(effect, source_volume):
    module, instance = effect
    source_volume(np.array([np.nan] * 50 + list(np.arange(100, dtype=np.float32))))
    instance.ranges = [[0, 50], [50, 99]]
    target_cell = MagicMock()
    instance.table.item.return_value = target_cell

    instance.onProportionEdited(0, 90)

    target_cell.setData.assert_called_once_with(module.ps.QtCore.Qt.ItemDataRole.EditRole, 89.0)


def test_on_proportion_edited_warns_when_every_voxel_is_null(effect, source_volume, monkeypatch, caplog):
    module, instance = effect
    source_volume(np.full(10, -1))
    monkeypatch.setattr(module, "getVolumeNullValue", lambda node: -1)
    instance.ranges = [[0, 50], [50, 99]]

    instance.onProportionEdited(0, 15)

    assert "no valid (non-null) voxels" in caplog.text
    instance.table.item.assert_not_called()


def test_estimate_proportions_uses_sampled_voxels(effect):
    _, instance = effect
    instance.svalues = np.arange(100)
    instance.ranges = [[0, 20], [20, 50], [50, 99]]

    assert instance.estimateProportions() == [20.0, 30.0, 50.0]


def test_estimate_proportions_is_empty_without_samples(effect):
    _, instance = effect
    instance.ranges = [[0, 1]]

    assert instance.estimateProportions() == []


def test_apply_kmeans_clears_histogram_when_no_segments_remain(effect):
    _, instance = effect
    instance.svalues = np.arange(100)
    instance.ranges = [[0, 50], [50, 99]]
    segmentation = MagicMock()
    segmentation.GetNumberOfSegments.return_value = 0
    segmentation_node = MagicMock()
    segmentation_node.GetSegmentation.return_value = segmentation
    instance.scriptedEffect.parameterSetNode.return_value.GetSegmentationNode.return_value = segmentation_node
    instance.redrawHistogram = MagicMock()

    instance.applyKmeans()

    assert instance.ranges == []
    instance.redrawHistogram.assert_called_once_with()


@pytest.mark.parametrize(
    "fixed_limit, is_max_limit, expected",
    [
        (0, True, 14),  # first segment: same as a plain percentile
        (20, True, 34),  # voxels below the segment's min are not counted against the proportion
        (50, False, 36),  # segment [36, 50] holds 15 voxels
        (5, False, 0),  # not enough voxels below the max: clamps to the volume min
        (95, True, 99),  # not enough voxels above the min: clamps to the volume max
    ],
)
def test_threshold_for_segment_proportion(effect, fixed_limit, is_max_limit, expected):
    module, _ = effect

    result = module.SegmentEditorEffect.thresholdForSegmentProportion(np.arange(100), 0.15, fixed_limit, is_max_limit)

    assert result == expected
