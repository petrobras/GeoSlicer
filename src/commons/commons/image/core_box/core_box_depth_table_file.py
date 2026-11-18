import os
import pandas as df


class CoreBoxDepth:
    def __init__(self, start, end):
        self.__start = start
        self.__end = end

    @property
    def start(self):
        return self.__start

    @property
    def end(self):
        return self.__end

    @property
    def height(self):
        return abs(self.__end - self.__start)


class CoreBoxDepthTableFile:
    def __init__(self, table_file):
        self.__core_boxes_depth_list = list()
        self.__import_table_file(table_file)

    @property
    def core_boxes_depth_list(self):
        return self.__core_boxes_depth_list

    def __convert_string_to_float(self, value_str):
        if not isinstance(value_str, str):
            return value_str

        if value_str == "":
            return -1

        value_str_split = value_str.split(",")
        if len(value_str_split) == 2:  # one comma occurrence
            value_str = value_str.replace(",", ".")
        elif len(value_str_split) > 2:  # multiples comma occurrence
            value_str = value_str.replace(",", "")

        return float(value_str)

    def __import_table_file(self, table_file):
        if table_file is None or not os.path.isfile(table_file):
            raise RuntimeError("Core depth file not found: {}".format(table_file))

        try:
            table_df = df.read_csv(table_file, delimiter=",", header=None)
        except Exception as e:
            raise RuntimeError("Error while loading core depth file: {}: {}".format(table_file, str(e)))

        last_end_value = 0
        for idx in range(len(table_df.index)):
            start_value = self.__convert_string_to_float(table_df.iloc[idx, 0])
            end_value = self.__convert_string_to_float(table_df.iloc[idx, 1])
            if start_value < last_end_value:
                raise RuntimeError(
                    "Failed to complete execution. "
                    "There are unordered or overlapped depth values in the core depth file: "
                    f"{table_file} at index {idx}"
                )
            elif end_value <= start_value:
                raise RuntimeError(
                    "Failed to complete execution. "
                    "There are inconsistent depth values in the core depth file: "
                    f"{table_file} at index {idx}"
                )
            core_info = CoreBoxDepth(start=start_value, end=end_value)
            self.__core_boxes_depth_list.append(core_info)
            last_end_value = end_value
