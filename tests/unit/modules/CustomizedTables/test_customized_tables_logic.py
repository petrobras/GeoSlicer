import pytest

from CustomizedTables.CustomizedTables import CustomizedTablesLogic


def columnIndexToLetter(columnIndex):
    """Excel-style column name for a 0-based index (A, B, ..., Z, AA, AB, ...).

    An independent inverse of the logic's conversion, kept here because only the tests
    need it: the module itself never converts an index back to a letter.
    """
    letters = ""
    index = columnIndex + 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


@pytest.mark.parametrize(
    "letter,index",
    [("A", 0), ("Z", 25), ("AA", 26), ("AZ", 51), ("BA", 52), ("ZZ", 701)],
)
def test_column_letter_index_round_trip(letter, index):
    assert CustomizedTablesLogic.columnLetterToIndex(letter) == index
    # Feed the inverse back through the production conversion, so the two must agree
    assert columnIndexToLetter(index) == letter
    assert CustomizedTablesLogic.columnLetterToIndex(columnIndexToLetter(index)) == index


def test_column_letter_to_index_rejects_invalid_letter():
    with pytest.raises(ValueError):
        CustomizedTablesLogic.columnLetterToIndex("A1")


def test_column_letter_pattern_extracts_double_letter_tokens():
    # Regression test: tokens like "AA"/"AB" must be extracted whole, not
    # confused with substrings "A"/"B" inside them.
    matches = CustomizedTablesLogic.COLUMN_LETTER_PATTERN.findall("AA + B - AB*2")
    assert matches == ["AA", "B", "AB"]
