from unittest.mock import patch
from commons.slicer.lazy.protocols.local import LocalProtocol
from pathlib import Path

import numpy as np
import xarray as xr


class TestLocalProtocol:
    @patch.object(Path, "is_dir", lambda x: False)
    @patch.object(Path, "exists", lambda x: True)
    @patch("xarray.open_dataset")
    @patch("xarray.open_mfdataset")
    def test_load_single_file(self, mock_open_mfdataset, mock_open_dataset):
        local_protocol = LocalProtocol("file://fake_file.nc")
        mock_dataset = xr.Dataset({"data_var": (("x", "y", "z"), np.random.rand(10, 5, 5))})
        mock_open_dataset.return_value = mock_dataset

        result = local_protocol.load()
        assert isinstance(result, xr.Dataset)
        mock_open_dataset.assert_called_once_with("fake_file.nc", engine="h5netcdf", backend_kwargs={"lock": False})
        mock_open_mfdataset.assert_not_called()

    @patch.object(Path, "is_dir", lambda x: True)
    @patch.object(Path, "glob", lambda x, y: iter(["path1"]))
    @patch.object(Path, "exists", lambda x: True)
    @patch("xarray.open_dataset")
    @patch("xarray.open_mfdataset")
    def test_load_directory(self, mock_open_mfdataset, mock_open_dataset):
        local_protocol = LocalProtocol("file://fake_directory")
        mock_dataset = xr.Dataset({"data_var": (("x", "y", "z"), np.random.rand(10, 5, 5))})
        mock_open_dataset.return_value = mock_dataset
        mock_open_mfdataset.return_value = mock_dataset

        result = local_protocol.load()
        assert isinstance(result, xr.Dataset)
        mock_open_mfdataset.assert_called_once()
