import numpy as np
from commons.slicer.helpers import safe_convert_array


def test_same_dtype():
    array = np.array([1, 2, 3], dtype=np.int32)
    result = safe_convert_array(array, np.int32)
    assert result.dtype == np.int32
    assert np.all(result == array)


def test_same_dtype_str():
    array = np.array([1, 2, 3], dtype=np.int32)
    result = safe_convert_array(array, "int32")
    assert result.dtype == np.int32
    assert np.all(result == array)


def test_int_to_uint():
    array = np.array([-10, 1, 2, 3], dtype=np.int32)
    result = safe_convert_array(array, "uint32")
    assert result.dtype == np.uint32
    assert np.all(result == np.array([0, 1, 2, 3], dtype=np.uint32))


def test_float_to_uint():
    array = np.array([-16.2, 1.1, 2.2, 3.3, 4.7], dtype=np.float32)
    result = safe_convert_array(array, "uint32")
    assert result.dtype == np.uint32
    assert np.all(result == np.array([0, 1, 2, 3, 5], dtype=np.uint32))


def test_double_to_float():
    array = np.array([1.1, 2.2, 3.3], dtype=np.float64)
    result = safe_convert_array(array, "float32")
    assert result.dtype == np.float32
    assert np.allclose(result, np.array([1.1, 2.2, 3.3], dtype=np.float32))


def test_float_to_int():
    array = np.array([-16.2, 1.1, 2.2, 3.3, 4.7], dtype=np.float32)
    result = safe_convert_array(array, "int32")
    assert result.dtype == np.int32
    assert np.all(result == np.array([-16, 1, 2, 3, 5], dtype=np.int32))


def test_uint16_to_uint8():
    array = np.array([1, 2, 3, 1000], dtype=np.uint16)
    result = safe_convert_array(array, "uint8")
    assert result.dtype == np.uint8
    assert np.all(result == np.array([1, 2, 3, 255], dtype=np.uint8))


def test_int16_to_int8():
    array = np.array([-1000, 2, 3, 1000], dtype=np.int16)
    result = safe_convert_array(array, "int8")
    assert result.dtype == np.int8
    assert np.all(result == np.array([-128, 2, 3, 127], dtype=np.int8))


def test_invalid_kinds():
    array = np.array([1, 2, 3], dtype=np.int32)
    try:
        safe_convert_array(array, "bool")
        assert False
    except ValueError:
        pass
    try:
        safe_convert_array(array.astype(bool), "uint8")
        assert False
    except ValueError:
        pass
