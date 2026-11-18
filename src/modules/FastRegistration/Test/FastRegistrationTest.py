import numpy as np
import slicer
import vtk

from commons.algorithms.fast_registration import fast_reg, fast_reg_slicer
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events


def _blob_array(n=160, n_blobs=40, seed=0):
    """A volume of `n_blobs` compact bright cubes on a zero background — the feature pattern
    fast_reg is built to register. The cubes are kept small (3x3x3) so the bright fraction stays
    well under 0.1%: fast_reg's 99.9-percentile threshold then lands in the background, matching
    real microCT where dense inclusions are a tiny fraction of the volume."""
    rng = np.random.default_rng(seed)
    array = np.zeros((n, n, n), np.float32)
    for z, y, x in rng.integers(15, n - 15, size=(n_blobs, 3)):
        array[z - 1 : z + 2, y - 1 : y + 2, x - 1 : x + 2] = 1000.0
    return array


def _blob_centers(n=160, n_blobs=45, seed=3):
    """Random (z, y, x) blob centers, kept 35 voxels off every face so a rotation about the volume
    centre cannot push a blob out of the volume."""
    rng = np.random.default_rng(seed)
    return rng.integers(35, n - 35, size=(n_blobs, 3)).astype(float)


def _volume_from_centers(centers, n=160):
    """Build a volume with a 3x3x3 bright cube at each (z, y, x) centre. Unlike rotating the whole
    array, placing cubes at exactly-known centres gives a ground-truth correspondence to check the
    recovered matrix against, with no interpolation blur."""
    array = np.zeros((n, n, n), np.float32)
    for z, y, x in np.round(centers).astype(int):
        array[z - 1 : z + 2, y - 1 : y + 2, x - 1 : x + 2] = 1000.0
    return array


def _rotated_pair(n=160, angle_deg=12.0, shift_zyx=(3.0, -4.0, 5.0), n_blobs=45):
    """Blob centres and the same constellation rotated `angle_deg` about the z-axis and shifted:
    returns (fixed_centers, moving_centers), both (z, y, x) in full-resolution voxels."""
    centers = _blob_centers(n, n_blobs)
    theta = np.radians(angle_deg)
    cos, sin = np.cos(theta), np.sin(theta)
    rotation_zyx = np.array([[1.0, 0.0, 0.0], [0.0, cos, -sin], [0.0, sin, cos]])
    volume_center = np.full(3, n / 2.0)
    moving_centers = (rotation_zyx @ (centers - volume_center).T).T + volume_center + np.asarray(shift_zyx)
    return centers, moving_centers


def _downsample(array, factor):
    """Block-mean downsampling: the same scene seen with `factor` times larger voxels. Voxel i of
    the result covers full-resolution voxels factor*i .. factor*i + factor-1, so its centre is at
    full-resolution index factor*i + (factor-1)/2."""
    n = array.shape[0] // factor
    return array[: n * factor, : n * factor, : n * factor].reshape(n, factor, n, factor, n, factor).mean(axis=(1, 3, 5))


def _assert_maps_onto(matrix, moving_index_xyz, fixed_index_xyz, tolerance):
    homogeneous = np.c_[moving_index_xyz, np.ones(len(moving_index_xyz))]
    mapped = (np.asarray(matrix) @ homogeneous.T).T[:, :3]
    error = np.max(np.linalg.norm(mapped - fixed_index_xyz, axis=1))
    assert error < tolerance, f"max mapping error {error:.3f} voxels"


# A fabricated fast_reg.register report, for widget tests that skip the algorithm.
_RESULT_INFO = dict(matched=40, tested=42, log10_nfa=-80.0, refit_pairs=41, rms=0.025, rms_voxels=0.53)


def _make_volume_node(array, name, spacing=(1.0, 1.0, 1.0)):
    node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", name)
    slicer.util.updateVolumeFromArray(node, array)
    node.SetSpacing(*spacing)
    return node


def _ijk_to_ras(node):
    matrix = vtk.vtkMatrix4x4()
    node.GetIJKToRASMatrix(matrix)
    return np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])


class FastRegistrationTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        self._widgets = {"apply_button": self.find_widget("Apply Button")}

    def tear_down(self):
        pass

    # ------------------------------------------------------------------ pure algorithm

    def test_algorithm_recovers_identity(self):
        fixed = _blob_array()
        matrix, _ = fast_reg.register(fixed, fixed.copy())
        np.testing.assert_allclose(matrix, np.eye(4), atol=1e-6)

    def test_algorithm_recovers_translation(self):
        fixed = _blob_array()
        moving = np.roll(fixed, 7, axis=0)  # shift +7 in z (array axis 0)
        matrix, _ = fast_reg.register(fixed, moving)
        # K maps moving index -> fixed index; moving is fixed shifted +7 in z, so the z
        # translation recovered must be -7 (points/matrix are in x, y, z order).
        np.testing.assert_allclose(matrix[:3, 3], [0, 0, -7], atol=1e-3)

    def test_algorithm_recovers_rotation(self):
        # Arbitrary-rotation registration is the method's headline capability (not just translation).
        # Rotate the blob constellation 12 deg about the z-axis (the (y, x) image plane), then check
        # both the reported angle and that the recovered matrix maps every moving blob centre back
        # onto its fixed counterpart to sub-voxel accuracy.
        n = 160
        centers = _blob_centers(n)
        fixed = _volume_from_centers(centers, n)

        angle_deg = 12.0
        theta = np.radians(angle_deg)
        cos, sin = np.cos(theta), np.sin(theta)
        rotation_zyx = np.array([[1.0, 0.0, 0.0], [0.0, cos, -sin], [0.0, sin, cos]])
        volume_center = np.array([n / 2.0, n / 2.0, n / 2.0])
        moving_centers = (rotation_zyx @ (centers - volume_center).T).T + volume_center
        moving = _volume_from_centers(moving_centers, n)

        matrix, _ = fast_reg.register(fixed, moving)
        r = matrix[:3, :3]
        recovered_angle_deg = np.degrees(np.arccos(np.clip((np.trace(r) - 1) / 2, -1.0, 1.0)))
        assert abs(recovered_angle_deg - angle_deg) < 0.5, recovered_angle_deg

        # K maps a moving index coordinate (x, y, z, 1) onto the corresponding fixed index coordinate.
        moving_xyz = moving_centers[:, ::-1]  # (z, y, x) -> (x, y, z)
        fixed_xyz = centers[:, ::-1]
        homogeneous = np.c_[moving_xyz, np.ones(len(moving_xyz))]
        mapped = (matrix @ homogeneous.T).T[:, :3]
        assert np.max(np.linalg.norm(mapped - fixed_xyz, axis=1)) < 0.5

    def test_algorithm_recovers_transform_across_spacings(self):
        # The moving volume has twice the voxel size of the fixed one (and is rotated and shifted).
        # Voxel-count masses then differ 8x and voxel-unit tolerances mean different physical
        # sizes, so this only registers if everything is done in physical units.
        factor = 2
        fixed_centers, moving_centers = _rotated_pair()
        fixed = _volume_from_centers(fixed_centers)
        moving = _downsample(_volume_from_centers(moving_centers), factor)

        matrix, _ = fast_reg.register(fixed, moving, fixed_spacing=(1.0, 1.0, 1.0), moving_spacing=(float(factor),) * 3)

        # Coarse moving index of each blob centre, in (x, y, z) order (see _downsample).
        moving_index = (moving_centers[:, ::-1] - (factor - 1) / 2.0) / factor
        _assert_maps_onto(matrix, moving_index, fixed_centers[:, ::-1], tolerance=1.0)

    def test_algorithm_recovers_transform_across_anisotropic_spacings(self):
        # The moving volume is 2x coarser in-plane only: the fixed one is block-averaged along x and
        # y alone before registering, and K must still map the ORIGINAL index coordinates.
        fixed_centers, moving_centers = _rotated_pair()
        fixed = _volume_from_centers(fixed_centers)
        full = _volume_from_centers(moving_centers)
        moving = full.reshape(160, 80, 2, 80, 2).mean(axis=(2, 4))

        matrix, _ = fast_reg.register(fixed, moving, fixed_spacing=(1.0, 1.0, 1.0), moving_spacing=(2.0, 2.0, 1.0))

        moving_index = moving_centers[:, ::-1] - [0.5, 0.5, 0.0]
        moving_index[:, :2] /= 2.0
        _assert_maps_onto(matrix, moving_index, fixed_centers[:, ::-1], tolerance=1.0)

    def test_algorithm_registers_when_fixed_has_many_more_blobs(self):
        # Only a quarter of the inclusions show in the moving scan (e.g. the rest are too small for
        # it), so the fixed scan has four times the blob density. A moving tetrahedron's partner
        # then spans far more than the fixed blobs' few nearest neighbours.
        centers, moving_centers = _rotated_pair(n_blobs=120)
        fixed = _volume_from_centers(centers)
        moving = _volume_from_centers(moving_centers[:30])

        matrix, _ = fast_reg.register(fixed, moving)

        _assert_maps_onto(matrix, moving_centers[:30, ::-1], centers[:30, ::-1], tolerance=1.0)

    def test_significance_rejects_chance_matches_on_a_plane(self):
        # Inclusions often lie on fractures or laminae. Two unrelated blob sets on the same plane
        # then match far more often by chance than a volume-filling density model predicts; such a
        # model rates this pure chance as highly significant. It must not be accepted.
        rng = np.random.default_rng(0)
        for _ in range(5):
            fixed_plane = np.c_[rng.uniform(0, 1000, (400, 2)), np.zeros(400)]
            moving_plane = np.c_[rng.uniform(0, 1000, (400, 2)), np.zeros(400)]
            log10_nfa, *_ = fast_reg._significance(moving_plane, fixed_plane, exclude=[])
            assert log10_nfa >= 0, log10_nfa

    def test_algorithm_rejects_mirrored_volume(self):
        # A mirror image keeps every blob-to-blob distance, so every tetrahedron has a congruent
        # counterpart of opposite handedness. No rotation maps one onto the other: it must not register.
        fixed = _volume_from_centers(_blob_centers())
        mirrored = np.ascontiguousarray(fixed[::-1])
        try:
            fast_reg.register(fixed, mirrored)
        except fast_reg.RegistrationFailed:
            pass
        else:
            raise AssertionError("a mirrored volume must not register")

    def test_algorithm_registers_crop(self):
        # The moving volume is a 1/8-of-the-width crop of the fixed one, so most fixed blobs have no
        # counterpart: blob budgets and tetrahedra must still line up the ones that do.
        fixed = _blob_array(n_blobs=120, seed=5)
        crop = np.ascontiguousarray(fixed[20:100, 30:110, 40:120])
        matrix, _ = fast_reg.register(fixed, crop)
        np.testing.assert_allclose(matrix[:3, 3], [40, 30, 20], atol=0.1)  # (x, y, z) crop offset

    def test_algorithm_registers_despite_cupping(self):
        # Beam hardening makes a core's rim reconstruct brighter than its centre. A global percentile
        # would then pick the rim instead of the inclusions; contrast against the local background
        # must not.
        n = 160
        _, yy, xx = np.mgrid[:n, :n, :n]
        radius = np.hypot(yy - n / 2, xx - n / 2)
        core = np.where(radius < 72, 1000 + 1500 * (radius / 72) ** 2, 0).astype(np.float32)
        fixed = core + 0.8 * _volume_from_centers(_blob_centers())
        moving = np.ascontiguousarray(np.roll(fixed, 6, axis=0))
        matrix, _ = fast_reg.register(fixed, moving)
        np.testing.assert_allclose(matrix[:3, 3], [0, 0, -6], atol=0.1)

    def test_scale_params_bounds_pooled_size(self):
        # Pooling follows the smaller volume, so a full scan against a small crop would otherwise
        # be detected at full resolution (tens of GB for 2000**3). Equal volumes keep their pooling.
        params = fast_reg._scale_params((2000,) * 3, (1.0,) * 3, (250,) * 3, (1.0,) * 3)
        assert (2000 // params["pool_fixed"]) ** 3 <= fast_reg._MAX_POOLED_VOXELS, params
        assert params["pool_moving"] == 1, params
        params = fast_reg._scale_params((2000,) * 3, (1.0,) * 3, (2000,) * 3, (1.0,) * 3)
        assert params["pool_fixed"] == params["pool_moving"] == 4, params

    def test_algorithm_reports_progress_monotonically(self):
        fixed = _blob_array()
        fractions = []
        fast_reg.register(fixed, fixed.copy(), progress_callback=lambda f, m: fractions.append(f))
        assert fractions, "progress_callback was never called"
        assert fractions[0] >= 0.0 and fractions[-1] == 1.0
        assert all(a <= b + 1e-9 for a, b in zip(fractions, fractions[1:]))

    def test_algorithm_raises_with_diagnostics_when_no_features(self):
        rng = np.random.default_rng(1)
        noise = rng.standard_normal((160, 160, 160)).astype(np.float32)
        try:
            fast_reg.register(noise, rng.standard_normal((160, 160, 160)).astype(np.float32))
        except fast_reg.RegistrationFailed as exc:
            assert exc.diagnostics, "RegistrationFailed should carry diagnostics"
        else:
            raise AssertionError("expected RegistrationFailed on featureless volumes")

    # ------------------------------------------------------------------ Slicer integration

    def test_register_volume_nodes_creates_observed_transform(self):
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(np.roll(_blob_array(), 5, axis=0), "moving")

        transform_node, ras_matrix = fast_reg_slicer.register_volume_nodes(fixed, moving)

        assert transform_node is not None
        assert ras_matrix.shape == (4, 4)
        # Transform is observed (not hardened): the moving node references it.
        assert moving.GetTransformNodeID() == transform_node.GetID()

    def test_build_transform_node_from_index_matrix(self):
        # The widget gets only the index-space matrix from the logic, then rebuilds the transform
        # via build_transform_node. A pure +5 in z (array axis 0) index shift must produce an
        # observed transform on the moving node.
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        k = np.eye(4)
        k[2, 3] = 5.0  # matrix is in (x, y, z) order; translate +5 in z
        transform_node, ras_matrix = fast_reg_slicer.build_transform_node(fixed, moving, k.tolist())
        assert transform_node is not None
        assert moving.GetTransformNodeID() == transform_node.GetID()
        assert ras_matrix.shape == (4, 4)

    def test_build_transform_node_composes_ras_correctly(self):
        # The RAS transform must satisfy ras @ IJKToRAS(moving) == IJKToRAS(fixed) @ K, i.e. mapping a
        # moving voxel to RAS then applying the transform lands on the same RAS point as mapping
        # through the index-space K and fixed's geometry. Non-unit spacing and distinct origins make
        # this a real check of the composition, not just of the matrix shape.
        fixed = _make_volume_node(_blob_array(), "fixed", spacing=(0.5, 0.5, 0.5))
        moving = _make_volume_node(_blob_array(seed=2), "moving", spacing=(0.5, 0.5, 0.5))
        fixed.SetOrigin(1.0, 1.0, 1.0)
        moving.SetOrigin(3.0, -2.0, 1.0)

        k = np.eye(4)
        k[0, 3] = 4.0
        k[2, 3] = 5.0
        _, ras_matrix = fast_reg_slicer.build_transform_node(fixed, moving, k.tolist())

        lhs = ras_matrix @ _ijk_to_ras(moving)
        rhs = _ijk_to_ras(fixed) @ k
        np.testing.assert_allclose(lhs, rhs, atol=1e-6)

    def test_logic_run_registers_and_signals(self):
        # End-to-end exercise of the path the UI uses: FastRegistrationLogic.run registers on the
        # calling thread, then the finished signal delivers the index-space matrix. run() returns
        # before the signal fires (it is posted to the event loop), so this pumps events to get it.
        from FastRegistration import FastRegistrationLogic

        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(np.roll(_blob_array(), 6, axis=0), "moving")

        logic = FastRegistrationLogic()
        finished = []
        logic.registrationFinished.connect(lambda: finished.append(True))

        assert logic.run(fixed, moving) is None, "run() must publish its outcome via the signal"
        for _ in range(50):
            if finished:
                break
            process_events()

        assert finished, "registrationFinished never fired"
        assert logic.error is None, logic.error
        assert logic.failure is None, logic.failure
        assert logic.result is not None
        # moving is fixed rolled +6 in z, so the recovered index-space z translation is -6.
        np.testing.assert_allclose(logic.result[2, 3], -6.0, atol=1e-2)

    def test_logic_run_registers_volumes_of_different_spacing(self):
        # The UI path has to hand each node's own spacing to the algorithm.
        from FastRegistration import FastRegistrationLogic

        factor = 2
        fixed_centers, moving_centers = _rotated_pair()
        fixed = _make_volume_node(_volume_from_centers(fixed_centers), "fixed")
        moving = _make_volume_node(
            _downsample(_volume_from_centers(moving_centers), factor), "moving", spacing=(float(factor),) * 3
        )

        logic = FastRegistrationLogic()
        logic.run(fixed, moving)

        assert logic.result is not None, logic.failure or logic.error
        moving_index = (moving_centers[:, ::-1] - (factor - 1) / 2.0) / factor
        _assert_maps_onto(logic.result, moving_index, fixed_centers[:, ::-1], tolerance=1.0)

    def test_logic_run_reports_progress(self):
        # The progress callback is what keeps ProgressBarProc moving while the GUI thread is
        # blocked, so it has to reach fast_reg and come back with a rising fraction.
        from FastRegistration import FastRegistrationLogic

        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(np.roll(_blob_array(), 6, axis=0), "moving")

        seen = []
        FastRegistrationLogic().run(fixed, moving, progress_callback=lambda f, m: seen.append(f))

        assert seen, "no progress was reported"
        assert seen == sorted(seen), f"progress went backwards: {seen}"
        assert all(0.0 <= f <= 1.0 for f in seen), f"progress out of range: {seen}"

    # ------------------------------------------------------------------ failure reporting

    def test_logic_run_reports_structured_failure(self):
        # A RegistrationFailed is an expected outcome, not a crash: it lands in `failure` with its
        # diagnostics intact (so the widget can map the reason to actionable text), not in `error`.
        from FastRegistration import FastRegistrationLogic

        # Uniform volumes have no blobs to match, so fast_reg bails out early.
        flat = np.zeros((64, 64, 64), np.float32)
        fixed = _make_volume_node(flat, "fixed")
        moving = _make_volume_node(flat.copy(), "moving")

        logic = FastRegistrationLogic()
        logic.run(fixed, moving)

        assert logic.result is None
        assert logic.error is None, logic.error
        assert logic.failure is not None, "expected a structured failure"
        assert logic.failure["reason"]
        assert isinstance(logic.failure["diagnostics"], dict)
        # The reason must be one the widget has curated text for.
        from FastRegistration import _FAILURE_MESSAGES, _failure_message

        assert any(key in logic.failure["reason"] for key in _FAILURE_MESSAGES), logic.failure["reason"]
        assert _failure_message(logic.failure["reason"])

    def test_failure_message_maps_known_reasons(self):
        # Every RegistrationFailed reason fast_reg can raise must resolve to its curated, actionable
        # text (the keys are matched as substrings of the raised reason).
        from FastRegistration import _FAILURE_MESSAGES, _failure_message

        assert _FAILURE_MESSAGES, "expected at least one mapped failure reason"
        for key, message in _FAILURE_MESSAGES.items():
            assert _failure_message(f"leading text {key} trailing text") == message

    def test_failure_message_falls_back_for_unknown_reason(self):
        from FastRegistration import _failure_message

        message = _failure_message("some unrecognised failure")
        assert "some unrecognised failure" in message
        assert "manual registration" in message.lower()

    # ------------------------------------------------------------------ widget behavior

    def test_apply_disabled_until_valid_inputs(self):
        widget = self._module_widget
        apply_button = self._widgets["apply_button"]
        assert apply_button is not None
        # No inputs selected yet.
        assert apply_button.enabled is False

        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")

        widget.fixedInput.setCurrentNode(fixed)
        widget.setMovingNode(moving)
        process_events()
        assert apply_button.enabled is True

    def test_apply_disabled_when_same_node_selected(self):
        widget = self._module_widget
        apply_button = self._widgets["apply_button"]

        volume = _make_volume_node(_blob_array(), "volume")
        widget.fixedInput.setCurrentNode(volume)
        widget.setMovingNode(volume)
        process_events()

        assert apply_button.enabled is False
        assert widget.validationLabel.visible is True

    def test_apply_enabled_with_different_spacing(self):
        widget = self._module_widget
        apply_button = self._widgets["apply_button"]

        fixed = _make_volume_node(_blob_array(), "fixed", spacing=(1.0, 1.0, 1.0))
        moving = _make_volume_node(_blob_array(seed=2), "moving", spacing=(3.0, 3.0, 3.0))
        widget.fixedInput.setCurrentNode(fixed)
        widget.setMovingNode(moving)
        process_events()

        assert apply_button.enabled is True
        assert widget.validationLabel.visible is False

    def test_show_result_displays_matrix_and_enables_apply(self):
        # Given a finished result, the Result section appears with the 4x4 matrix filled in, the
        # banner set (rotation and RMS), and its Apply enabled. Uses a fabricated result so it stays fast and
        # deterministic (the algorithm itself is covered above).
        widget = self._module_widget
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        widget._fixedNode, widget._movingNode = fixed, moving

        ras_matrix = np.eye(4)
        ras_matrix[0, 3] = 2.5
        transform_node, _ = fast_reg_slicer.build_transform_node(fixed, moving, np.eye(4).tolist())
        widget._transformNode = transform_node

        widget._showResult(ras_matrix, _RESULT_INFO)
        process_events()
        try:
            assert widget.resultSection.visible is True
            assert widget.failureSection.visible is False
            assert widget.applyTransformButton.enabled is True
            assert "41 matched features" in widget.qcBanner.text, widget.qcBanner.text  # from _RESULT_INFO
            assert "25 µm" in widget.qcBanner.text, widget.qcBanner.text
            assert widget.matrixTable.item(0, 3).text() == "2.5000"
        finally:
            widget._stopPingPong()

    def test_input_apply_is_locked_while_a_result_is_pending(self):
        # Two enabled Apply buttons at once is exactly the ambiguity the Result section's Apply is
        # meant to remove: the input Apply must stay locked until the result is applied or cancelled.
        widget = self._module_widget
        apply_button = self._widgets["apply_button"]
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        widget.fixedInput.setCurrentNode(fixed)
        widget.setMovingNode(moving)
        widget._fixedNode, widget._movingNode = fixed, moving
        process_events()
        assert apply_button.enabled is True

        transform_node, _ = fast_reg_slicer.build_transform_node(fixed, moving, np.eye(4).tolist())
        widget._transformNode = transform_node
        widget._showResult(np.eye(4), _RESULT_INFO)
        process_events()
        assert apply_button.enabled is False

        widget._onCancelResultClicked()
        process_events()
        assert apply_button.enabled is True

    def test_apply_transform_bakes_it_and_removes_node(self):
        widget = self._module_widget
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        widget.fixedInput.setCurrentNode(fixed)
        widget.setMovingNode(moving)
        widget._fixedNode, widget._movingNode = fixed, moving

        ras_matrix = np.eye(4)
        transform_node, _ = fast_reg_slicer.build_transform_node(fixed, moving, np.eye(4).tolist())
        transform_id = transform_node.GetID()
        widget._transformNode = transform_node
        widget._showResult(ras_matrix, _RESULT_INFO)
        process_events()

        widget._onApplyTransformClicked()
        process_events()
        widget._stopPingPong()

        assert widget._transformNode is None
        assert moving.GetTransformNodeID() != transform_id  # no longer observing the transform
        assert not slicer.mrmlScene.IsNodePresent(transform_node)  # transform node removed
        assert widget.applyTransformButton.enabled is False
        assert widget.cancelResultButton.enabled is False
        # The cross-fade stops: an animation still running would read as unfinished work.
        assert widget._pingPongTimer.isActive() is False
        # With nothing pending, the input Apply is available again for the next pair.
        assert self._widgets["apply_button"].enabled is True

    def test_cancel_result_removes_transform_and_hides_section(self):
        widget = self._module_widget
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        widget._fixedNode, widget._movingNode = fixed, moving

        ras_matrix = np.eye(4)
        transform_node, _ = fast_reg_slicer.build_transform_node(fixed, moving, np.eye(4).tolist())
        widget._transformNode = transform_node
        widget._showResult(ras_matrix, _RESULT_INFO)
        process_events()

        widget._onCancelResultClicked()
        process_events()

        assert widget.resultSection.visible is False
        assert widget._transformNode is None
        assert not slicer.mrmlScene.IsNodePresent(transform_node)

    def test_preview_buttons_restore_layers_changed_from_elsewhere(self):
        # The slice views can be re-layered from outside the module (the Data module's visibility
        # toggles, say), which leaves the cross-fade animating an opacity on unrelated layers and
        # makes the preview look dead. Any preview button must put the fixed/moving pair back.
        widget = self._module_widget
        fixed = _make_volume_node(_blob_array(), "fixed")
        moving = _make_volume_node(_blob_array(seed=2), "moving")
        other = _make_volume_node(_blob_array(seed=5), "other")
        widget._fixedNode, widget._movingNode = fixed, moving

        transform_node, _ = fast_reg_slicer.build_transform_node(fixed, moving, np.eye(4).tolist())
        widget._transformNode = transform_node
        widget._showResult(np.eye(4), _RESULT_INFO)
        process_events()
        try:

            def breakLayers():
                layoutManager = slicer.app.layoutManager()
                for name in layoutManager.sliceViewNames():
                    composite = layoutManager.sliceWidget(name).sliceLogic().GetSliceCompositeNode()
                    composite.SetBackgroundVolumeID(other.GetID())
                    composite.SetForegroundVolumeID(None)

            breakLayers()
            process_events()
            assert widget._captureDisplayState()["background"] == other.GetID()

            widget._pauseOn(1.0)  # "Show moving"
            process_events()
            state = widget._captureDisplayState()
            assert state["background"] == fixed.GetID()
            assert state["foreground"] == moving.GetID()
            assert state["foregroundOpacity"] == 1.0

            # Resuming the cross-fade repairs the arrangement too, not just the paused views.
            breakLayers()
            process_events()
            widget._onPauseResumeClicked()
            process_events()
            state = widget._captureDisplayState()
            assert state["background"] == fixed.GetID()
            assert state["foreground"] == moving.GetID()
        finally:
            widget._stopPingPong()

    def test_show_failure_reveals_failure_section(self):
        widget = self._module_widget
        widget._showFailure("too few blobs detected in one or both volumes")
        process_events()

        assert widget.failureSection.visible is True
        assert widget.resultSection.visible is False
        assert widget.failureLabel.text  # actionable message shown
