"""LBPM writes whitespace-separated logs named ``.csv``; the report has to read them and derive the curves."""

import textwrap

import pytest

from commons.lbpm.results import LBPMResults

TIMELOG = textwrap.dedent(
    """\
    sw krw krn krwf krnf vw vn force pw pn wet peff
    0.99680692 0.12040476 0.005769583 0.12 0.0057 4.7e-06 7.5e-08 -6.4e-07 0.33356193 0.336716 0 -7.9255417
    0.89618272 0.10581373 0.0145011706 0.10 0.0145 6.5e-06 9.2e-08 -1.0e-06 0.33379346 0.33868284 0 -9.0649587
    0.79557700 0.09901500 0.0245011706 0.09 0.0245 7.5e-06 9.9e-08 -1.2e-06 0.33400000 0.34000000 0 -9.7018560
    """
)

SUBPHASE = textwrap.dedent(
    """\
    time rn rw Vwc Vwd Vnc Vnd pwc pnc Ai Xnc Xwc
    10000 1 1 2176539 562191 10162 8773 0.33361538 0.33671624 4244.9643 0.125 -0.125
    20000 1 1 2000000 500000 300000 100000 0.33390420 0.33868295 4722.0770 0.125 -1.6648753
    """
)

SOLID = "Vs As Hs Xs\n8440817 557840.06 14122.386 -0.25\n"


@pytest.fixture
def case(tmp_path):
    (tmp_path / "timelog.csv").write_text(TIMELOG)
    (tmp_path / "subphase.csv").write_text(SUBPHASE)
    (tmp_path / "solid.csv").write_text(SOLID)
    (tmp_path / "minkowski.csv").write_text("Vn An Jn Xn\n")
    for step in (10000, 20000):
        (tmp_path / f"vis{step}").mkdir()
    return tmp_path


def test_reads_whitespace_separated_logs(case):
    results = LBPMResults.load(case)

    assert results.has_data
    assert results.timelog is not None and results.timelog.shape == (3, 12)
    assert results.subphase is not None and results.subphase.shape == (2, 12)
    assert results.solid["Vs"] == pytest.approx(8440817)
    assert results.frames == ["vis10000", "vis20000"]


def test_empty_logs_are_not_data(tmp_path):
    (tmp_path / "timelog.csv").write_text("")
    results = LBPMResults.load(tmp_path)
    assert not results.has_data
    assert results.summary()["frames"] == 0


def test_saturation_comes_from_the_subphase_volumes(case):
    results = LBPMResults.load(case)
    saturation = results.saturation()

    # (Vwc + Vwd) / (Vwc + Vwd + Vnc + Vnd)
    assert saturation.iloc[0] == pytest.approx((2176539 + 562191) / (2176539 + 562191 + 10162 + 8773))
    assert saturation.iloc[1] == pytest.approx(2500000 / 2900000)


def test_capillary_pressure_is_the_connected_phase_difference(case):
    results = LBPMResults.load(case)
    assert results.capillary_pressure().iloc[0] == pytest.approx(0.33671624 - 0.33361538)


def test_curves_cover_the_report(case):
    results = LBPMResults.load(case)
    curves = {curve.key: curve for curve in results.curves()}

    assert set(curves) == {
        "relative_permeability",
        "effective_pressure",
        "saturation_history",
        "capillary_pressure",
        "interfacial_area",
        "euler_characteristic",
    }

    relative = curves["relative_permeability"]
    assert relative.points == 3
    assert set(relative.series) == {"krw", "krn"}
    assert relative.x[0] == pytest.approx(0.99680692)

    assert curves["saturation_history"].x == [10000, 20000]
    assert set(curves["euler_characteristic"].series) == {"Xnc", "Xwc"}


def test_summary_reports_the_endpoints(case):
    summary = LBPMResults.load(case).summary()

    assert summary["steady_points"] == 3
    assert summary["sw_initial"] == pytest.approx(0.99680692)
    assert summary["sw_final"] == pytest.approx(0.795577)
    assert summary["krw_final"] == pytest.approx(0.099015)
    assert summary["last_timestep"] == 20000
    assert summary["frames"] == 2
    # Porosity uses the first analysis row's fluid volumes against the solid volume.
    assert summary["porosity"] == pytest.approx((2176539 + 562191 + 10162 + 8773) / (2757665 + 8440817), rel=1e-3)
