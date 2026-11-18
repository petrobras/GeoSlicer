"""4D datasets: a folder whose numbered entries are the frames of a time sequence.

Each frame is read through the ordinary source backends (LBPM per-rank HDF5, TIFF stacks, RAW, NetCDF),
so a 4D dataset inherits their partial-read behaviour: asking for a downsampled frame reads only the
planes and rows needed for it.

Two properties of real output drive the design:

* **frames are numbered, not alphabetical.** LBPM writes ``vis10000``, ``vis100000``, ``vis110000``; sorted
  as text the simulation plays out of order, so ordering is always by the captured integer;
* **frames can be ragged.** A frame still being written, or a reconstruction with a different plane count,
  has a different Z extent. Reads are conformed to the reference frame's shape by cropping and zero-filling,
  and the frame is flagged partial instead of failing the read — a running simulation must stay playable.
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..folder import frame_sort_key
from ..sources.base import SourceError, SourceInfo, VirtualSource, sample_factor
from ..sources.factory import open_source
from ..uri import SCHEME_FOURD, VirtualURI, fourd_uri

TRAILING_DIGITS = re.compile(r"(\d+)(?!.*\d)")


@dataclass(frozen=True)
class Frame:
    index: int
    path: Path
    label: str
    key: str

    @property
    def name(self) -> str:
        return self.path.name


class FourDDataset:
    """The frames of a time sequence, plus the metadata every consumer needs."""

    def __init__(self, root, pattern: str, variable: str = None, source_options: Dict = None):
        self.root = Path(root)
        self.pattern = pattern
        self.variable = variable
        self.source_options = dict(source_options or {})
        self._frames: List[Frame] = []
        self._info: Optional[SourceInfo] = None
        self.rescan()

    # -- construction ---------------------------------------------------------------------------------
    @classmethod
    def from_uri(cls, uri: str) -> "FourDDataset":
        parsed = VirtualURI.parse(uri)
        if parsed.scheme != SCHEME_FOURD:
            raise ValueError(f"Not a 4D URI: {uri}")
        options = {key: value for key, value in parsed.params.items() if key not in ("pattern", "var")}
        return cls(parsed.path, pattern=parsed.pattern, variable=parsed.variable, source_options=options)

    @property
    def uri(self) -> str:
        return fourd_uri(self.root, self.pattern, self.variable)

    # -- frames ---------------------------------------------------------------------------------------
    @property
    def frames(self) -> List[Frame]:
        return list(self._frames)

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def frame(self, index: int) -> Frame:
        if not self._frames:
            raise SourceError(f"No frame matching {self.pattern!r} inside {self.root}")
        return self._frames[max(0, min(index, len(self._frames) - 1))]

    def labels(self) -> List[str]:
        return [frame.label for frame in self._frames]

    def rescan(self) -> int:
        """Re-list the folder. Returns how many frames were appended (0 when nothing changed)."""
        previous = len(self._frames)
        matcher = re.compile(self.pattern) if self.pattern else None

        candidates = []
        try:
            for entry in self.root.iterdir():
                if entry.name.startswith("."):
                    continue
                if matcher is None or matcher.fullmatch(entry.name):
                    candidates.append(entry)
        except OSError as error:
            logging.warning(f"Unable to list the 4D folder {self.root}: {error}")
            return 0

        candidates.sort(key=frame_sort_key)
        self._frames = [
            Frame(index=index, path=path, label=self._label(path), key=path.name)
            for index, path in enumerate(candidates)
        ]

        return max(0, len(self._frames) - previous)

    @staticmethod
    def _label(path: Path) -> str:
        """Human label for a frame: its number when it has one (an LBPM timestep), else its name."""
        match = TRAILING_DIGITS.search(path.stem if path.is_file() else path.name)
        return match.group(1) if match else path.name

    # -- description ----------------------------------------------------------------------------------
    def describe(self, refresh: bool = False) -> SourceInfo:
        """Metadata of the reference frame (the first readable one), with this dataset's variable applied."""
        if self._info is not None and not refresh:
            return self._info

        errors = []
        for frame in self._frames:
            try:
                with self.open_frame(frame.index) as source:
                    self._info = source.describe()
                    return self._info
            except Exception as error:
                errors.append(f"{frame.name}: {error}")

        raise SourceError(
            f"None of the {len(self._frames)} frames in {self.root} could be read."
            + (f" First problems: {'; '.join(errors[:3])}" if errors else "")
        )

    def variables(self) -> Tuple[str, ...]:
        return self.describe().variables

    def spacing_zyx(self) -> Tuple[float, float, float]:
        return self.describe().spacing_zyx or (1.0, 1.0, 1.0)

    def preview_factor(self, target: int = None) -> int:
        info = self.describe()
        return sample_factor(info.shape_zyx, **({"target": target} if target else {}))

    # -- reading --------------------------------------------------------------------------------------
    def open_frame(self, index: int, reference: SourceInfo = None) -> VirtualSource:
        """Open one frame, telling it the geometry the sequence expects (see ragged frames above)."""
        frame = self.frame(index)
        source = open_source(frame.path, variable=self.variable, **self.source_options)

        reference = reference or self._info
        if reference is not None and reference.shape_zyx:
            source.set_reference_shape(reference.shape_zyx)

        return source

    def read_frame(
        self,
        index: int,
        factor: int = 1,
        origin_zyx: Sequence[int] = (0, 0, 0),
        size_zyx: Sequence[int] = None,
        conform: bool = True,
    ) -> np.ndarray:
        """Read one frame. With ``conform`` the result always has the reference frame's sampled shape."""
        reference = self.describe()
        with self.open_frame(index, reference=reference) as source:
            array = source.read_window(origin_zyx=origin_zyx, size_zyx=size_zyx, factor=factor)

        if not conform:
            return array

        expected = self.sampled_shape(factor, origin_zyx=origin_zyx, size_zyx=size_zyx, info=reference)
        return conform_shape(array, expected)

    def sampled_shape(
        self,
        factor: int,
        origin_zyx: Sequence[int] = (0, 0, 0),
        size_zyx: Sequence[int] = None,
        info: SourceInfo = None,
    ) -> Tuple[int, ...]:
        from ..sources.base import window_slices

        info = info or self.describe()
        slices = window_slices(info.shape_zyx, origin_zyx, size_zyx, factor)
        shape = tuple(len(range(item.start, item.stop, item.step)) for item in slices)
        return shape + ((info.components,) if info.components > 1 else ())

    # -- identity -------------------------------------------------------------------------------------
    def signature(self) -> str:
        """Digest identifying this dataset's content, used to key (and reuse) a preview cache.

        Includes each frame's name and modification time, so appending or rewriting frames yields a new
        key while merely reopening the same folder reuses the cache built earlier.
        """
        digest = hashlib.blake2b(digest_size=16)
        digest.update(f"{self.root.as_posix()}|{self.pattern}|{self.variable}".encode("utf-8"))
        for frame in self._frames:
            try:
                digest.update(f"{frame.name}|{frame.path.stat().st_mtime_ns}".encode("utf-8"))
            except OSError:
                digest.update(f"{frame.name}|missing".encode("utf-8"))
        return digest.hexdigest()

    def stable_key(self) -> str:
        """Digest of the dataset's identity only (folder, pattern, variable), stable while it grows."""
        digest = hashlib.blake2b(digest_size=12)
        digest.update(f"{self.root.as_posix()}|{self.pattern}|{self.variable}".encode("utf-8"))
        return digest.hexdigest()

    def __repr__(self) -> str:
        return f"FourDDataset({self.root.as_posix()!r}, pattern={self.pattern!r}, frames={len(self._frames)})"


def conform_shape(array: np.ndarray, shape: Sequence[int]) -> np.ndarray:
    """Crop and zero-fill ``array`` to ``shape``.

    Zero-filling (rather than repeating the last plane) keeps an incomplete frame visibly incomplete: while
    a simulation is running the user must be able to tell "this frame is still being written" from
    "this frame is finished".
    """
    shape = tuple(int(size) for size in shape)
    if array.shape == shape:
        return array

    result = np.zeros(shape, dtype=array.dtype)
    window = tuple(slice(0, min(actual, expected)) for actual, expected in zip(array.shape, shape))
    result[window] = array[window]
    return result
