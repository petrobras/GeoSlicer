import logging

import chardet
import pandas as pd
from detect_delimiter import detect


def read_csv(filepath, whitelist=None, **kwargs):
    """
    Detects the csv file enconding and delimiter (if they aren't passed as kwargs), and forwards them to the pandas
    csv_reader function.
    There must be separate read funcions (detect_file_encoding and detect_csv_file_delimiter, that can be used elsewhere):
        - detect_file_encoding reads the file as binary to detect the encoding;
        - detect_csv_file_delimiter reads the file as non binary to detect the delimiter;
        - finally the pandas read_csv function is called with the encoding and delimiter configured;
    :param filepath: CSV file path
    :return: pandas dataframe
    """

    ENCODING = "encoding"
    DELIMITER = "delimiter"
    SEP = "sep"
    DECIMAL = "decimal"

    if whitelist is None:
        whitelist = [";", ","]

    if ENCODING in kwargs:
        encoding = kwargs[ENCODING]
        kwargs.pop(ENCODING, None)
    else:
        encoding = detect_file_encoding(filepath)

    if DELIMITER in kwargs:
        delimiter = kwargs[DELIMITER]
        kwargs.pop(DELIMITER, None)
    elif SEP in kwargs:
        delimiter = kwargs[SEP]
        kwargs.pop(SEP, None)
    else:
        delimiter = detect_csv_file_delimiter(filepath, encoding, whitelist)

    if DECIMAL in kwargs:
        decimal = kwargs[DECIMAL]
        kwargs.pop(DECIMAL, None)
    else:
        decimal = "," if delimiter == ";" else "."

    return pd.read_csv(filepath, delimiter=delimiter, encoding=encoding, decimal=decimal, **kwargs)


def count_outside_quotes(string, char):
    count = 0
    in_quotes = False
    for c in string:
        if c == '"':
            in_quotes = not in_quotes
        elif c == char and not in_quotes:
            count += 1
    return count


def number_of_delimiters_per_line(lines, delimiter):
    count = count_outside_quotes(lines[0], delimiter)
    for line in lines[1:]:
        if count_outside_quotes(line, delimiter) != count:
            return 0
    return count


def detect_file_encoding(filepath):
    try:
        # read as binary and detect encoding
        with open(filepath, "rb") as file:
            data = file.read(1000)
            encoding = chardet.detect(data)["encoding"]
        return encoding
    except Exception as e:
        logging.critical(repr(e))
        return None


def detect_csv_file_delimiter(filepath, encoding, whitelist=[",", ";"]):
    try:
        # read in non binary with encoding, to detect delimiter
        with open(filepath, "r", encoding=encoding) as file:
            data = file.readlines(50)
            counters = {}
            for delimiter in whitelist:
                count = number_of_delimiters_per_line(data, delimiter)
                counters[delimiter] = count
            return max(counters, key=counters.get)

    except Exception as e:
        logging.critical(repr(e))
        return None
