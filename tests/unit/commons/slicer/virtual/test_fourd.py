"""4D frame indexing, ragged-frame conforming, the preview cache and the full-resolution LRU."""

import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
import tifffile

from commons.slicer.virtual.fourd.cache import (
    STATE_FAILED,
    STATE_FILLED,
    FullResolutionCache,
    PreviewBuilder,
    PreviewCache,
)
from commons.slicer.virtual import attributes as attrs
from commons.slicer.virtual.fourd.dataset import FourDDataset, conform_shape
from commons.slicer.virtual.fourd.manager import FourDManager
from commons.slicer.virtual.sources.base import SourceInfo
from commons.slicer.virtual.uri import fourd_uri


def write_frame(root: Path, index: int, planes: int = 2, value: int = 0, size=(4, 6)):
    folder = root / f"frame_{index:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    for plane in range(planes):
        tifffile.imwrite((folder / f"s{plane}.tif").as_posix(), np.full(size, value + plane, dtype=np.uint16))
    return folder


@pytest.fixture
def sequence(tmp_path):
    for index in range(3):
        write_frame(tmp_path, index, value=index * 10)
    return tmp_path


# -- dataset ------------------------------------------------------------------------------------------
def test_dataset_orders_and_labels_frames(sequence):
    dataset = FourDDataset(sequence, pattern=r"frame_\d+")

    assert dataset.frame_count == 3
    assert dataset.labels() == ["000", "001", "002"]
    assert dataset.describe().shape_zyx == (2, 4, 6)
    assert dataset.uri.startswith("4d://")


def test_dataset_orders_by_number(tmp_path):
    for index in (1, 2, 10, 100):
        write_frame(tmp_path, index)

    dataset = FourDDataset(tmp_path, pattern=r"frame_\d+")
    assert [frame.path.name for frame in dataset.frames] == ["frame_001", "frame_002", "frame_010", "frame_100"]


def test_rescan_reports_appended_frames(sequence):
    dataset = FourDDataset(sequence, pattern=r"frame_\d+")
    assert dataset.rescan() == 0

    write_frame(sequence, 3, value=30)
    assert dataset.rescan() == 1
    assert dataset.frame_count == 4


def test_reading_a_ragged_frame_conforms_it(sequence):
    # A frame with fewer planes than the reference: the read is padded, not refused.
    write_frame(sequence, 3, planes=1, value=99)
    dataset = FourDDataset(sequence, pattern=r"frame_\d+")

    frame = dataset.read_frame(3, factor=1)
    assert frame.shape == (2, 4, 6)
    assert int(frame[0, 0, 0]) == 99
    assert int(frame[1].max()) == 0, "the missing plane must read as empty, not as a repeat"


def test_conform_shape_crops_and_pads():
    array = np.ones((3, 3), dtype=np.uint8)
    assert conform_shape(array, (2, 2)).shape == (2, 2)

    padded = conform_shape(array, (4, 3))
    assert padded.shape == (4, 3)
    assert padded[3].sum() == 0


def test_signature_changes_with_the_frames(sequence):
    dataset = FourDDataset(sequence, pattern=r"frame_\d+")
    before = dataset.signature()

    write_frame(sequence, 5, value=50)
    dataset.rescan()

    assert dataset.signature() != before
    # The identity key does not change: the same folder keeps reusing its cache while it grows.
    assert dataset.stable_key() == FourDDataset(sequence, pattern=r"frame_\d+").stable_key()


# -- preview cache ------------------------------------------------------------------------------------
@dataclass
class FakeFrame:
    path: Path


def _change_on_disk(path: Path) -> None:
    """Write a file with a modification time later than anything stamped so far.

    Filesystem timestamps are coarse, so a plain write can share the tick of a stamp taken just before it
    and go unnoticed.
    """
    path.write_text("x")
    later = time.time_ns() + 10_000_000_000
    os.utime(path, ns=(later, later))


class FakeDataset:
    """Enough of a dataset for the cache: three frames of a known shape, counting reads."""

    def __init__(self, root: Path, frames: int = 3, fail: set = ()):
        self.root = root
        self.variable = "phase"
        self.uri = f"4d://{root.as_posix()}?pattern=f"
        self._frames = frames
        self._fail = set(fail)
        self.reads = []
        for index in range(frames):
            (root / f"f{index}").mkdir(parents=True, exist_ok=True)

    @property
    def frame_count(self):
        return self._frames

    def frame(self, index):
        return FakeFrame(path=self.root / f"f{index}")

    def describe(self):
        return SourceInfo(kind="volume", node_class="vtkMRMLScalarVolumeNode", shape_zyx=(2, 4, 4), dtype="uint16")

    def sampled_shape(self, factor, **kwargs):
        return (2, 4, 4)

    def preview_factor(self, target=None):
        return 1

    def stable_key(self):
        return "fake"


def test_cache_writes_one_file_per_frame_and_reuses_them(tmp_path):
    dataset = FakeDataset(tmp_path / "data", frames=3)
    dataset.read_frame = lambda index, factor=1: (dataset.reads.append(index), np.full((2, 4, 4), index, np.uint16))[1]

    cache = PreviewCache(dataset, root=tmp_path / "cache")
    assert cache.missing() == [0, 1, 2]

    first = cache.get_or_build(1)
    assert int(first[0, 0, 0]) == 1
    assert cache.is_filled(1)
    assert (cache.path / "frame_000001.npy").is_file()

    again = cache.get_or_build(1)
    assert dataset.reads == [1], "a cached frame must not be read from the dataset again"
    np.testing.assert_array_equal(first, again)

    stats = cache.stats()
    assert (stats.filled, stats.failed, stats.total, stats.pending) == (1, 0, 3, 2)


def test_cache_is_reused_across_instances_and_rebuilt_when_the_shape_changes(tmp_path):
    dataset = FakeDataset(tmp_path / "data")
    dataset.read_frame = lambda index, factor=1: np.full((2, 4, 4), 7, np.uint16)

    cache = PreviewCache(dataset, root=tmp_path / "cache")
    cache.get_or_build(0)

    reopened = PreviewCache(dataset, root=tmp_path / "cache")
    assert reopened.is_filled(0), "the same dataset must reuse the store it already filled"

    dataset.sampled_shape = lambda factor, **kwargs: (2, 8, 8)
    rebuilt = PreviewCache(dataset, root=tmp_path / "cache")
    assert not rebuilt.is_filled(0), "a different frame shape invalidates the store"


def test_unreadable_frames_are_marked_and_retried_when_they_change(tmp_path):
    dataset = FakeDataset(tmp_path / "data")

    def read(index, factor=1):
        if index == 2:
            raise OSError("still being written")
        return np.full((2, 4, 4), index, np.uint16)

    dataset.read_frame = read

    cache = PreviewCache(dataset, root=tmp_path / "cache")
    assert cache.build(2) is None
    assert cache.state(2) == STATE_FAILED
    assert cache.missing() == [0, 1], "a failed frame is not retried on every pass"

    messages = cache.drain_messages()
    assert any("could not be read" in message for message in messages)
    assert cache.drain_messages() == []

    # The frame changes on disk: it becomes a candidate again.
    _change_on_disk(dataset.root / "f2" / "new")
    assert cache.refresh_states() == [2]
    assert 2 in cache.missing()


def test_refresh_can_be_limited_to_some_frames(tmp_path):
    dataset = FakeDataset(tmp_path / "data")
    dataset.read_frame = lambda index, factor=1: np.full((2, 4, 4), index, np.uint16)

    cache = PreviewCache(dataset, root=tmp_path / "cache")
    for index in range(3):
        cache.build(index)

    for index in range(3):
        _change_on_disk(dataset.root / f"f{index}" / "touched")

    assert cache.refresh_states(indices=[2]) == [2]
    assert cache.state(0) == STATE_FILLED


def test_builder_fills_the_nearest_frames_first(tmp_path):
    dataset = FakeDataset(tmp_path / "data", frames=6)
    order = []

    def read(index, factor=1):
        order.append(index)
        return np.full((2, 4, 4), index, np.uint16)

    dataset.read_frame = read
    cache = PreviewCache(dataset, root=tmp_path / "cache")

    builder = PreviewBuilder(cache)
    builder.start(priority=4)
    assert builder.wait(timeout=30), "the builder should finish a six-frame sequence"

    assert set(order) == set(range(6))
    assert order[0] == 4, "the frame the user is looking at is filled first"
    assert abs(order[1] - 4) <= 1


# -- full resolution ----------------------------------------------------------------------------------
def test_full_resolution_cache_evicts_the_least_recently_used():
    cache = FullResolutionCache(capacity=2)
    for index in range(3):
        cache.put(index, np.zeros(2))

    assert cache.indices() == [1, 2]

    cache.get(1)
    cache.put(3, np.zeros(2))
    assert cache.indices() == [1, 3], "using a frame protects it from the next eviction"

    cache.capacity = 1
    assert len(cache) == 1


# -- manager ------------------------------------------------------------------------------------------
class _Node:
    def __init__(self, attributes):
        self.attributes = attributes

    def GetAttribute(self, key):
        return self.attributes.get(key)


def _proxy(folder, pattern=r"vis\d+", variable="phase"):
    return _Node({attrs.FOURD_PROXY: attrs.TRUE, attrs.URI: fourd_uri(folder, pattern, variable)})


def test_the_nodes_of_a_folder_are_found_whether_they_have_a_player_or_not(monkeypatch, tmp_path):
    """A node restored with a project has no player until it is shown, and must still be found by folder."""
    import slicer

    run, other = tmp_path / "lbpm" / "uid-1", tmp_path / "lbpm" / "uid-2"
    phase, pressure, elsewhere = _proxy(run), _proxy(run, variable="Pressure"), _proxy(other)
    not_a_proxy = _Node({attrs.URI: fourd_uri(run, r"vis\d+")})
    monkeypatch.setattr(slicer.util, "getNodesByClass", lambda cls: [phase, pressure, elsewhere, not_a_proxy])
    manager = FourDManager.__new__(FourDManager)

    assert manager.nodes(run) == [phase, pressure]
    assert manager.nodes(run, pattern=r"vis\d+", variable="phase") == [phase]
    assert manager.nodes(tmp_path / "lbpm" / "uid-3") == []
