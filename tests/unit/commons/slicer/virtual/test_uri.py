"""Virtual URIs address a variable inside a file, or a folder plus a frame pattern."""

import pytest

from commons.slicer.virtual.uri import InvalidURIError, VirtualURI, file_uri, fourd_uri


def test_file_uri_round_trip():
    uri = file_uri("/data/tomo.nc", "microtom")
    parsed = VirtualURI.parse(uri)

    assert parsed.scheme == "file"
    assert parsed.path.as_posix() == "/data/tomo.nc"
    assert parsed.variable == "microtom"


def test_fourd_uri_keeps_a_regular_expression_intact():
    uri = fourd_uri("/data/LBPM", r"vis\d+", "phase")
    parsed = VirtualURI.parse(uri)

    assert parsed.scheme == "4d"
    assert parsed.pattern == r"vis\d+"
    assert parsed.variable == "phase"
    assert parsed.format() == uri


def test_uri_without_parameters_has_none():
    assert VirtualURI.parse(file_uri("/data/tomo.nc")).params == {}


def test_with_params_drops_none_values():
    uri = VirtualURI(scheme="file", path=__import__("pathlib").Path("/data")).with_params(var=None, stride=2)
    assert uri.params == {"stride": "2"}


@pytest.mark.parametrize("text", ["", "not a uri", "/data/tomo.nc", "file://"])
def test_invalid_uris_are_rejected(text):
    with pytest.raises(InvalidURIError):
        VirtualURI.parse(text)
