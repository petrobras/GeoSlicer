"""Folder scanning decides what becomes a node, what becomes a frame, and what is left alone."""

import numpy as np
import pytest
import tifffile

from commons.slicer.virtual.folder import (
    ITEM_STACK,
    ITEM_TABLE,
    ITEM_VOLUME,
    frame_sort_key,
    scan,
    suggest_patterns,
)


def write_stack(folder, planes=2, value=1):
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(planes):
        tifffile.imwrite((folder / f"slice_{index}.tif").as_posix(), np.full((4, 4), value, dtype=np.uint16))


@pytest.fixture
def tree(tmp_path):
    write_stack(tmp_path / "recon_0")
    write_stack(tmp_path / "recon_1")
    (tmp_path / "timelog.csv").write_text("sw krw\n0.9 0.1\n")
    (tmp_path / "settings.txt").write_text("not a table, just notes\n")
    (tmp_path / "notes.docx").write_bytes(b"binary")
    for step in (10000, 20000, 100000):
        (tmp_path / f"vis{step}").mkdir()
        (tmp_path / f"vis{step}" / "summary.xmf").write_text("frame")
    return tmp_path


def test_frames_are_ordered_by_number_not_alphabetically():
    names = ["vis100000", "vis20000", "vis9000", "vis1000000"]
    assert sorted(names, key=frame_sort_key) == ["vis9000", "vis20000", "vis100000", "vis1000000"]


def test_names_without_a_number_sort_after_the_numbered_ones():
    assert sorted(["vis10", "readme", "vis2"], key=frame_sort_key) == ["vis2", "vis10", "readme"]


def test_scan_groups_planes_into_one_volume_per_folder(tree):
    result = scan(tree)
    kinds = {item.key: item.kind for item in result.items}

    assert kinds["recon_0"] == ITEM_STACK
    assert kinds["recon_1"] == ITEM_STACK
    assert kinds["timelog.csv"] == ITEM_TABLE
    # A settings ".txt" is not a table, and an unknown format is reported as skipped rather than guessed.
    assert "settings.txt" not in kinds
    assert {path.name for path in result.skipped} >= {"settings.txt", "notes.docx"}


def test_pattern_turns_matching_entries_into_frames(tree):
    result = scan(tree, pattern=r"vis\d+")

    assert [path.name for path in result.frames] == ["vis10000", "vis20000", "vis100000"]
    assert all(not item.key.startswith("vis") for item in result.items)


def test_scan_is_bounded(tmp_path):
    for index in range(30):
        (tmp_path / f"volume_{index}.raw").write_bytes(bytes(8))

    result = scan(tmp_path, max_items=10)
    assert len(result.items) == 10
    assert result.truncated == 20


def test_suggestions_rank_the_biggest_family_first(tree):
    suggestions = suggest_patterns(tree)
    patterns = [pattern for pattern, _count, _examples in suggestions]

    assert patterns[0] == r"vis\d+"
    assert any(pattern == r"recon_\d+" for pattern in patterns)

    _pattern, count, examples = suggestions[0]
    assert count == 3
    assert examples == ["vis10000", "vis20000", "vis100000"]


def test_volume_files_are_listed_as_items(tmp_path):
    (tmp_path / "image_0001_0002_0003_01000nm.raw").write_bytes(bytes(6))
    result = scan(tmp_path)
    assert [item.kind for item in result.items] == [ITEM_VOLUME]
