import pytest

from commons.image.optimized_transforms import (
    DEFAULT_NULL_VALUES,
    format_null_values,
    handle_null_values,
    parse_null_values,
)
import numpy as np


def test_handle_null_values():
    a = np.array([1, 2, 3], dtype=np.uint8)
    b = np.array([0, 2, 4, 8], dtype=np.int64)
    c = np.array([-20.3, 0, 100], dtype=np.float32)

    # TODO(PL-1429b)
    # assert handle_null_values(a, {1, 2}) == 2
    assert handle_null_values(a, {2, 7}) == 0
    assert handle_null_values(b, {2, 4}) == -1
    assert handle_null_values(c, {0}) == -21

    assert np.array_equal(a, np.array([1, 0, 3], dtype=np.uint8))
    assert np.array_equal(b, np.array([0, -1, -1, 8], dtype=np.int64))
    assert np.array_equal(c, np.array([-20.3, -21, 100], dtype=np.float32))


@pytest.mark.parametrize(
    "text, expected",
    [
        pytest.param("-999.25, -9999.0", {-999.25, -9999.0}, id="two_values"),
        pytest.param(" -9999 ", {-9999.0}, id="surrounding_spaces"),
        pytest.param("", set(), id="empty_text"),
        pytest.param("   ", set(), id="blank_text"),
        pytest.param("-9999,0", {-9999.0, 0.0}, id="decimal_comma_is_a_list"),
        pytest.param("1e30", {1e30}, id="scientific_notation"),
    ],
)
def test_parse_null_values(text, expected):
    assert parse_null_values(text) == expected


def test_parse_null_values_accepts_nan():
    (value,) = parse_null_values("nan")
    assert np.isnan(value)


@pytest.mark.parametrize("text", ["abc", "-9999.0.0", "-9999 -999", ",", ",,,,", " , ", ", -9999.0", "-9999.0,"])
def test_parse_null_values_rejects_malformed_text(text):
    with pytest.raises(ValueError):
        parse_null_values(text)


def test_format_null_values_is_sorted_and_plain():
    assert format_null_values({-999.25, -9999.0, -9999.25}) == "-9999.25, -9999.0, -999.25"
    assert format_null_values(set()) == ""
    assert format_null_values([np.float64(-999.25)]) == "-999.25"


def test_null_values_round_trip():
    assert parse_null_values(format_null_values(DEFAULT_NULL_VALUES)) == DEFAULT_NULL_VALUES
