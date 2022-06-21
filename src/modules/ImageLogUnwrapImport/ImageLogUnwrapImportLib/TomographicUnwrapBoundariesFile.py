from ltrace.file_utils import read_csv


class TomographicUnwrapBoundariesFile:
    VERSION_0 = 0

    TEMPLATE = {
        VERSION_0: {"poco": str, "testemunho": int, "caixa": int, "topo_caixa_m": float, "base_caixa_m": float},
    }

    def __init__(self, filename: str):
        self.__filename = filename
        self.__data = read_csv(self.__filename, encoding=None)

    @property
    def data(self):
        return self.__data

    def check_version(self):
        actual_columns = list(self.__data.columns)
        if len(actual_columns) <= 0:
            return False, "Invalid content in boundaries file"

        expected_columns = self.TEMPLATE[self.VERSION_0].keys()
        for column in expected_columns:
            if column not in actual_columns:
                return False, f'Invalid boundaries file. Missing "{column}" column.'

        return True, ""
