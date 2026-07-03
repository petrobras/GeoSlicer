import logging
import typing

import chardet
import pandas as pd

from pathlib import Path


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


def load_and_parse_data(
    file_path: Path, filter_empty_columns: bool = False, delimiter: typing.Optional[str] = None
) -> typing.Union[pd.DataFrame, None]:
    """
    Data loader that handles CSV and Excel files like SIRR.
    It automatically detects:
    - The actual header row (ignoring titles/metadata above it).
    - The decimal separator ('.' vs ',').
    """

    def find_header_index(df_temp):
        """Helper to find which row index contains the header keywords."""
        for idx, row in df_temp.iterrows():
            # Convert row to a single string for easy searching
            if row.hasnans is False:
                return idx
        return 0  # Default to first row if no keyword found

    def detect_decimal_separator(sample_data):
        """
        Helper to guess decimal separator.
        Returns ',' if it sees 'number,number' pattern, else '.'
        """
        import re

        # Join sample data into one string
        text = " ".join(sample_data.astype(str).values.flatten().tolist())

        # Regex to find N,N pattern (e.g. 12,5)
        if re.search(r"\d,\d", text):
            return ","
        return "."

    # 2. Determine file extension
    ext = file_path.suffix.lower()

    try:
        if ext == ".csv":
            encoding = detect_file_encoding(file_path)
            engine_value = "python" if delimiter is None else "c"

            # Read first without header to scan content
            df_raw = pd.read_csv(file_path, header=None, encoding=encoding, sep=delimiter, engine=engine_value)
            header_idx = find_header_index(df_raw)

            decimal_char = detect_decimal_separator(df_raw.iloc[header_idx + 1 : header_idx + 6])

            # Load the final dataframe with correct parameters
            df = pd.read_csv(
                file_path,
                header=header_idx,
                decimal=decimal_char,
                encoding=encoding,
                sep=delimiter,
                engine=engine_value,
            )

        elif ext in [".xlsx", ".xls"]:
            # --- EXCEL HANDLING ---

            # Read first without header to scan content
            df_raw = pd.read_excel(file_path, header=None)

            # Find the true header row
            header_idx = find_header_index(df_raw)
            # Reload with the correct header
            df = pd.read_excel(file_path, header=header_idx)

            # Excel sometimes reads numbers as strings if decimals were ambiguous
            # We check object columns and convert if necessary
            for col in df.select_dtypes(include=["object"]):
                # specific check: if column has commas, try converting to float
                sample = df[col].dropna().astype(str).iloc[:5]
                if sample.str.contains(r"\d,\d").any():
                    # Clean and convert: 1.000,00 -> 1000.00
                    df[col] = df[col].astype(str).str.replace(".", "", regex=False).str.replace(",", ".")
                    df[col] = pd.to_numeric(df[col], errors="ignore")

        else:
            raise ValueError(f"Unsupported file format: {ext}")

        # 3. Final Cleanup
        # Remove columns/rows that are purely empty (artifacts of bad parsing)
        df.dropna(how="all", axis=0, inplace=True)
        if filter_empty_columns:
            df.dropna(how="all", axis=1, inplace=True)

        # Reset index after dropping rows
        df.reset_index(drop=True, inplace=True)

        logging.info(f"Detected Header Row: {header_idx}")
        return df

    except Exception as e:
        logging.warning(f"Error processing file: {e}")
        return None
