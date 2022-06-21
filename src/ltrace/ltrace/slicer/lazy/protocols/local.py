import numpy as np
import xarray as xr

from ltrace.slicer.lazy.protocols.base import BaseProtocol
from pathlib import Path


class LocalProtocol(BaseProtocol):
    PROTOCOL = "file"

    def load(self, *args, **kwargs) -> xr.Dataset:
        protocol, path = self.url.split("://")
        path = Path(path)
        if path.is_dir():
            with xr.open_dataset(next(path.glob("*.nc"))) as firstDataset:
                largestVolume = max(
                    firstDataset.data_vars,
                    key=lambda var: np.prod(firstDataset[var].shape),
                )
                axes = firstDataset[largestVolume].dims

            return xr.open_mfdataset((path / "*.nc").as_posix(), concat_dim=axes[0], combine="nested", chunks=256)

        return xr.open_dataset(path.as_posix())
