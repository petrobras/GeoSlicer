import numpy as np
import pytest

from SpectralProfile.SpectralProfile import DEFAULT_Z_EXPONENT as DEFAULT_N
from SpectralProfile.SpectralProfile import SUPERVISED_BYTES_PER_VOXEL, SpectralProfileLogic

Logic = SpectralProfileLogic

AXIS = np.linspace(160.0, 20.0, 15)
PAIR = np.array([0, 14])  # 160 and 20 kV of AXIS


def makeVolume():
    """Four slices of 6x8 pixels: air (100) on the left half, a material on the right half."""
    array = np.full((4, 6, 8), 100, dtype=np.uint16)
    array[:, :, 4:] = np.array([200, 300, 500, 900], dtype=np.uint16)[:, None, None]
    return array


def powerLawVolume(a, c, exponent=-3.0, axis=AXIS, noise=0.0, seed=0):
    """Volume where every pixel follows 1000 + a * (E / 100) ** exponent + c, `a` and `c` given per pixel [j, i]."""
    model = a[None] * (axis[:, None, None] / 100.0) ** exponent + c[None]
    rng = np.random.default_rng(seed)
    return 1000.0 + model + rng.normal(0, noise, model.shape)


def blobsVolume(noise=0.5):
    """Three materials as vertical bands, each with its own (a, c)."""
    a = np.zeros((30, 60))
    c = np.zeros((30, 60))
    for n, (aa, cc) in enumerate([(1.0, 5.0), (5.0, 30.0), (12.0, 55.0)]):
        a[:, n * 20 : (n + 1) * 20] = aa
        c[:, n * 20 : (n + 1) * 20] = cc
    return powerLawVolume(a, c, noise=noise), a, c


# ----- naming -----
def test_default_output_name_records_exponent_and_classes():
    assert Logic.defaultOutputName("microtom", -3.0, 4) == "microtom_spectral_b3_classes4_gmm"
    assert Logic.defaultOutputName("microtom", -2.5, 6) == "microtom_spectral_b2.5_classes6_gmm"
    assert Logic.defaultOutputName("", -3.0, 4) == ""


# ----- axis and selection -----
def test_axis_extent():
    assert Logic.axisExtent(np.array([160.0, 100.0, 40.0]), 3) == (10.0, 190.0)


def test_select_energy_range_is_inclusive_and_order_independent():
    axis = np.array([160.0, 140.0, 120.0, 100.0, 80.0, 60.0, 40.0, 20.0])
    assert list(Logic.selectEnergyRange(axis, 20, 160)) == list(range(8))
    assert list(Logic.selectEnergyRange(axis, 60, 120)) == [2, 3, 4, 5]
    assert list(Logic.selectEnergyRange(axis, 120, 60)) == [2, 3, 4, 5]
    assert list(Logic.selectEnergyRange(axis, 61, 119)) == [3, 4]
    assert len(Logic.selectEnergyRange(axis, 500, 600)) == 0


def test_unused_runs_and_energy_edges():
    assert Logic.unusedRuns(np.array([2, 3, 6]), 8) == [(0, 1), (4, 5), (7, 7)]
    assert Logic.unusedRuns(np.arange(5), 5) == []
    assert list(Logic.energyEdges(np.array([10.0, 20.0, 40.0]))) == [5.0, 15.0, 30.0, 50.0]


# ----- histogram -----
def test_background_is_most_frequent_value_per_slice():
    assert list(Logic.backgroundValues(makeVolume())) == [100] * 4


def test_histogram_counts_every_pixel_once_per_slice_and_puts_air_first():
    array = makeVolume()
    background = Logic.backgroundValues(array)
    counts, low, high = Logic().computeHeatmap(array, 16, background)
    assert counts.shape == (4, 16)
    assert (counts.sum(axis=1) == 6 * 8).all()
    assert low == pytest.approx(0.0) and high > low
    assert (counts[:, 0] == 24).all()  # air is zero attenuation


def test_histogram_with_mask_only_counts_the_soi():
    array = makeVolume()
    mask = np.zeros((6, 8), dtype=bool)
    mask[:, 4:] = True
    counts, _, _ = Logic().computeHeatmap(array, 8, Logic.backgroundValues(array), mask)
    assert (counts.sum(axis=1) == 24).all()


# ----- fit -----
def test_power_law_fit_recovers_the_parameters():
    a = np.linspace(1.0, 9.0, 40).reshape(8, 5)
    c = np.linspace(20.0, 60.0, 40).reshape(8, 5)
    array = powerLawVolume(a, c)
    fitted = Logic.powerLawFit(array, AXIS, -3.0, np.arange(len(AXIS)), np.full(len(AXIS), 1000.0))
    assert fitted[0] == pytest.approx(a, abs=1e-3)
    assert fitted[1] == pytest.approx(c, abs=1e-3)
    assert fitted[2].all()


def test_power_law_fit_uses_only_the_selected_energies():
    a = np.full((4, 4), 5.0)
    c = np.full((4, 4), 30.0)
    array = powerLawVolume(a, c)
    array[3] += 500  # a saturated slice that the selection leaves out
    selection = np.array([0, 1, 2, 4, 5, 6, 8, 10, 12])
    fitted_a, fitted_c, _ = Logic.powerLawFit(array, AXIS, -3.0, selection, np.full(len(AXIS), 1000.0))
    assert fitted_a[0, 0] == pytest.approx(5.0, abs=1e-3) and fitted_c[0, 0] == pytest.approx(30.0, abs=1e-3)


def test_power_law_fit_respects_mask_and_air():
    a = np.full((8, 5), 5.0)
    c = np.full((8, 5), 30.0)
    a[0, 0], c[0, 0] = 0.0, 0.0  # pure air
    array = powerLawVolume(a, c)
    mask = np.zeros((8, 5), dtype=bool)
    mask[:4] = True
    fitted_a, _, valid = Logic.powerLawFit(array, AXIS, -3.0, np.arange(len(AXIS)), np.full(len(AXIS), 1000.0), mask)
    assert not valid[0, 0] and valid[1, 1] and not valid[4:].any()
    assert fitted_a[1, 1] == pytest.approx(5.0, abs=1e-3)


# ----- clustering -----
def test_cluster_parameters_separates_blobs_orders_by_c_and_returns_fitted_gaussians():
    rng = np.random.default_rng(1)
    c = np.concatenate([rng.normal(10, 1, 500), rng.normal(40, 1, 500)]).reshape(20, 50)
    a = np.concatenate([rng.normal(2, 0.3, 500), rng.normal(8, 0.3, 500)]).reshape(20, 50)
    valid = np.ones_like(c, dtype=bool)
    labels, clusters = Logic.clusterParameters(c, a, valid, 2)
    assert len(clusters) == 2 and clusters[0]["mean"][0] < clusters[1]["mean"][0]
    assert (labels.ravel()[:500] == 1).all() and (labels.ravel()[500:] == 2).all()
    assert sum(k["weight"] for k in clusters) == pytest.approx(1.0)
    assert clusters[0]["mean"][0] == pytest.approx(10, abs=0.3) and clusters[1]["mean"][1] == pytest.approx(8, abs=0.2)


def test_ellipse_points_are_on_the_sigma_contour():
    outline = Logic.ellipsePoints([1.0, 2.0], np.diag([4.0, 1.0]), sigmas=1.0)
    assert outline[:, 0].max() == pytest.approx(3.0, abs=1e-2) and outline[:, 1].max() == pytest.approx(3.0, abs=1e-2)


# ----- calibration with standards -----
def test_parse_formula_handles_digits_and_nested_groups():
    assert Logic.parseFormula("SiO2") == {"Si": 1, "O": 2}
    assert Logic.parseFormula("CaMg(CO3)2") == {"Ca": 1, "Mg": 1, "C": 2, "O": 6}
    assert Logic.parseFormula("Ca(OH)2") == {"Ca": 1, "O": 2, "H": 2}
    assert Logic.parseFormula("Al2(SO4)3") == {"Al": 2, "S": 3, "O": 12}
    assert Logic.parseFormula(" H2 O ") == {"H": 2, "O": 1}


@pytest.mark.parametrize("text", ["", "Xx2", "Ca(OH", "CaOH)2", "si02", "Ca-O"])
def test_parse_formula_rejects_bad_text(text):
    with pytest.raises(ValueError):
        Logic.parseFormula(text)


def test_composition_and_zeff_match_the_reference_minerals():
    quartz = Logic.composition(Logic.parseFormula("SiO2"), 2.65)
    dolomite = Logic.composition(Logic.parseFormula("CaMg(CO3)2"), 2.85)
    calcite = Logic.composition(Logic.parseFormula("CaCO3"), 2.71)
    assert quartz["electronDensity"] == pytest.approx(1.323, abs=0.002)
    assert dolomite["electronDensity"] == pytest.approx(1.422, abs=0.003)
    assert calcite["electronDensity"] == pytest.approx(1.354, abs=0.003)
    assert Logic.effectiveZ(quartz, 2.94) == pytest.approx(11.6, abs=0.1)
    assert Logic.effectiveZ(dolomite, 2.94) == pytest.approx(13.0, abs=0.1)
    assert Logic.effectiveZ(calcite, 2.94) == pytest.approx(15.1, abs=0.1)


def syntheticStandards(beta=900.0, K=0.0035, n=3.1):
    """Standards whose a and c follow the model exactly, with the given calibration."""
    specs = [("SiO2", 2.65), ("CaCO3", 2.71), ("Al2O3", 3.95), ("MgO", 3.58)]
    compositions = [Logic.composition(Logic.parseFormula(f), rho) for f, rho in specs]
    c = np.array([beta * comp["electronDensity"] for comp in compositions])
    a = np.array([K * ci * np.sum(comp["fractions"] * comp["Z"] ** n) for ci, comp in zip(c, compositions)])
    return a, c, compositions


def test_calibration_recovers_beta_k_and_the_exponent_of_the_scan():
    for n in (2.94, 4.5):  # the steepness of a / c with the atomic number depends on the scan
        a, c, compositions = syntheticStandards(n=n)
        calibration = Logic.calibrate(a, c, compositions)
        assert calibration["beta"] == pytest.approx(900.0, rel=1e-6)
        assert calibration["n"] == pytest.approx(n, abs=1e-3) and calibration["fittedExponent"]
        assert calibration["K"] == pytest.approx(0.0035, rel=1e-2)
        for standard in calibration["standards"]:
            assert standard["Zeff"][0] == pytest.approx(standard["Zeff"][1], rel=1e-3)


def test_calibration_fixes_n_when_it_cannot_be_fitted_and_says_why():
    a, c, compositions = syntheticStandards(n=2.94)
    two = Logic.calibrate(a[:2], c[:2], compositions[:2])  # fitting n needs 3 standards
    assert two["n"] == 2.94 and not two["fittedExponent"] and "3 standards" in two["exponentNote"]
    assert two["K"] == pytest.approx(0.0035, rel=1e-2)
    steep = syntheticStandards(n=9.0)  # outside the range searched: the fit runs to its end and is not trusted
    limited = Logic.calibrate(*steep)
    assert limited["n"] == 2.94 and not limited["fittedExponent"] and "limit" in limited["exponentNote"]
    assert Logic.calibrate(a, c, compositions, fitExponent=False, exponent=3.1)["n"] == 3.1


def test_calibration_points_are_the_measured_against_the_known_values_of_each_standard():
    a, c, compositions = syntheticStandards(n=2.94)
    calibration = Logic.calibrate(a, c, compositions)
    points = calibration["points"]
    assert len(points) == 4 and calibration["n"] == pytest.approx(2.94, abs=1e-3)
    for point, comp, ci, ai in zip(points, compositions, c, a):
        assert point["c"] == pytest.approx(ci) and point["ratio"] == pytest.approx(ai / ci)
        assert point["electronDensity"] == pytest.approx(comp["electronDensity"])
        assert point["zeff"] == pytest.approx(Logic.effectiveZ(comp, calibration["n"]))
    # on the line of the calibration for data that follow the model; a standard off the data is off the line
    assert all(abs(p["c"] / (calibration["beta"] * p["electronDensity"]) - 1) < 1e-6 for p in points)


def test_calibration_residual_says_which_standard_is_off_the_calibration():
    a, c, compositions = syntheticStandards(n=3.4)
    good = Logic.calibrate(a, c, compositions)
    assert Logic.calibrationResidual(good)[0] < 1e-6
    bent = c.copy()
    bent[2] *= 1.25  # one standard whose c is 25 % off, as with a wrong density
    off = Logic.calibrate(a * (bent / c), bent, compositions)  # the same a / c, a different c
    distance, worst = Logic.calibrationResidual(off)
    assert worst == 2 and distance > 0.08


def test_calibration_needs_two_standards_with_positive_a_and_c():
    a, c, compositions = syntheticStandards(n=2.94)
    with pytest.raises(ValueError):
        Logic.calibrate(a[:1], c[:1], compositions[:1])
    with pytest.raises(ValueError):
        Logic.calibrate(-a, c, compositions)


def test_convert_inverts_the_calibration_and_handles_air():
    calibration = {"beta": 900.0, "K": 0.0035, "n": 3.0}
    electronDensity, zeff, density = Logic.convert(0.0035 * 900 * 1.3 * 12.0**3, 900 * 1.3, calibration, 0.5)
    assert electronDensity == pytest.approx(1.3) and zeff == pytest.approx(12.0) and density == pytest.approx(2.6)
    assert all(np.isnan(v) for v in Logic.convert(0.0, 5.0, calibration))
    assert all(np.isnan(v) for v in Logic.convert(1.0, -2.0, calibration))


def test_cluster_properties_use_the_ratio_of_the_means_and_report_a_bootstrap_spread():
    calibration = {"beta": 900.0, "K": 0.0035, "n": 3.0}
    rng = np.random.default_rng(7)
    c = rng.normal(1170.0, 15.0, (20, 50))
    a = 0.0035 * 1170.0 * 12.0**3 * rng.normal(1.0, 0.05, (20, 50))
    labels = np.ones((20, 50), dtype=np.uint8)
    labels[:, 25:] = 2
    result = Logic.clusterProperties(a, c, labels, 3, calibration)
    assert result[0]["values"][1] == pytest.approx(12.0, rel=0.02)
    assert result[0]["sd"][1] > 0 and result[0]["pixels"] == 500
    assert result[2]["pixels"] == 0 and np.isnan(result[2]["values"][0])  # an empty cluster


def test_standard_pixels_drops_the_border_unless_nothing_is_left():
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 4:16] = True
    inner = Logic.standardPixels(mask, 3)
    assert inner.sum() == 6 * 6 and not inner[4, 4]
    tiny = np.zeros((10, 10), dtype=bool)
    tiny[4:6, 4:6] = True
    assert (Logic.standardPixels(tiny, 3) == tiny).all()


BETA, K_SCALE, N_Z = 30.0, 2e-4, 3.0
STANDARD_SPECS = [("C2F4", 2.2), ("Al", 2.70), ("SiO2", 2.65)]  # Teflon, aluminum, quartz


def materialSpectrum(formula, density, axis, beta=BETA, k=K_SCALE, n=N_Z, b=-3.0):
    """Attenuation above air of a material whose a and c follow the model exactly, at each energy of `axis`."""
    composition = Logic.composition(Logic.parseFormula(formula), density)
    c = beta * composition["electronDensity"]
    a = k * c * np.sum(composition["fractions"] * composition["Z"] ** n)
    return a * (axis / 100.0) ** b + c


def standardsScene(noise=0.3):
    """Air, a rock block inside the SOI and, outside it, the three standards as rings and an irregular piece, plus a
    holder of another material (iron) around them. Returns array, SOI mask and the true mask of each standard."""
    axis = np.linspace(160.0, 20.0, 12)
    size = 120
    array = np.full((12, size, size), 1000.0)
    jj, ii = np.mgrid[:size, :size]
    radius = np.hypot(jj - 60, ii - 60)
    soi = radius < 24
    regions = [
        (radius >= 28) & (radius < 33),  # Teflon: a ring
        (jj > 100) & (ii > 85) & (ii < 105) & (radius > 40),  # aluminum: an irregular block, not a disc
        (radius >= 36) & (radius < 41),  # quartz: another ring
    ]
    holder = (radius >= 44) & (radius < 48)
    rng = np.random.default_rng(9)
    for (formula, density), region in zip(STANDARD_SPECS, regions):
        array[:, region] = (1000.0 + materialSpectrum(formula, density, axis))[:, None]
    array[:, holder] = (1000.0 + materialSpectrum("Fe", 7.87, axis))[:, None]
    array[:, soi] = (1000.0 + materialSpectrum("CaCO3", 2.71, axis))[:, None]
    material = array != 1000.0  # the air of the real scans is exactly constant, so it gets no noise
    array[material] += rng.normal(0, noise, array.shape)[material]
    return array, soi, regions, axis


def test_find_standards_by_clustering_whatever_their_shape():
    array, soi, regions, axis = standardsScene()
    compositions = [Logic.composition(Logic.parseFormula(f), r) for f, r in STANDARD_SPECS]
    found = Logic.findStandards(array, axis, np.arange(12), np.full(12, 1000.0), soi, -3.0, compositions)
    assert found["mismatch"] < 0.05
    assert len(found["standards"]) == 3 and found["labels"].max() == 3 + len(found["others"])
    for mask, region in zip(found["masks"], regions):
        assert (mask & region).sum() / region.sum() > 0.9  # the cluster covers the standard
        assert (mask & ~region).sum() / mask.sum() < 0.05  # and little else


def test_find_standards_reports_when_the_soi_leaves_nothing_to_find():
    array, soi, _, axis = standardsScene()
    compositions = [Logic.composition(Logic.parseFormula(f), r) for f, r in STANDARD_SPECS]
    with pytest.raises(ValueError):
        Logic.findStandards(array, axis, np.arange(12), np.full(12, 1000.0), np.ones_like(soi), -3.0, compositions)


def test_find_standards_with_a_confidence_limit_still_finds_them_and_leaves_pixels_out():
    array, soi, regions, axis = standardsScene(noise=1.0)
    compositions = [Logic.composition(Logic.parseFormula(f), r) for f, r in STANDARD_SPECS]
    args = (array, axis, np.arange(12), np.full(12, 1000.0), soi, -3.0, compositions)
    everything = Logic.findStandards(*args)
    sure = Logic.findStandards(*args, minProbability=0.99)
    for mask, region in zip(sure["masks"], regions):
        assert (mask & region).sum() / mask.sum() > 0.95
    assert np.count_nonzero(sure["labels"]) <= np.count_nonzero(everything["labels"])


def test_cluster_parameters_leaves_out_the_undecided_pixels_between_two_clusters():
    rng = np.random.default_rng(8)
    c = np.concatenate([rng.normal(10, 2.0, 1500), rng.normal(16, 2.0, 1500)]).reshape(50, 60)
    a = rng.normal(5.0, 0.5, (50, 60))
    valid = np.ones_like(c, dtype=bool)
    everything, _ = Logic.clusterParameters(c, a, valid, 2)
    labels, clusters = Logic.clusterParameters(c, a, valid, 2, minProbability=0.95)
    assert (everything > 0).all() and (labels == 0).sum() > 0
    undecided = c[labels == 0]
    assert abs(np.median(undecided) - 13.0) < 1.5  # they sit between the two blobs
    assert sum(cluster["count"] for cluster in clusters) == np.count_nonzero(labels)


def test_match_standard_clusters_picks_the_clusters_with_the_right_pattern():
    compositions = [Logic.composition(Logic.parseFormula(f), r) for f, r in STANDARD_SPECS]
    clusters = []
    for formula, density in [("Fe", 7.87), ("SiO2", 2.65), ("C2F4", 2.2), ("Al", 2.70)]:  # shuffled, with a decoy
        composition = Logic.composition(Logic.parseFormula(formula), density)
        c = BETA * composition["electronDensity"]
        a = K_SCALE * c * np.sum(composition["fractions"] * composition["Z"] ** DEFAULT_N)
        clusters.append({"mean": np.array([c, a]), "count": 500})
    chosen, mismatch = Logic.matchStandardClusters(clusters, compositions, 100)
    assert chosen == [2, 3, 1] and mismatch < 1e-6  # Teflon, aluminum, quartz
    with pytest.raises(ValueError):
        Logic.matchStandardClusters(clusters[:2], compositions, 100)


def test_clean_region_drops_small_scattered_pieces():
    mask = np.zeros((60, 60), dtype=bool)
    mask[10:30, 10:30] = True
    mask[50, 50] = True
    cleaned = Logic.cleanRegion(mask)
    assert cleaned[15, 15] and not cleaned[50, 50]


def test_order_by_attenuation_uses_the_lowest_energy_of_the_selection():
    array = np.stack([np.full((6, 6), 100.0), np.full((6, 6), 100.0)])
    left = np.zeros((6, 6), dtype=bool)
    left[:, :3] = True
    array[0, :, :3], array[0, :, 3:] = 300.0, 200.0  # first slice, highest energy
    array[1, :, :3], array[1, :, 3:] = 150.0, 400.0  # second slice, lowest energy
    masks = [left, ~left]
    assert Logic.orderByAttenuation(array, np.array([160.0, 20.0]), np.array([0, 1]), np.full(2, 100.0), masks) == [
        0,
        1,
    ]
    assert Logic.orderByAttenuation(array, np.array([160.0, 20.0]), np.array([0]), np.full(2, 100.0), masks) == [1, 0]


def test_classify_by_gaussians_follows_the_edited_model_and_the_confidence_limit():
    c = np.array([[0.0, 10.0, 20.0]])
    a = np.zeros((1, 3))
    valid = np.ones((1, 3), dtype=bool)
    model = [
        {"mean": np.array([0.0, 0.0]), "cov": np.eye(2) * 4.0, "weight": 0.5},
        {"mean": np.array([20.0, 0.0]), "cov": np.eye(2) * 4.0, "weight": 0.5},
    ]
    labels, counts = Logic.classifyByGaussians(c, a, valid, model)
    assert labels[0, 0] == 1 and labels[0, 2] == 2 and counts[0] + counts[1] == 3
    # the pixel in the middle belongs to neither blob: with a confidence limit it is the undecided one
    assert Logic.classifyByGaussians(c, a, valid, model, minProbability=0.9)[0][0, 1] == 0
    model[0]["mean"] = np.array([10.0, 0.0])  # drag the first center onto the middle pixel
    assert Logic.classifyByGaussians(c, a, valid, model)[0][0, 1] == 1
    model[1]["cov"] = np.eye(2) * 400.0  # and widen the second one so it takes over
    assert Logic.classifyByGaussians(c, a, valid, model)[0][0, 2] == 2


def test_gaussian_shape_and_covariance_are_inverse_and_rotate_the_ellipse():
    shape = (np.deg2rad(30.0), 3.0, 1.0)
    cov = Logic.gaussianCov(*shape)
    assert np.allclose(np.linalg.eigvalsh(cov), [1.0, 9.0])
    angle, major, minor = Logic.gaussianShape(cov)
    assert major == pytest.approx(3.0) and minor == pytest.approx(1.0)
    assert np.cos(angle - np.deg2rad(30.0)) ** 2 == pytest.approx(1.0)  # the same axis, up to the sign


def standardsAtExponent(b, noise=0.5, seed=3):
    """Pixels of three standards (flattened into one 3D array) whose spectra follow the power law with exponent b."""
    axis = np.linspace(160.0, 20.0, 40)
    rng = np.random.default_rng(seed)
    array = np.full((40, 1, 300), 1000.0)
    masks = []
    for n, (formula, density) in enumerate(STANDARD_SPECS):
        array[:, 0, n * 100 : (n + 1) * 100] = (1000.0 + materialSpectrum(formula, density, axis, b=b))[:, None]
        mask = np.zeros((1, 300), dtype=bool)
        mask[0, n * 100 : (n + 1) * 100] = True
        masks.append(mask)
    array[:, 0, :] += rng.normal(0, noise, (40, 300))
    return array, axis, masks


@pytest.mark.parametrize("trueExponent", [-2.2, -2.9, -3.6])
def test_estimate_exponent_recovers_the_true_one_from_the_standards(trueExponent):
    array, axis, masks = standardsAtExponent(trueExponent)
    result = Logic.estimateExponent(array, axis, np.arange(40), np.full(40, 1000.0), masks)
    assert result["best"] == pytest.approx(trueExponent, abs=0.08)
    assert not result["atEdge"] and result["ratio"] > 1.05
    low, high = result["interval"]  # the interval is on the grid, the best value is refined between its points
    assert low - 0.05 <= result["best"] <= high + 0.05


def test_estimate_exponent_flags_a_best_value_at_the_edge_of_the_range():
    array, axis, masks = standardsAtExponent(-8.0)  # outside the range that is searched
    result = Logic.estimateExponent(array, axis, np.arange(40), np.full(40, 1000.0), masks)
    assert result["atEdge"] and result["best"] == pytest.approx(-6.0)
    assert "end of the range" in Logic.describeExponentEstimate(-3.5, result["best"], result)


def test_estimate_exponent_says_when_the_standards_do_not_pin_it_down():
    axis = np.linspace(160.0, 20.0, 40)
    array = np.full((40, 1, 100), 1000.0)
    array[:, 0, :] += 30.0 + np.random.default_rng(1).normal(0, 2.0, (40, 100))  # no energy dependence at all
    mask = np.ones((1, 100), dtype=bool)
    result = Logic.estimateExponent(array, axis, np.arange(40), np.full(40, 1000.0), [mask])
    assert result["ratio"] < 1.05
    assert "poorly defined" in Logic.describeExponentEstimate(-3.5, result["best"], result)


def test_estimate_exponent_uses_only_the_selected_energies():
    array, axis, masks = standardsAtExponent(-3.0)
    array[5:10] += 800.0  # saturated slices that the selection leaves out
    selection = np.array([k for k in range(40) if not 5 <= k < 10])
    result = Logic.estimateExponent(array, axis, selection, np.full(40, 1000.0), masks)
    assert result["best"] == pytest.approx(-3.0, abs=0.08)


def test_segment_gaussians_take_the_mean_covariance_and_share_of_each_segment():
    rng = np.random.default_rng(11)
    c = np.concatenate([rng.normal(10, 1.0, 600), rng.normal(40, 3.0, 400)]).reshape(25, 40)
    a = np.concatenate([rng.normal(2, 0.2, 600), rng.normal(9, 0.6, 400)]).reshape(25, 40)
    valid = np.ones((25, 40), dtype=bool)
    first = np.zeros((25, 40), dtype=bool)
    first.flat[:600] = True
    second = np.zeros((25, 40), dtype=bool)
    second.flat[600:] = True
    tiny = np.zeros((25, 40), dtype=bool)
    tiny[0, 0] = True  # too few pixels to be a Gaussian
    clusters, labels = Logic.segmentGaussians(c, a, valid, [first, tiny, second])
    assert [cluster["index"] for cluster in clusters] == [0, 2]  # the tiny segment is skipped
    assert clusters[0]["mean"] == pytest.approx([10, 2], abs=0.15) and clusters[1]["mean"] == pytest.approx(
        [40, 9], abs=0.4
    )
    assert clusters[0]["weight"] == pytest.approx(0.6) and clusters[1]["cov"][0, 0] > clusters[0]["cov"][0, 0]
    assert (labels.ravel()[:600] == 1).all() and (labels.ravel()[600:] == 2).all()
    # a segment is only taken where the fit is valid
    valid[:, :20] = False
    assert Logic.segmentGaussians(c, a, valid, [first, second])[0][0]["count"] < 600


def test_suggest_mineral_names_a_class_only_when_it_is_close_enough():
    n = 2.94
    assert Logic.suggestMineral(11.6, 2.65, n)[0] == "Quartz"
    assert Logic.suggestMineral(13.0, 2.85, n)[0] == "Dolomite"
    assert Logic.suggestMineral(21.5, 5.0, n)[0] == "Pyrite"


def test_suggest_mineral_uses_the_density_to_tell_apart_minerals_with_the_same_zeff():
    n = 2.94
    assert Logic.suggestMineral(15.1, 2.71, n)[0] == "Calcite"
    assert Logic.suggestMineral(15.1, 2.93, n)[0] == "Aragonite"
    assert Logic.suggestMineral(15.2, 2.97, n)[0] == "Anhydrite"
    assert Logic.suggestMineral(15.1, float("nan"), n)[0] == "Calcite"  # no density: the closest Zeff
    name, zDifference, densityDifference = Logic.suggestMineral(15.6, 1.98, n)
    assert name and densityDifference < -0.2  # a porous calcite: right Zeff, far lower density
    assert Logic.suggestMineral(40.0, 3.0, n)[0] == ""  # nothing close enough


def test_a_class_without_attenuation_or_with_a_very_low_density_is_suggested_as_pores():
    from SpectralProfile.SpectralProfile import MINERAL_CHOICES, PORES

    n = 2.94
    assert Logic.suggestMineral(float("nan"), float("nan"), n)[0] == PORES  # a or c not positive: no Zeff
    assert Logic.suggestMineral(float("nan"), 3.0, n)[0] == PORES
    assert Logic.suggestMineral(15.1, 0.3, n)[0] == PORES  # a mineral Zeff but almost no mass
    assert Logic.suggestMineral(15.1, 2.71, n)[0] == "Calcite"
    assert MINERAL_CHOICES[0] == PORES and MINERAL_CHOICES[-1] == "-" and "Quartz" in MINERAL_CHOICES


def test_every_reference_mineral_has_a_formula_the_module_can_read():
    from SpectralProfile.SpectralProfile import REFERENCE_MINERALS

    for name, (formula, density) in REFERENCE_MINERALS.items():
        composition = Logic.composition(Logic.parseFormula(formula), density)
        assert composition["electronDensity"] > 0 and Logic.effectiveZ(composition, 2.94) > 1, name


def test_unique_segment_names_number_only_the_repeated_ones():
    assert Logic.uniqueSegmentNames(["Calcite", "Quartz", "Calcite"]) == ["Calcite (1)", "Quartz", "Calcite (2)"]
    assert Logic.uniqueSegmentNames(["Quartz"]) == ["Quartz"] and Logic.uniqueSegmentNames([]) == []


# ----- texts of the panel -----
def test_cluster_text_is_a_table_with_the_share_of_each_cluster_and_the_undecided_pixels():
    clusters = [{"mean": np.array([10.0, 1.0]), "count": 25}, {"mean": np.array([40.0, 5.0]), "count": 75}]
    text = Logic.describeClusters(clusters, 90, 12.3)
    assert "<table" in text and "25.0 %" in text and "75.0 %" in text and "Cluster 2" in text
    assert "12.3 %" in text and "undecided" in text
    assert "undecided" not in Logic.describeClusters(clusters, 0, 0.0)


def test_stability_text_colors_the_agreement_by_level():
    result = {"overall": 0.9, "categories": {"Another random start": 0.99, "Exponent": 0.5}, "perCluster": [0.99, 0.5]}
    text = Logic.describeStability(result)
    assert "99.0 %" in text and "50.0 %" in text
    assert "rgb(46,160,67)" in text and "rgb(214,39,40)" in text and "rgb(230,140,30)" in text


def test_calibration_text_shows_the_two_constants_and_the_warnings():
    a, c, compositions = syntheticStandards(n=2.94)
    calibration = Logic.calibrate(a, c, compositions)
    text = Logic.describeCalibration(calibration)
    assert "beta" in text and "K" in text and "900" in text and "n = " in text and "<table" not in text
    warned = Logic.describeCalibration(calibration, "poor match", "a note")
    assert "poor match" in warned and "rgb(214,39,40)" in warned and "a note" in warned


# ----- stability -----
def test_match_clusters_undoes_a_permutation_of_the_labels():
    base = np.array([[1, 1, 2, 2], [3, 3, 0, 1]], dtype=np.uint8)
    permutation = np.array([0, 3, 1, 2], dtype=np.uint8)  # base label k becomes permutation[k]
    other = permutation[base]
    assert (Logic.matchClusters(base, other, 3) == base).all()


def test_stability_of_well_separated_clusters_is_high_and_the_map_covers_the_analysis():
    array, _, _ = blobsVolume(noise=0.5)
    selection = np.arange(len(AXIS))
    background = np.full(len(AXIS), 1000.0)
    result = Logic.clusterStability(array, AXIS, background, None, -3.0, selection, 3)
    assert result["overall"] > 0.95
    assert len(result["perCluster"]) == 3 and min(result["perCluster"]) > 0.9
    assert result["map"].shape == (30, 60) and result["map"].min() >= 0 and result["map"].max() <= 100
    assert len(result["categories"]) == 3


def test_stability_of_overlapping_clusters_is_lower():
    rng = np.random.default_rng(5)
    a = rng.normal(5.0, 1.5, (30, 60))  # a single cloud forced into 3 clusters
    c = rng.normal(30.0, 8.0, (30, 60))
    array = powerLawVolume(a, c, noise=0.5)
    selection = np.arange(len(AXIS))
    background = np.full(len(AXIS), 1000.0)
    split = Logic.clusterStability(array, AXIS, background, None, -3.0, selection, 3)
    clean, _, _ = blobsVolume(noise=0.5)
    separated = Logic.clusterStability(clean, AXIS, background, None, -3.0, selection, 3)
    assert split["overall"] < separated["overall"]


# ----- clustering methods, kept Gaussians and properties table -----
@pytest.mark.parametrize("method", ["gmm", "kmeans", "ward", "average", "complete"])
def test_every_clustering_method_separates_blobs_into_ordered_gaussians(method):
    rng = np.random.default_rng(1)
    c = np.concatenate([rng.normal(10, 1, 500), rng.normal(40, 1, 500)]).reshape(20, 50)
    a = np.concatenate([rng.normal(2, 0.3, 500), rng.normal(8, 0.3, 500)]).reshape(20, 50)
    valid = np.ones_like(c, dtype=bool)
    labels, clusters = Logic.clusterParameters(c, a, valid, 2, method=method)
    assert len(clusters) == 2 and clusters[0]["mean"][0] < clusters[1]["mean"][0]
    assert (labels.ravel()[:500] == 1).all() and (labels.ravel()[500:] == 2).all()
    assert clusters[0]["mean"][0] == pytest.approx(10, abs=0.3) and clusters[1]["cov"].shape == (2, 2)


def test_kept_gaussians_come_back_as_they_were_only_for_the_same_fit_and_segments():
    clusters = [
        {
            "segmentId": "class1",
            "mean": np.array([10.0, 2.0]),
            "cov": np.array([[1.0, 0.2], [0.2, 0.5]]),
            "weight": 0.4,
        },
        {"segmentId": "class2", "mean": np.array([40.0, 8.0]), "cov": np.eye(2), "weight": 0.6},
    ]
    fit = {"exponent": -3.0, "selection": [0, 1, 2], "axis": [160.0, 20.0]}
    text = Logic.encodeGaussians(clusters, fit)
    restored = Logic.decodeGaussians(text, fit, ["class2", "class1"])
    assert [item["segmentId"] for item in restored] == ["class2", "class1"]
    assert np.allclose(restored[1]["cov"], clusters[0]["cov"]) and restored[0]["weight"] == 0.6
    assert Logic.decodeGaussians(text, dict(fit, exponent=-3.5), ["class1", "class2"]) is None
    assert Logic.decodeGaussians(text, fit, ["class1", "other"]) is None
    assert Logic.decodeGaussians("", fit, ["class1"]) is None


def test_properties_table_has_a_row_per_segment_with_the_shares_and_the_mineral():
    properties = [
        {"pixels": 30, "values": (0.5, 12.0, 1.1), "sd": (0.01, 0.1, 0.02)},
        {"pixels": 70, "values": (1.3, 15.0, 2.6), "sd": (0.02, 0.2, 0.03)},
    ]
    header, rows = Logic.propertiesTable(["A", "B"], ["Pores", ""], properties)
    assert header[0] == "Segment" and header[-1] == "Mineral" and len(header) == len(rows[0])
    assert rows[1][0] == "B" and rows[0][1] == pytest.approx(30.0) and rows[1][4] == 15.0 and rows[0][-1] == "Pores"


def test_default_output_name_records_the_clustering_method():
    assert Logic.defaultOutputName("microtom", -3.0, 4, "ward") == "microtom_spectral_b3_classes4_ward"


# ----- fewer energies with the Gaussians of the full fit -----
def fullFit(noise):
    array, a, c = blobsVolume(noise=noise)
    full = np.arange(len(AXIS))
    background = np.full(len(AXIS), 1000.0)
    fitted_a, fitted_c, valid = Logic.powerLawFit(array, AXIS, -3.0, full, background)
    model = Logic.fitClusters(fitted_c, fitted_a, valid, 3)
    reference, _ = Logic.assignClusters(model)
    return array, full, background, model["clusters"], reference


def dualVolumes(shape=(6, 30, 60), noise=0.3, seed=2, dtype=np.uint16):
    """Two 3D volumes (one per energy) of three materials in bands along x, each following the power law."""
    a = np.zeros(shape)
    c = np.zeros(shape)
    for n, (aa, cc) in enumerate([(1.0, 5.0), (5.0, 30.0), (12.0, 55.0)]):
        a[..., n * 20 : (n + 1) * 20] = aa
        c[..., n * 20 : (n + 1) * 20] = cc
    rng = np.random.default_rng(seed)
    volumes = [(1000.0 + a * (AXIS[k] / 100.0) ** -3.0 + c + rng.normal(0, noise, shape)).astype(dtype) for k in PAIR]
    return volumes, a, c


def dualClusters():
    """Gaussians of the three materials, fitted on the 2D multi-energy version of the same bands."""
    array, _, _ = blobsVolume(noise=0.3)
    fitted_a, fitted_c, valid = Logic.powerLawFit(array, AXIS, -3.0, np.arange(len(AXIS)), np.full(len(AXIS), 1000.0))
    return Logic.fitClusters(fitted_c, fitted_a, valid, 3)["clusters"]


def test_block_voxels_shrinks_with_the_clusters_and_has_a_floor():
    assert Logic.blockVoxels(8, 1e9) < Logic.blockVoxels(2, 1e9)
    assert Logic.blockVoxels(4, 1) == 1024


def test_parse_gaussians_reads_what_encode_wrote_and_rejects_the_rest():
    clusters = dualClusters()
    for n, cluster in enumerate(clusters):
        cluster["segmentId"] = f"class{n + 1}"
    fit = {"exponent": -3.0, "selection": [0, 1, 2], "axis": [160.0, 20.0]}
    parsed = Logic.parseGaussians(Logic.encodeGaussians(clusters, fit))
    assert parsed is not None and parsed[0] == fit
    assert [item["segmentId"] for item in parsed[1]] == ["class1", "class2", "class3"]
    assert parsed[1][1]["cov"] == pytest.approx(clusters[1]["cov"])
    assert Logic.parseGaussians("") is None and Logic.parseGaussians("{}") is None


def test_estimate_dual_memory_counts_the_labels_and_one_block_only():
    small = Logic.estimateDualMemory((1000, 1000, 1000), 4, 1 * 2**30)
    assert 1e9 < small < 1e9 + 1.2 * 2**30
    assert Logic.estimateDualMemory((10, 10, 10), 4, 1 * 2**30) < 1000 * 400


# ----- gray scale of volumes reconstructed on their own scale -----
def rescaled(volumes, airs, scales):
    """The volumes as a reconstruction with another gray scale would store them: air + scale * attenuation."""
    return [air + scale * (volume.astype(float) - 1000.0) for volume, air, scale in zip(volumes, airs, scales)]


def textureVolume(shape=(40, 300, 300), seed=3):
    """A volume of blobs that vary smoothly along z, in the pixels of the 'reference' scan."""
    from scipy.ndimage import gaussian_filter

    return gaussian_filter(np.random.default_rng(seed).normal(size=shape), 5).astype(np.float32)


def dualOfTexture(texture, zStart, ySize, xSize, scale, offset, gain=100.0, shift=3000.0):
    """The volume a second scan of the texture would give: `scale` voxels per pixel, starting at `offset` pixels of the
    reference, on its own gray scale. One slice per slice of the texture from zStart."""
    from scipy.ndimage import map_coordinates

    rows, columns = np.mgrid[:ySize, :xSize]
    coordinates = [rows / scale + offset[0], columns / scale + offset[1]]
    return np.stack(
        [shift + gain * map_coordinates(texture[z], coordinates, order=1) for z in range(zStart, texture.shape[0])]
    )


def test_normalized_cross_correlation_finds_the_window_whatever_the_gain_and_offset():
    image = textureVolume((1, 120, 120))[0]
    window = 5.0 * image[30:70, 40:90] + 100.0
    score = Logic.normalizedCrossCorrelation(image, window)
    assert score.shape == (120 - 40 + 1, 120 - 50 + 1)
    assert np.unravel_index(score.argmax(), score.shape) == (30, 40) and score.max() == pytest.approx(1.0, abs=1e-6)


def test_register_slice_finds_the_slice_and_where_the_volume_starts():
    texture = textureVolume()
    scale, offset = 2.25, (40.0, 55.0)
    volume = dualOfTexture(texture, 0, 400, 400, scale, offset)  # 178 x 178 pixels of the reference, inside it
    for z in (10, 23):
        found = Logic.registerSlice(texture[z], 0.072, volume, 0.032)
        assert found["scale"] == pytest.approx(scale)
        assert found["z"] == z  # the slice of the texture is slice z of the volume
        assert found["offset"] == pytest.approx(offset, abs=1.0)
        assert found["score"] > 0.9
    far = Logic.registerSlice(texture[23], 0.072, volume, 0.032, zRange=(0, 5))
    assert far["score"] < Logic.registerSlice(texture[23], 0.072, volume, 0.032)["score"]


def test_register_slice_can_be_stopped_and_rejects_an_empty_range():
    texture = textureVolume((12, 200, 200))
    volume = dualOfTexture(texture, 0, 150, 150, 2.25, (30.0, 30.0))
    assert Logic.registerSlice(texture[5], 0.072, volume, 0.032, progress=lambda fraction: False) is None
    with pytest.raises(ValueError):
        Logic.registerSlice(texture[5], 0.072, volume, 0.032, zRange=(6, 6))


def test_map_to_volume_samples_the_reference_and_leaves_zero_outside():
    image = np.arange(100, dtype=np.uint8).reshape(10, 10)
    mapped = Logic.mapToVolume(image, (20, 20), 2.0, (1.0, 2.0))  # voxel (y, x) is at pixel (y / 2 + 1, x / 2 + 2)
    assert mapped[0, 0] == image[1, 2] and mapped[10, 4] == image[6, 4]
    assert mapped[19, 19] == image[10 if False else 9, 9] or mapped[19, 19] == 0
    outside = Logic.mapToVolume(image, (30, 30), 2.0, (6.0, 6.0))  # most of it is beyond the reference
    assert outside[29, 29] == 0 and outside[0, 0] == image[6, 6]


def grayVolumes(noise=0.05, seed=5):
    """Two volumes where three materials (bands along x) have their own pair of gray values."""
    rng = np.random.default_rng(seed)
    base = np.zeros((10, 20, 60), dtype=np.float32)
    levels = [(1000.0, 1500.0), (2000.0, 2600.0), (3000.0, 3300.0)]
    volumes = [base.copy(), base.copy()]
    for n, (first, second) in enumerate(levels):
        volumes[0][..., n * 20 : (n + 1) * 20] = first
        volumes[1][..., n * 20 : (n + 1) * 20] = second
    return [v + rng.normal(0, noise * 1000.0, v.shape).astype(np.float32) for v in volumes]


def grayClusters(volumes):
    samples = [np.column_stack([v[..., n * 20 : (n + 1) * 20].ravel() for v in volumes]) for n in range(3)]
    return Logic.fitGrayGaussians(samples)[0]


def test_fit_gray_gaussians_keeps_the_classes_with_enough_voxels_and_weights_them_by_share():
    rng = np.random.default_rng(0)
    samples = [
        rng.normal([100, 200], 5, (600, 2)),
        rng.normal([300, 100], 5, (150, 2)),
        rng.normal([500, 500], 5, (200, 2)),
    ]
    clusters, kept = Logic.fitGrayGaussians(samples)
    assert kept == [0, 2] and len(clusters) == 2
    assert clusters[0]["mean"] == pytest.approx([100, 200], abs=1) and clusters[0]["weight"] == pytest.approx(600 / 800)
    assert (np.linalg.eigvalsh(clusters[0]["cov"]) > 0).all()


def test_sample_class_voxels_reads_the_voxels_of_each_class_of_the_reference():
    volumes = grayVolumes()
    classes = np.zeros((40, 100), dtype=np.uint8)
    classes[:, 0:20], classes[:, 20:40] = 1, 2  # reference pixels over the first two bands (1 pixel = 1 voxel)
    first, second, third = Logic.sampleClassVoxels(volumes, 5, classes, 1.0, (0.0, 0.0), 3, smoothing=0.0, slices=1)
    assert len(third) == 0  # no reference pixel of the third class
    assert first.shape[1] == 2 and len(first) == 3 * 20 * 20  # slices 4..6 of 20 x 20 voxels
    assert first[:, 0].mean() == pytest.approx(1000.0, abs=20) and second[:, 1].mean() == pytest.approx(2600.0, abs=20)


def test_dual_histogram_counts_the_voxels_of_the_region_and_the_slices_and_follows_the_classes():
    volumes = grayVolumes(noise=0.01)  # three bands along x
    region = np.zeros(volumes[0].shape[1:], dtype=bool)
    region[:, 0:40] = True  # the first two bands
    result = Logic.dualHistogram(volumes, region, (2, 8), smoothing=0.0, bins=64)
    assert result["slices"] == 6 and result["voxels"] == pytest.approx(6 * 20 * 40, rel=0.03)  # the tails are cut
    counts = result["counts"]
    assert counts.shape == (64, 64)
    peaks = np.argwhere(counts > 0.2 * counts.max())
    first = result["x"][0] + (peaks[:, 0] + 0.5) * (result["x"][1] - result["x"][0]) / 64
    assert first.min() < 1100 and first.max() > 1900 and first.max() < 2100  # the bands of 1000 and 2000, not 3000
    assert Logic.dualHistogram(volumes, None, None, 0.0, bins=16, maxSlices=3)["slices"] == 3
    with pytest.raises(ValueError):
        Logic.dualHistogram(volumes, region, (5, 5))
    with pytest.raises(ValueError):
        Logic.dualHistogram(volumes, np.zeros_like(region))


def test_a_3d_region_limits_the_classification_and_the_histogram_to_its_voxels():
    volumes = grayVolumes()
    clusters = grayClusters(volumes)
    region = np.zeros(volumes[0].shape, dtype=bool)
    region[2:6, :, 0:40] = True  # slices 2 to 5 of the first two bands only
    labels = np.zeros(volumes[0].shape, dtype=np.uint8)
    result = Logic.classifyGrayVolumes(volumes, clusters, labels, 0.0, 0.0, memoryBytes=2**30, region=region)
    assert result["valid"] == int(region.sum()) and ((labels > 0) == region).all()
    histogram = Logic.dualHistogram(volumes, region, None, 0.0, bins=32)
    assert histogram["slices"] == 4 and histogram["voxels"] == pytest.approx(region.sum(), rel=0.05)
    with pytest.raises(ValueError):
        Logic.dualHistogram(volumes, region, (7, 9), 0.0)  # no region in these slices


def test_properties_table_counts_the_voxels_and_the_dual_classes_show_the_density_and_zeff():
    properties = [
        {"pixels": 30, "values": (0.5, 12.0, 2.6), "sd": (0.01, 0.2, 0.05)},
        {"pixels": 70, "values": (0.6, 13.5, 2.9), "sd": (0.01, 0.3, 0.05)},
    ]
    header, rows = Logic.propertiesTable(["A", "B"], ["Quartz", "Dolomite"], properties, unit="Voxels")
    assert header[1] == "Voxels (%)" and rows[0][1] == pytest.approx(30.0) and rows[1][-1] == "Dolomite"
    clusters = [{"name": "A", "color": (255, 0, 0), "count": 30}, {"name": "B", "color": (0, 255, 0), "count": 70}]
    text = Logic.describeDualClasses(clusters, 0, 0.0, properties, ["Quartz", ""], [("C", (0, 0, 255))])
    assert "30.0 %" in text and "13.50" in text and "Quartz" in text and "not learned" in text
    assert "Mean gray" in Logic.describeDualClasses(
        [dict(c, samples=5, mean=[1.0, 2.0]) for c in clusters], 0, 0.0
    )  # no calibration: the gray values


def test_density_calibration_of_the_volumes_gives_back_the_electron_density_and_zeff():
    n = 3.5
    truth = [(0.7, 8.0), (1.3, 13.0), (1.1, 11.0)]  # electron density and Zeff of the standards
    air, scale, ratio = [100.0, 300.0], [50.0, 80.0], [0.02, 0.008]

    def gray(k, rho, z):
        return air[k] + scale[k] * rho * (1 + ratio[k] * z**n)

    fits = [
        Logic.fitDensityCalibration(
            [gray(k, rho, z) for rho, z in truth], air[k], [r for r, _ in truth], [z for _, z in truth], n
        )
        for k in range(2)
    ]
    for k, fit in enumerate(fits):
        assert fit["air"] == pytest.approx(air[k]) and fit["scale"] == pytest.approx(scale[k])
        assert fit["ratio"] == pytest.approx(ratio[k]) and fit["relative"] < 1e-9 and fit["freedom"] == 1
    material = [(1.2, 12.0), (0.9, 9.5), (0.0, 1.0)]  # the last one is air
    values = np.array([[gray(0, rho, z), gray(1, rho, z)] for rho, z in material])
    result = Logic.densityAndZeff(values, fits, n)
    assert result[0, :2] == pytest.approx([1.2, 12.0], rel=1e-6) and result[0, 2] == pytest.approx(1.2 / 0.4995)
    assert result[1, :2] == pytest.approx([0.9, 9.5], rel=1e-6)
    assert np.isnan(result[2]).all()  # nothing above the air
    with pytest.raises(ValueError):
        Logic.fitDensityCalibration([1.0, 2.0], None, [0.5, 1.0], [8.0, 13.0], n)  # two references fit nothing


def test_reference_masks_are_cleaned_by_their_gray_values():
    rng = np.random.default_rng(2)
    gray = np.stack([np.full((80, 80), 5000.0), np.full((80, 80), 7000.0)])
    gray[:, 10:30, 10:60] = [[[8000.0]], [[11000.0]]]  # a ring-like standard
    gray += rng.normal(0, 20, gray.shape)
    carried = np.zeros((80, 80), dtype=bool)
    carried[8:32, 8:62] = True  # the mask carried over is a little larger: it holds the neighbour's pixels
    refined = Logic.refineReferenceMask(gray, carried)
    assert refined[12:28, 12:58].all() and not refined[:9].any() and not refined[:, :9].any()
    assert not Logic.refineReferenceMask(gray, np.zeros((80, 80), dtype=bool)).any()


def caVolumes(noise=0.0, seed=7):
    """Two volumes of three bands whose materials have the (c, a) of CA_MATERIALS, with their own air and scale."""
    rng = np.random.default_rng(seed)
    energies, exponent, airs, scales = [60.0, 80.0], -3.0, [100.0, 200.0], [10.0, 20.0]
    volumes = [np.zeros((8, 10, 60), dtype=np.float32) for _ in energies]
    for n, (c, a) in enumerate(CA_MATERIALS):
        for k, energy in enumerate(energies):
            volumes[k][..., n * 20 : (n + 1) * 20] = airs[k] + scales[k] * (a * (energy / 100.0) ** exponent + c)
    volumes = [v + rng.normal(0, noise, v.shape).astype(np.float32) for v in volumes]
    return volumes, energies, airs, scales, exponent


CA_MATERIALS = [(10.0, 0.5), (30.0, 3.0), (50.0, 8.0)]


def caClusters():
    return [
        {"mean": np.array(m), "cov": np.diag([4.0, 0.25]), "weight": 1 / 3, "name": f"M{n}"}
        for n, m in enumerate(CA_MATERIALS)
    ]


def test_the_density_plane_and_its_histogram_put_the_materials_at_their_density_and_photoelectric_term():
    n = 3.0
    air, scale, ratio = [100.0, 300.0], [50.0, 80.0], [0.02, 0.008]
    fits = [{"air": air[k], "scale": scale[k], "ratio": ratio[k]} for k in range(2)]
    materials = [(0.7, 8.0), (1.3, 13.0)]  # electron density and Zeff
    volumes = [np.zeros((6, 20, 40), dtype=np.float32) for _ in range(2)]
    for m, (rho, z) in enumerate(materials):
        for k in range(2):
            volumes[k][..., m * 20 : (m + 1) * 20] = air[k] + scale[k] * rho * (1 + ratio[k] * z**n)
    x, y = Logic.densityPlane([volumes[0][0, 0, [0, 39]], volumes[1][0, 0, [0, 39]]], fits)
    assert x == pytest.approx([r for r, _ in materials]) and y == pytest.approx([r * z**n for r, z in materials])
    result = Logic.dualHistogram(
        volumes, None, None, 0.0, bins=40, convert=lambda values: Logic.densityPlane(values, fits)
    )
    for rho, z in materials:
        cx = int((rho - result["x"][0]) / (result["x"][1] - result["x"][0]) * 40)
        cy = int((rho * z**n - result["y"][0]) / (result["y"][1] - result["y"][0]) * 40)
        assert result["counts"][cx, cy] > 0.4 * result["counts"].max()
    with pytest.raises(ValueError):
        Logic.densityPlane(
            [volumes[0][0, 0], volumes[1][0, 0]], [fits[0], {"air": 300.0, "scale": 80.0, "ratio": fits[0]["ratio"]}]
        )  # the two volumes behave as the same energy


def sceneOutsideTheSoi(seed=4):
    """Two volumes' slice: a round sample, and outside it the air, three standards and a holder, as blocks."""
    rng = np.random.default_rng(seed)
    n, airs, scales, ratios = 2.94, [100.0, 300.0], [5000.0, 8000.0], [0.001, 0.0004]
    standards = [(0.7, 8.4), (1.1, 11.6), (1.3, 13.0)]  # electron density and Zeff, from the least attenuating
    rho, zeff = np.zeros((120, 120)), np.zeros((120, 120))
    blocks = {
        "air": (slice(5, 25), slice(5, 35)),
        "s0": (slice(5, 25), slice(45, 75)),
        "s1": (slice(5, 25), slice(85, 115)),
        "s2": (slice(95, 115), slice(5, 35)),
        "holder": (slice(95, 115), slice(85, 115)),
    }
    for name, values in {"s0": standards[0], "s1": standards[1], "s2": standards[2], "holder": (0.9, 6.0)}.items():
        rho[blocks[name]], zeff[blocks[name]] = values
    yy, xx = np.mgrid[:120, :120]
    sample = np.hypot(yy - 60, xx - 60) < 25
    rho[sample], zeff[sample] = 1.3, 11.0
    gray = np.stack([airs[k] + scales[k] * rho * (1 + ratios[k] * zeff**n) for k in range(2)])
    blocks["air"] = (rho == 0) & ~sample  # the whole background is air
    return gray + rng.normal(0, 8.0, gray.shape), sample, blocks, standards, n


def test_the_references_are_found_among_the_uniform_regions_outside_the_sample():
    gray, sample, blocks, standards, n = sceneOutsideTheSoi()
    found = Logic.findDualReferences(gray, ~sample, standards, n)
    assert found["cost"] < 0.02
    for name, mask in zip(("s0", "s1", "s2"), found["masks"]):  # in order of attenuation
        truth = np.zeros_like(sample)
        truth[blocks[name]] = True
        assert (mask & truth).sum() > 0.8 * truth.sum() and not (mask & ~truth).any()
    air = blocks["air"]
    assert (found["air"] & air).sum() > 0.8 * air.sum() and not (found["air"] & ~air).any()
    with pytest.raises(ValueError):
        Logic.findDualReferences(gray, np.zeros_like(sample), standards, n)  # nothing outside
    with pytest.raises(ValueError):  # the standards are not those of these regions
        Logic.findDualReferences(gray, ~sample, [(0.7, 8.4), (1.4, 10.0), (0.8, 13.0)], n)


def test_cluster_gray_volumes_groups_the_voxels_of_the_region_by_their_gray_from_dark_to_bright():
    volumes = grayVolumes(noise=0.02)  # three bands along x
    region = np.zeros(volumes[0].shape, dtype=bool)
    region[2:8, :, :] = True  # a 3D region: slices 2 to 7
    clusters, voxels = Logic.clusterGrayVolumes(volumes, region, 3, maxSamples=20_000)
    assert [round(c["mean"][0] / 100) for c in clusters] == [10, 20, 30]  # the bands of 1000, 2000 and 3000
    assert clusters[0]["weight"] == pytest.approx(1 / 3, abs=0.05) and len(voxels) == 3
    assert all(len(v) > 1000 and abs(v[:, 0].mean() - c["mean"][0]) < 50 for v, c in zip(voxels, clusters))
    flat = Logic.clusterGrayVolumes(volumes, None, 2, maxSamples=20_000)[0]  # a 2D region (here none) works too
    assert len(flat) == 2
    with pytest.raises(ValueError):
        Logic.clusterGrayVolumes(volumes, np.zeros_like(region), 3)
    with pytest.raises(ValueError):
        Logic.clusterGrayVolumes(volumes, region, 3, maxSamples=300)  # fewer voxels than the clusters need


@pytest.mark.parametrize("smoothing", [0.0, 1.0])
def test_classify_gray_volumes_gives_the_same_labels_whatever_the_size_of_the_slabs(smoothing):
    volumes = grayVolumes()
    clusters = grayClusters(volumes)
    reference = np.zeros(volumes[0].shape, dtype=np.uint8)
    Logic.classifyGrayVolumes(volumes, clusters, reference, 0.9, smoothing, memoryBytes=2**30)
    assert [(reference[..., n * 20 + 5 : n * 20 + 15] == n + 1).mean() for n in range(3)] == pytest.approx(
        [1.0] * 3, abs=0.02
    )
    plane = volumes[0].shape[1] * volumes[0].shape[2]
    for depth in (1, 3):  # slabs of a few slices, so that the halo of the filter is needed
        labels = np.full(volumes[0].shape, 255, dtype=np.uint8)
        result = Logic.classifyGrayVolumes(
            volumes, clusters, labels, 0.9, smoothing, memoryBytes=depth * plane * SUPERVISED_BYTES_PER_VOXEL
        )
        assert (labels == reference).all()
        assert result["voxels"] == labels.size and result["valid"] == labels.size


def test_classify_gray_volumes_respects_the_region_the_slices_and_the_stop():
    volumes = grayVolumes()
    clusters = grayClusters(volumes)
    region = np.zeros(volumes[0].shape[1:], dtype=bool)
    region[:, :40] = True
    labels = np.full(volumes[0].shape, 255, dtype=np.uint8)
    result = Logic.classifyGrayVolumes(volumes, clusters, labels, 0.0, 0.0, region=region, zRange=(2, 8))
    assert (labels[:2] == 0).all() and (labels[8:] == 0).all() and (labels[2:8, :, 40:] == 0).all()
    assert (labels[2:8, :, :40] > 0).all() and result["valid"] == 6 * 20 * 40
    calls = []
    stopped = Logic.classifyGrayVolumes(
        volumes,
        clusters,
        labels,
        0.0,
        0.0,
        memoryBytes=20 * 60 * SUPERVISED_BYTES_PER_VOXEL,
        progress=lambda f: calls.append(f) or len(calls) < 2,
    )
    assert stopped is None and len(calls) == 2
    with pytest.raises(ValueError):
        Logic.classifyGrayVolumes(volumes[:1], clusters, labels)


def test_fit_gray_gaussians_is_not_decided_by_a_few_outliers():
    rng = np.random.default_rng(1)
    clean = rng.normal([1000.0, 2000.0], [30.0, 40.0], (3000, 2))
    outliers = np.array([[65535.0, 65535.0]] * 25 + [[0.0, 3000.0]] * 25)  # saturated and mixed voxels
    clusters, _ = Logic.fitGrayGaussians([np.vstack([clean, outliers])])
    assert clusters[0]["mean"] == pytest.approx([1000.0, 2000.0], abs=5.0)
    assert np.sqrt(np.diag(clusters[0]["cov"])) == pytest.approx([30.0, 40.0], rel=0.1)
    assert clusters[0]["weight"] == pytest.approx(1.0)


# ----- the physical method with smoothing, region and slices -----
