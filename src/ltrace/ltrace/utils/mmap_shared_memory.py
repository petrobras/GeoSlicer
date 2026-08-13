import mmap
import os
import tempfile

import numpy as np


class MmapSharedMemory:
    """File-backed mmap replacing multiprocessing.SharedMemory for inter-process array sharing."""

    def __init__(self, mm, path):
        self._mm = mm
        self.name = path
        self.buf = mm

    @classmethod
    def create(cls, size):
        fd, path = tempfile.mkstemp()
        os.ftruncate(fd, size)
        mm = mmap.mmap(fd, size)
        os.close(fd)
        return cls(mm, path)

    @classmethod
    def from_file(cls, path):
        fd = os.open(path, os.O_RDWR)
        mm = mmap.mmap(fd, 0)
        os.close(fd)
        return cls(mm, path)

    @classmethod
    def create_array(cls, array, dtype=None):
        _dtype = np.dtype(dtype) if dtype is not None else array.dtype
        size = array.size * _dtype.itemsize
        fd, path = tempfile.mkstemp()
        os.ftruncate(fd, size)
        mm = mmap.mmap(fd, size)
        os.close(fd)
        shared = np.ndarray(array.shape, dtype=_dtype, buffer=mm)
        shared[:] = array
        return cls(mm, path)

    def close(self):
        try:
            self._mm.close()
        except Exception:
            pass
        try:
            os.unlink(self.name)
        except OSError:
            pass
