import os

from ltrace.file_utils import read_csv


class InspectorVariablesFile:
    """Class responsible to load inspector variables output file data.

    Raises:
        RuntimeError: If protocol doesn't match any definition or if file isn't valid.
    """

    VERSION_1 = 0
    VERSION_2 = 1
    VERSION_3 = 2

    TEMPLATE = {
        VERSION_1: {
            "Voxel Size (mm²)": "Pixel Area (mm^2)",
            "ROI Voxel Count (#px)": "ROI Voxel Count (#px)",
            "Target Segment Voxel Count (#px)": "Segment Voxel Count (#px)",
        },
        VERSION_2: {
            "Voxel Size (mm^2)": "Pixel Area (mm^2)",
            "ROI Voxel Count (#px)": "ROI Voxel Count (#px)",
            "Target Segment Voxel Count (#px)": "Segment Voxel Count (#px)",
        },
        VERSION_3: {
            "Pixel Area (mm^2)": "Pixel Area (mm^2)",
            "ROI Voxel Count (#px)": "ROI Voxel Count (#px)",
            "Segment Voxel Count (#px)": "Segment Voxel Count (#px)",
        },
    }

    def __init__(self, file: str):
        self.__filename = file

        if not os.path.isfile(file):
            raise RuntimeError("File {} doesn't not exist.".format(file))

        self.__data = read_csv(self.__filename, sep="\t", encoding=None)
        self.__version = self._check_version()
        self.__consolidate_headers()

    @property
    def version(self):
        return self.__version

    @property
    def filename(self):
        return self.__filename

    @property
    def data(self):
        return self.__data

    @staticmethod
    def header(version=VERSION_2):
        parameters = [
            parameter for parameter in InspectorVariablesFile.TEMPLATE[version].values() if parameter is not None
        ]
        return parameters

    def _check_version(self):
        temp_df = self.__data.set_index(self.__data.columns[0])
        indexes = list(temp_df.index)
        if len(indexes) <= 0:
            raise RuntimeError("Invalid content in variables file {}".format(self.__filename))

        def check_version_pattern(version, current_indexes):
            version_template = self.TEMPLATE.get(version, None)
            if version_template is None:
                raise RuntimeError("The variables file's version specified is not defined. Please check this behavior.")

            expected_indexes = [
                parameter
                for parameter, compatibility_label in version_template.items()
                if compatibility_label is not None
            ]
            for expected_index in expected_indexes:
                if expected_index not in current_indexes:
                    return False

            return True

        versions = self.TEMPLATE.keys()
        current_version = None
        for version in versions:
            if check_version_pattern(version=version, current_indexes=indexes) is True:
                current_version = version

        if current_version is None:
            raise RuntimeError(
                "Couldn't define which pattern the related variables file is: {}".format(self.__filename)
            )

        return current_version

    def __consolidate_headers(self):
        """Maintain DataFrame header (index) compatibility between older and newer versions."""
        rename_headers = {key: value for key, value in self.TEMPLATE[self.__version].items()}
        self.__data = self.__data.rename(index=rename_headers)
