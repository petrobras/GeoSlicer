import numpy as np
import pandas as pd
import shutil
import tempfile

from commons.slicer.helpers import export_las_from_histogram_in_depth_data, make_directory_writable
from pathlib import Path


class TestExportToLas:
    """Test suite for export table to LAS feature"""

    def setup_method(self):
        self.temp_dir_path = Path(tempfile.TemporaryDirectory().name)
        self.temp_dir_path.mkdir(parents=True, exist_ok=True)

    def teardown_method(self):
        if hasattr(self, "temp_dir_path") and self.temp_dir_path.exists():
            shutil.rmtree(self.temp_dir_path, onexc=make_directory_writable)

    def test_histogram_in_depth_table_data_ascending_order(self):
        file_path = self.temp_dir_path / "testfile.las"
        # fmt: off
        array = np.array([
            ['X', 0.029578, 0.0424143, 0.0608213, 0.0872165, 0.125067,
            0.179343, 0.257175, 0.368784, 0.528829, 0.758331, 1.08743,
            1.55936, 2.23609, 3.20651, 4.59807, 6.59355, 9.45502, 13.5583,
            19.4424, 27.88],
            ['5851.1', 0.016911, 0.0419662, 0.0594516, 0.0830233, 0.110061,
            0.178541, 0.351434, 0.583017, 0.977293, 1.7715, 2.26625, 3.0,
            0.840756, 1.45981, 0.360719, 0.0, 1.05821, 0.0, 0.0, 0.0],
            ['5862.0', 0.250849, 0.700934, 1.21362, 1.67544, 2.49729, 2.61117,
                3.0, 2.62984, 1.30456, 1.40788, 0.125425, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ['5871.0', 0.986908, 2.41155, 3.0, 1.98752, 1.24963, 0.619063,
                0.302997, 0.0, 0.054406, 0.0, 0.0, 0.167337, 0.199015, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ['5881.2', 0.528651, 1.53823, 2.58757, 2.94192, 3.0, 2.37399,
                1.43332, 0.5723, 0.403687, 0.254769, 0.0, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ], dtype=object)
        # fmt: on
        df = pd.DataFrame(array)
        result = export_las_from_histogram_in_depth_data(df, file_path=file_path.as_posix())
        assert result is True

    def test_histogram_in_depth_table_data_descending_order(self):
        file_path = self.temp_dir_path / "testfile.las"
        # fmt: off
        array = np.array([
            ['5851.1', 0.016911, 0.0419662, 0.0594516, 0.0830233, 0.110061,
            0.178541, 0.351434, 0.583017, 0.977293, 1.7715, 2.26625, 3.0,
            0.840756, 1.45981, 0.360719, 0.0, 1.05821, 0.0, 0.0, 0.0],
            ['5862.0', 0.250849, 0.700934, 1.21362, 1.67544, 2.49729, 2.61117,
                3.0, 2.62984, 1.30456, 1.40788, 0.125425, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ['5871.0', 0.986908, 2.41155, 3.0, 1.98752, 1.24963, 0.619063,
                0.302997, 0.0, 0.054406, 0.0, 0.0, 0.167337, 0.199015, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ['5881.2', 0.528651, 1.53823, 2.58757, 2.94192, 3.0, 2.37399,
                1.43332, 0.5723, 0.403687, 0.254769, 0.0, 0.0, 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0],
            ['X', 0.029578, 0.0424143, 0.0608213, 0.0872165, 0.125067,
            0.179343, 0.257175, 0.368784, 0.528829, 0.758331, 1.08743,
            1.55936, 2.23609, 3.20651, 4.59807, 6.59355, 9.45502, 13.5583,
            19.4424, 27.88]
            ], dtype=object)
        # fmt: on

        df = pd.DataFrame(array)
        result = export_las_from_histogram_in_depth_data(df, file_path=file_path.as_posix())

        assert result is True
