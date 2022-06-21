import os

from ltrace.file_utils import read_csv


class InspectorReportFile:
    """Class responsible to load inspector report output file data.

    Raises:
        RuntimeError: If protocol doesn't match any definition or if file isn't valid.
    """

    VERSION_0 = 0
    VERSION_1 = 1
    VERSION_2 = 2
    VERSION_3 = 3
    VERSION_4 = 4
    VERSION_5 = 5

    TEMPLATE = {
        VERSION_0: {
            "Label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area": ("area", float),
            "angle": ("angle", float),
            "max_feret": ("max_feret", float),
            "min_feret": ("min_feret", float),
            "mean_feret": ("mean_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter": ("ellipse_perimeter", float),
            "ellipse_area": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter": ("perimeter", float),
            "perimeter_over_area": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "pore_size_class_label": ("pore_size_class_label", str),
            "mean": (None, None),
            "median": (None, None),
            "stddev": (None, None),
        },
        VERSION_1: {
            "Label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area": ("area", float),
            "angle": ("angle", float),
            "max_feret": ("max_feret", float),
            "min_feret": ("min_feret", float),
            "mean_feret": ("mean_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter": ("ellipse_perimeter", float),
            "ellipse_area": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter": ("perimeter", float),
            "perimeter_over_area": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "pore_size_class_label": ("pore_size_class_label", str),
            "mean": (None, None),
            "median": (None, None),
            "stddev": (None, None),
            "gamma": (None, None),
        },
        VERSION_2: {
            "label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area": ("area", float),
            "angle": ("angle", float),
            "max_feret": ("max_feret", float),
            "min_feret": ("min_feret", float),
            "mean_feret": ("mean_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter": ("ellipse_perimeter", float),
            "ellipse_area": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter": ("perimeter", float),
            "perimeter_over_area": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "pore_size_class_label": ("pore_size_class_label", str),
            "gamma": (None, None),
        },
        VERSION_3: {
            "label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area": ("area", float),
            "angle": ("angle", float),
            "max_feret": ("max_feret", float),
            "min_feret": ("min_feret", float),
            "mean_feret": ("mean_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter": ("ellipse_perimeter", float),
            "ellipse_area": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter": ("perimeter", float),
            "perimeter_over_area": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "pore_size_class_label": ("pore_size_class_label", str),
            "gamma": ("gamma", float),
        },
        VERSION_4: {
            "label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area (mm^2)": ("area", float),
            "angle (deg)": ("angle", float),
            "max_feret (mm)": ("max_feret", float),
            "min_feret (mm)": ("min_feret", float),
            "mean_feret (mm)": ("mean_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter (mm)": ("ellipse_perimeter", float),
            "ellipse_area (mm^2)": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area (1/mm)": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter (mm)": ("perimeter", float),
            "perimeter_over_area (1/mm)": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "pore_size_class_label": ("pore_size_class_label", str),
            "gamma": ("gamma", float),
        },
        VERSION_5: {
            "label": ("label", str),
            "voxelCount": ("voxelCount", int),
            "area (mm^2)": ("area", float),
            "angle (deg)": ("angle", float),
            "max_feret (mm)": ("max_feret", float),
            "min_feret (mm)": ("min_feret", float),
            "aspect_ratio": ("aspect_ratio", float),
            "elongation": ("elongation", float),
            "eccentricity": ("eccentricity", float),
            "ellipse_perimeter (mm)": ("ellipse_perimeter", float),
            "ellipse_area (mm^2)": ("ellipse_area", float),
            "ellipse_perimeter_over_ellipse_area (1/mm)": ("ellipse_perimeter_over_ellipse_area", float),
            "perimeter (mm)": ("perimeter", float),
            "perimeter_over_area (1/mm)": ("perimeter_over_area", float),
            "pore_size_class": ("pore_size_class", int),
            "gamma": ("gamma", float),
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
    def header(version=VERSION_5, accept_types=[str, int, float]):
        parameters = [
            parameter[0]
            for parameter in InspectorReportFile.TEMPLATE[version].values()
            if parameter is not None and parameter[1] in accept_types
        ]

        return parameters

    def _check_version(self):
        columns = list(self.__data.columns)
        if len(columns) <= 0:
            raise RuntimeError("Invalid content in report file {}".format(self.__filename))

        def check_version_pattern(version, current_columns):
            version_template = self.TEMPLATE.get(version, None)
            if version_template is None:
                raise RuntimeError("The report file's version specified is not defined. Please check this behavior.")

            expected_columns = [
                parameter
                for parameter, compatibility_label in version_template.items()
                if compatibility_label is not None
            ]

            for expected_column in expected_columns:
                if expected_column not in current_columns:
                    return False

            return True

        versions = self.TEMPLATE.keys()
        current_version = None
        for version in versions:
            if check_version_pattern(version=version, current_columns=columns) is True:
                current_version = version

        if current_version is None:
            raise RuntimeError("Couldn't define which pattern the related report file is: {}".format(self.__filename))

        return current_version

    def __consolidate_headers(self):
        """Maintain DataFrame header (column) compatability between older and newer versions."""
        rename_headers = {key: value[0] for key, value in self.TEMPLATE[self.__version].items()}
        self.__data = self.__data.rename(columns=rename_headers)
