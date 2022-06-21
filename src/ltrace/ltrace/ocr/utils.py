import pandas as pd
import camelot


def parse_pdf(filepath, pages=None, columns=None, remove_extra=False):

    n_cols = 0
    column_names = None
    if isinstance(columns, int):
        n_cols = columns
        column_names = []
    elif isinstance(columns, list):
        n_cols = len(columns)
        column_names = [c.lower() for c in columns]
    elif columns is None:
        pass
    else:
        raise ValueError(f"Argument Error: 'columns' must be a interger or a list of column names.")

    if pages is None:
        pages = "1-end"

    parse_args = dict(
        pages=pages, columns=["100,129,157,216,250,279,309,349,389,429,475,520"], split_text=True, strip_text="\n"
    )

    parse_types = [float, str, str, str, str, float, float, float, str, float, float, float, float]

    tables = camelot.read_pdf(filepath, flavor="stream", **parse_args)

    if column_names:
        df_list = list(extract_by(tables, column_names, parse_types, remove_extra))
    else:
        df_list = list(extract_all(tables, parse_types))

    if len(df_list) > 0:
        return pd.concat(df_list)

    return pd.DataFrame()


def extract_all(tables, parse_types):
    for table in tables:
        df = sanitize(table.df)
        df_columns = df.columns
        df = correct_types(df, parse_types)
        yield df


def extract_by(tables, column_names, parse_types, remove_extra):
    for table in tables:
        df = sanitize(table.df)
        found = match(df.columns, column_names)
        if found:
            df = correct_types(df, parse_types)
            if remove_extra:
                yield df[found].copy()
            else:
                yield df


def match(df_columns, filters):
    matches = []
    for pattern in filters:
        for column in df_columns:
            lowered = column.lower()
            if pattern in lowered:
                matches.append(column)
                break
        else:
            return None
    return matches


def correct_types(df, types):
    for i, type_ in enumerate(types):
        if type_ is float:
            df.iloc[:, i] = (
                df.iloc[:, i]
                .str.replace(",", ".", regex=False)
                .str.replace("<(\d+\.?\d+)", "0", regex=True)
                .astype(float)
            )
        elif type_ is int:
            df.iloc[:, i] = df.iloc[:, i].astype(int)
        else:
            df.iloc[:, i] = df.iloc[:, i].str.replace("\\", "/", regex=False).astype(str)
    return df


def sanitize(df):
    if isinstance(df.columns, pd.RangeIndex):
        header, values = look_for_header(df.iloc[0])
        df.columns = header
        df.iloc[0, :] = values
    return df


def look_for_header(row):
    header = []
    values = []
    for col_value in row:
        terms = col_value.split(" ")
        header.append(" ".join(terms[:-1]))
        values.append(terms[-1])
    return header, values
