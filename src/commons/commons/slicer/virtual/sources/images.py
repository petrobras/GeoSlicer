"""Image sources: a single TIFF/PNG/JPEG file, or a directory read as one image stack.

Reads are always partial. Two paths exist for TIFF, and the distinction matters in practice:

* uncompressed TIFFs are memory-mapped, so a strided read touches only the pages and rows requested;
* compressed TIFFs (JPEG-in-TIFF, ``compression=7``, is common in reconstruction output) cannot be
  memory-mapped, so each needed page is decoded individually and the in-plane stride is applied after.

Either way the caller never pays for the whole stack.
"""

import logging
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

from .base import (
    CLASS_SCALAR_VOLUME,
    CLASS_VECTOR_VOLUME,
    KIND_VOLUME,
    SourceError,
    SourceInfo,
    VirtualSource,
    path_stamp,
    window_slices,
)
from .metadata import isotropic, spacing_from_name, tiff_spacing

TIFF_EXTENSIONS = (".tif", ".tiff")
OTHER_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp")
IMAGE_EXTENSIONS = TIFF_EXTENSIONS + OTHER_IMAGE_EXTENSIONS

IGNORED_NAMES = {"thumbs.db", ".ds_store"}
IGNORED_SUFFIXES = (".old", ".tmp", ".part", ".swp")


def is_image_candidate(path: Path) -> bool:
    """Whether ``path`` looks like an image plane worth including in a stack.

    Filters the junk that sits next to real reconstruction output (``Thumbs.db``, ``*.old`` backups,
    dot-files), which both reference datasets contain.
    """
    name = path.name.lower()
    return (
        path.is_file()
        and not name.startswith(".")
        and name not in IGNORED_NAMES
        and path.suffix.lower() in IMAGE_EXTENSIONS
        and not name.endswith(IGNORED_SUFFIXES)
    )


def list_image_files(folder: Path) -> List[Path]:
    from natsort import natsorted

    return natsorted((path for path in folder.iterdir() if is_image_candidate(path)), key=lambda p: p.name)


class _ImagePlaneReader:
    """Uniform ``(pages, height, width, components)`` view over one image file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.is_tiff = self.path.suffix.lower() in TIFF_EXTENSIONS
        self._memmap = None
        self._probed = None

    def probe(self) -> Tuple[int, int, int, int, str, float]:
        """``(pages, height, width, components, dtype, spacing_mm)`` read from headers only."""
        if self._probed is not None:
            return self._probed

        if self.is_tiff:
            import tifffile

            with tifffile.TiffFile(self.path.as_posix()) as handle:
                page = handle.pages[0]
                pages = len(handle.pages)
                shape = tuple(page.shape)
                height, width = shape[0], shape[1]
                components = shape[2] if len(shape) > 2 else 1
                dtype = str(page.dtype)
                spacing = tiff_spacing(page)
        else:
            import imageio.v3 as iio

            array = iio.imread(self.path.as_posix())
            pages = 1
            height, width = array.shape[0], array.shape[1]
            components = array.shape[2] if array.ndim > 2 else 1
            dtype = str(array.dtype)
            spacing = None

        self._probed = (pages, height, width, components, dtype, spacing)
        return self._probed

    def read_page(self, index: int, row_slice: slice, column_slice: slice) -> np.ndarray:
        if self.is_tiff:
            import tifffile

            if self._memmap is None:
                try:
                    self._memmap = tifffile.memmap(self.path.as_posix(), mode="r")
                except (ValueError, OSError, MemoryError) as error:
                    # Compressed (e.g. JPEG-in-TIFF) or otherwise non-mappable: decode page by page.
                    logging.debug(f"{self.path.name} is not memory-mappable ({error}); decoding pages.")
                    self._memmap = False

            if self._memmap is not False:
                mapped = self._memmap
                plane = mapped[index] if mapped.ndim > 2 and len(mapped) > index else mapped
                return np.asarray(plane[row_slice, column_slice])

            with tifffile.TiffFile(self.path.as_posix()) as handle:
                plane = handle.pages[index].asarray()
            return plane[row_slice, column_slice]

        import imageio.v3 as iio

        return iio.imread(self.path.as_posix())[row_slice, column_slice]

    def close(self) -> None:
        self._memmap = None


class ImageSource(VirtualSource):
    """A single image file (multi-page TIFFs are read as a Z stack)."""

    KIND = KIND_VOLUME
    EXTENSIONS = IMAGE_EXTENSIONS

    def __init__(self, path, variable: str = None, **options):
        super().__init__(path, variable=variable, **options)
        self._readers: List[_ImagePlaneReader] = []
        self._pages_per_file = 1

    # -- layout ---------------------------------------------------------------------------------------
    def _files(self) -> List[Path]:
        return [self.path]

    def _describe(self) -> SourceInfo:
        files = self._files()
        if not files:
            raise SourceError(f"No readable image found at {self.path}")

        self._readers = [_ImagePlaneReader(path) for path in files]
        pages, height, width, components, dtype, spacing = self._readers[0].probe()
        self._pages_per_file = pages

        shape_zyx = (pages * len(files), height, width)
        if spacing is None:
            spacing = spacing_from_name(self.path.name)

        return SourceInfo(
            kind=KIND_VOLUME,
            node_class=CLASS_VECTOR_VOLUME if components > 1 else CLASS_SCALAR_VOLUME,
            shape_zyx=shape_zyx,
            dtype=dtype,
            spacing_zyx=isotropic(spacing),
            components=components,
            variables=(self.path.stem,),
            variable=self.variable or self.path.stem,
            extra={"files": len(files), "pages_per_file": pages},
        )

    # -- reading --------------------------------------------------------------------------------------
    def read_window(self, origin_zyx: Sequence[int] = (0, 0, 0), size_zyx: Sequence[int] = None, factor: int = 1):
        info = self.describe()
        z_slice, y_slice, x_slice = window_slices(info.shape_zyx, origin_zyx, size_zyx, factor)
        indices = range(z_slice.start, z_slice.stop, z_slice.step)

        planes = []
        for global_index in indices:
            reader = self._readers[global_index // self._pages_per_file]
            plane = reader.read_page(global_index % self._pages_per_file, y_slice, x_slice)
            planes.append(plane)

        if not planes:
            raise SourceError(f"Empty window requested from {self.path}")

        return np.stack(planes, axis=0)

    def paths(self) -> Sequence[Path]:
        return self._files()

    def stamp(self) -> str:
        return path_stamp(self.paths())

    def close(self) -> None:
        for reader in self._readers:
            reader.close()
        self._readers = []
        super().close()


class ImageStackSource(ImageSource):
    """A directory whose image files form a single volume, one (or more) Z planes each."""

    @classmethod
    def can_open(cls, path: Path) -> bool:
        return path.is_dir() and bool(next((item for item in path.iterdir() if is_image_candidate(item)), None))

    def _files(self) -> List[Path]:
        return list_image_files(self.path)

    def _describe(self) -> SourceInfo:
        info = super()._describe()
        spacing = info.spacing_zyx
        if spacing == (1.0, 1.0, 1.0):
            # Folder names carry the convention more often than the plane files do.
            folder_spacing = spacing_from_name(self.path.name)
            if folder_spacing:
                spacing = isotropic(folder_spacing)
        return SourceInfo(
            kind=info.kind,
            node_class=info.node_class,
            shape_zyx=info.shape_zyx,
            dtype=info.dtype,
            spacing_zyx=spacing,
            components=info.components,
            variables=(self.path.name,),
            variable=self.variable or self.path.name,
            extra=info.extra,
        )
