import numpy as np
import pytest

import ImageQualityMetrics.ImageQualityMetrics as module
from commons.lmath.image_quality_api import CnrOptions, QualityOptions
from commons.slicer import image_quality as adapter


class FakeSegment:
    def __init__(self, name):
        self._name = name

    def GetName(self):
        return self._name


class FakeSegmentation:
    def __init__(self, names):
        self._names = names

    def GetSegment(self, segmentId):
        return FakeSegment(self._names[segmentId])


class FakeSegmentationNode:
    def __init__(self, names):
        self._segmentation = FakeSegmentation(names)

    def GetSegmentation(self):
        return self._segmentation


class FakeVolumeNode:
    def __init__(self, array):
        self.array = array

    def GetSpacing(self):
        return (0.01, 0.02, 0.03)  # (x, y, z)

    def GetName(self):
        return "scan"


def test_measure_nodes_reads_the_nodes(monkeypatch):
    rng = np.random.default_rng(0)
    volume = rng.normal(100, 5, (4, 16, 16)).astype(np.float32)
    inner = np.zeros(volume.shape, bool)
    inner[:, 4:12, 4:12] = True
    volume[inner] += 200
    masks = {"in": inner, "out": ~inner}
    seen = {}

    def array_from_segment(segmentationNode, segmentId, volumeNode):
        seen["volumeNode"] = volumeNode
        return masks[segmentId]

    monkeypatch.setattr(adapter.slicer.util, "arrayFromVolume", lambda node: node.array)
    monkeypatch.setattr(adapter, "arrayFromSegmentBinaryLabelmap", array_from_segment)

    node = FakeVolumeNode(volume)
    options = QualityOptions(snr=["in"], cnr=CnrOptions("in", "out"))
    result = module.ImageQualityMetricsLogic().measure(
        node, FakeSegmentationNode({"in": "Inside", "out": "Outside"}), options, {"kV": "60"}
    )

    assert seen["volumeNode"] is node
    assert result.metrics["Volume"] == "scan" and result.metrics["kV"] == "60"
    assert result.metrics["CNR phases"] == "Inside vs Outside"
    assert "SNR [Inside]" in result.metrics
    assert result.metrics["Voxel size (um)"] == pytest.approx(20.0)  # mean of 0.03, 0.02, 0.01 mm


def test_every_metric_has_a_help_text_that_renders_as_markdown():
    import markdown

    assert set(module.HELP_TEXTS) == {"SNR", "CNR", "Cupping", "MTF"}
    for key, text in module.HELP_TEXTS.items():
        html = markdown.markdown(text)
        assert "<strong>" in html and "<li>" in html, key
        assert "```" not in html and "**" not in html, key  # nothing left unrendered
