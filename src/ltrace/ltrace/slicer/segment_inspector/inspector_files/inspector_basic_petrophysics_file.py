import fnmatch
import os

from ltrace.file_utils import read_csv


class InspectorBasicPetrophysicsFile:
    VERSION_1 = 0
    VERSION_2 = 1
    VERSION_3 = 99

    TEMPLATE = {
        VERSION_1: {
            "Porosity (%)",
            "Density (g/cm^3)",
            "Bulk modulus (Gpa) - Mineral mix (lower)",
            "Bulk modulus (Gpa) - Mineral mix (upper)",
            "Shear modulus (Gpa) - Mineral mix (lower)",
            "Shear modulus (Gpa) - Mineral mix (upper)",
            "calcite (%)",
            "dolomite (%)",
            "pore (%)",
            "quartz (%)",
            "other (%)",
        },
        VERSION_2: {
            "Porosity (%)",
            "pore (%)",
            "other (%)",
        },
        VERSION_3: {  # Only onse segment old version representing porosity. Must be the last one because of check_version_logic
            "other (%)",
        },
    }

    def __init__(self, file: str):
        self.__filename = file

        if not os.path.isfile(file):
            raise RuntimeError("File {} doesn't not exist.".format(file))

        self.__data = read_csv(self.__filename, sep="\t")
        self.__version = self._check_version()

    @property
    def version(self):
        return self.__version

    @property
    def filename(self):
        return self.__filename

    @property
    def data(self):
        return self.__data

    def _check_version(self):
        temp_df = self.__data.set_index(self.__data.columns[0])
        indexes = list(temp_df.index)

        for v in self.TEMPLATE:
            version = v
            for column_name in self.TEMPLATE[v]:
                if column_name not in indexes:
                    version = -1
            if version >= 0:
                return version

        raise RuntimeError("Invalid content in basic petrophysics file {}".format(self.__filename))
