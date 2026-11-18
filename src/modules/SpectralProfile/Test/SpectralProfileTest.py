import numpy as np
import slicer

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from SpectralProfile import DEFAULT_Z_EXPONENT
from SpectralProfile import PRESET_STANDARDS as SPECTRAL_PRESETS


class SpectralProfileTest(LTracePluginTest):
    def pre_setup(self):
        pass

    def post_setup(self):
        self._widgets = {
            "input_selector": self.find_widget("Input Selector"),
            "energies_range": self.find_widget("Energies Range Widget"),
            "clusters_spin_box": self.find_widget("Clusters Spin Box"),
        }
        axis = np.linspace(160.0, 20.0, 12)
        a = np.zeros((20, 30))
        c = np.zeros((20, 30))
        for n, (aa, cc) in enumerate([(1.0, 5.0), (5.0, 30.0), (12.0, 55.0)]):
            a[:, n * 10 : (n + 1) * 10] = aa
            c[:, n * 10 : (n + 1) * 10] = cc
        rng = np.random.default_rng(0)
        model = a[None] * (axis[:, None, None] / 100.0) ** -3.0 + c[None]
        self._array = (1000.0 + model + rng.normal(0, 0.5, model.shape)).astype(np.uint16)
        self._volume = slicer.util.addVolumeFromArray(self._array, name="SpectralProfileTestVolume")

    def tear_down(self):
        slicer.mrmlScene.RemoveNode(self._volume)

    def test_default_interface_configuration(self):
        assert self._widgets["input_selector"] is not None
        assert (
            self._widgets["energies_range"].minimumValue == 20 and self._widgets["energies_range"].maximumValue == 160
        )
        assert self._widgets["clusters_spin_box"].value == 4

    def test_default_output_name_follows_exponent_and_clusters(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.outputNameLineEdit.setText("")
        widget.clustersSpinBox.setValue(5)
        process_events()

        assert widget._outputName() == "SpectralProfileTestVolume_spectral_b3_classes5_gmm"
        assert widget.outputNameLineEdit.placeholderText == widget._outputName()

    def test_editing_a_gaussian_updates_the_same_segmentation(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.clustersSpinBox.setValue(3)
        widget.confidenceSpinBox.setValue(0)
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput")
        widget._onClusterClicked()
        node = widget._clusterNode
        assert node is not None and node.GetSegmentation().GetNumberOfSegments() == 3

        cluster = widget._clusters[0]
        before = cluster["mean"].copy()
        angle, major, minor = cluster["shape"]
        cluster["mean"] = before + np.array([1.0, 0.0])  # what dragging the center does
        cluster["shape"] = (angle + 0.3, major * 1.5, minor)  # and the handles of the axes
        widget._onGaussiansEdited()

        assert widget._clusterNode is node
        assert not np.allclose(cluster["cov"], np.eye(2)) and cluster["mean"][0] == before[0] + 1.0
        slicer.mrmlScene.RemoveNode(node)

    def test_selecting_volume_computes_heatmap_and_power_law_fit(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        process_events()

        counts, low, high = widget._heatmap
        assert counts.shape[0] == 12 and (counts.sum(axis=1) == 20 * 30).all() and high > low
        a, c, valid = widget._params
        assert a.shape == c.shape == valid.shape == (20, 30)

    def test_energy_slider_selects_the_energies_and_validates_the_minimum(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.energiesRange.setValues(20, 100)
        process_events()
        assert len(widget._selection) == 7 and "7 of 12" in widget.energiesStatusLabel.text

        widget.energiesRange.setValues(20, 40)
        assert widget._selection is None

        widget.energiesRange.setValues(20, 160)
        assert len(widget._selection) == 12

    def test_clustering_creates_one_segment_per_cluster(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.clustersSpinBox.setValue(3)
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput")
        widget._onClusterClicked()

        node = slicer.util.getNode("SpectralProfileTestOutput")
        assert node.GetSegmentation().GetNumberOfSegments() == 3
        assert [c["count"] for c in widget._clusters] == [200, 200, 200]
        slicer.mrmlScene.RemoveNode(node)

    def test_new_segmentation_is_the_only_one_visible(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.clustersSpinBox.setValue(3)
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput")
        widget._onClusterClicked()
        first = slicer.util.getNode("SpectralProfileTestOutput")
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput2")
        widget._onClusterClicked()
        second = slicer.util.getNode("SpectralProfileTestOutput2")

        assert second.GetDisplayNode().GetVisibility() and not first.GetDisplayNode().GetVisibility()
        slicer.mrmlScene.RemoveNode(first)
        slicer.mrmlScene.RemoveNode(second)

    def test_stability_check_creates_a_map_with_high_agreement(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.clustersSpinBox.setValue(3)
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput")
        widget._onStabilityClicked()

        mapNode = slicer.util.getNode("SpectralProfileTestOutput_stability")
        assert slicer.util.arrayFromVolume(mapNode).max() <= 100
        assert "Stability" in widget.clusterStatusLabel.text
        slicer.mrmlScene.RemoveNode(mapNode)

    @staticmethod
    def _labelsOf(segmentationNode, volumeNode) -> np.ndarray:
        """Labels (1-based, in the order of the segments) of a segmentation on the grid of a volume."""
        segmentation = segmentationNode.GetSegmentation()
        labels = np.zeros(slicer.util.arrayFromVolume(volumeNode).shape, dtype=np.uint8)
        for n in range(segmentation.GetNumberOfSegments()):
            mask = slicer.util.arrayFromSegmentBinaryLabelmap(
                segmentationNode, segmentation.GetNthSegmentID(n), volumeNode
            )
            labels[mask > 0] = n + 1
        return labels

    def _addStandardsScene(self):
        """Teflon, aluminum and quartz whose a and c follow the model exactly (b = -3), in air, beside the SOI.
        Returns the volume, the SOI segmentation and the true beta."""
        beta, k, exponent = 30.0, 2e-4, 3.0
        logic = slicer.modules.SpectralProfileWidget.logic
        axis = np.linspace(160.0, 20.0, 12)
        size = 90
        array = np.full((12, size, size), 1000.0)  # air, which sets the background of each slice
        jj, ii = np.mgrid[:size, :size]
        for column, (_, formula, density, _) in zip((15, 45, 75), SPECTRAL_PRESETS):
            composition = logic.composition(logic.parseFormula(formula), density)
            c = beta * composition["electronDensity"]
            a = k * c * np.sum(composition["fractions"] * composition["Z"] ** exponent)
            disc = np.hypot(jj - 15, ii - column) < 9
            array[:, disc] = (1000.0 + a * (axis / 100.0) ** -3.0 + c)[:, None]
        soiMask = np.zeros((12, size, size), dtype=np.uint8)
        soiMask[:, 40:85, 10:80] = 1
        array[:, 40:85, 10:80] = 1300.0  # a block of "rock" inside the SOI
        volume = slicer.util.addVolumeFromArray(array.astype(np.uint16), name="CalibrationTestVolume")
        soi = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "CalibrationTestSOI")
        soi.CreateDefaultDisplayNodes()
        soi.SetReferenceImageGeometryParameterFromVolumeNode(volume)
        segmentId = soi.GetSegmentation().AddEmptySegment("SOI", "SOI")
        slicer.util.updateSegmentBinaryLabelmapFromArray(soiMask, soi, segmentId, volume)
        return volume, soi, beta

    def test_calibration_finds_the_standards_outside_the_soi_and_recovers_the_scale(self):
        volume, soi, beta = self._addStandardsScene()
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(volume)
        widget.soiSelector.setCurrentNode(soi)
        widget.exponentSpinBox.setValue(-3.0)
        widget.estimateExponentCheckBox.setChecked(False)  # calibrate with the b typed
        widget._onFitParametersChanged()
        process_events()
        assert widget.standardsTable.rowCount == 3
        assert widget.standardsTable.item(0, 1).text() == "C2F4"

        widget._onCalibrateClicked()

        calibration = widget._calibration
        assert abs(calibration["beta"] - beta) / beta < 0.05
        assert "beta" in widget.calibrationStatusLabel.text
        found = slicer.util.getNode("CalibrationTestVolume_standards")
        assert found.GetSegmentation().GetNumberOfSegments() >= 3
        for node in (found, soi, volume):
            slicer.mrmlScene.RemoveNode(node)

    def test_a_segmentation_can_be_chosen_to_adjust_its_gaussians(self):
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(self._volume)
        widget.clustersSpinBox.setValue(3)
        widget.confidenceSpinBox.setValue(0)
        widget.outputNameLineEdit.setText("SpectralProfileTestOutput")
        widget._onClusterClicked()
        node = widget._clusterNode
        kept = [np.array(cluster["mean"]) for cluster in widget._clusters]
        widget._clusters = None  # forget the session result, as after reopening the scene

        widget.adjustSelector.setCurrentNode(node)

        assert widget._clusters is not None and len(widget._clusters) == 3
        assert all(
            np.allclose(cluster["mean"], mean) for cluster, mean in zip(widget._clusters, kept)
        )  # not re-estimated
        assert widget._clusterNode is node and all(cluster.get("segmentId") for cluster in widget._clusters)
        cluster = widget._clusters[1]
        cluster["mean"] = cluster["mean"] + np.array([0.5, 0.0])
        widget._onGaussiansEdited()
        assert widget._clusterNode is node and node.GetSegmentation().GetNumberOfSegments() == 3
        widget.adjustSelector.setCurrentNode(None)
        slicer.mrmlScene.RemoveNode(node)

    def test_classes_get_a_mineral_and_the_segments_are_renamed(self):
        volume, soi, _ = self._addStandardsScene()
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(volume)
        widget.soiSelector.setCurrentNode(soi)
        widget.exponentSpinBox.setValue(-3.0)
        widget._onFitParametersChanged()
        widget._onCalibrateClicked()
        widget.clustersSpinBox.setValue(2)
        widget.confidenceSpinBox.setValue(0)
        widget.outputNameLineEdit.setText("MineralsTestOutput")
        widget._onClusterClicked()

        table = widget.resultsTable
        assert table.rowCount == len(widget._clusters) == len(widget._mineralCombos)
        assert widget._mineralCombos[0].itemText(0) == "Pores"  # the first choice
        widget._mineralCombos[0].setCurrentText("Quartz")
        widget._onApplyMineralsClicked()

        segmentation = widget._clusterNode.GetSegmentation()
        assert segmentation.GetNthSegment(0).GetName() == "Quartz"
        assert widget._clusters[0]["name"] == "Quartz"
        propertiesNode = slicer.mrmlScene.GetNodeByID(
            widget._clusterNode.GetNodeReferenceID("SpectralProfile.Properties")
        )
        assert propertiesNode.GetNumberOfRows() == len(widget._clusters)
        assert propertiesNode.GetCellText(0, propertiesNode.GetNumberOfColumns() - 1) == "Quartz"
        slicer.mrmlScene.RemoveNode(propertiesNode)
        found = slicer.util.getNode("CalibrationTestVolume_standards")
        for node in (widget._clusterNode, found, soi, volume):
            slicer.mrmlScene.RemoveNode(node)

    def test_estimating_the_exponent_on_the_standards_finds_the_one_of_the_scan(self):
        volume, soi, _ = self._addStandardsScene()
        widget = slicer.modules.SpectralProfileWidget
        widget.inputSelector.setCurrentNode(volume)
        widget.soiSelector.setCurrentNode(soi)
        widget.exponentSpinBox.setValue(-3.5)  # the scan follows -3.0
        widget._onFitParametersChanged()
        process_events()

        widget.estimateExponentCheckBox.setChecked(True)
        widget._onCalibrateClicked()

        assert abs(widget.exponentSpinBox.value + 3.0) < 0.15
        assert widget._calibration is not None
        found = slicer.util.getNode("CalibrationTestVolume_standards")
        for node in (found, soi, volume):
            slicer.mrmlScene.RemoveNode(node)

    def test_dual_energy_calibrates_the_volumes_with_the_standards_for_the_density_and_zeff(self):
        widget = slicer.modules.SpectralProfileWidget
        logic = widget.logic
        exponent = DEFAULT_Z_EXPONENT
        airs, scales, ratios = [2400.0, 3100.0], [4000.0, 7000.0], [0.0005, 0.0002]  # each volume has its own
        rng = np.random.default_rng(1)

        def known(formula, density):
            composition = logic.composition(logic.parseFormula(formula), density)
            return composition["electronDensity"], logic.effectiveZ(composition, exponent)

        standards = {"Teflon": known("C2F4", 2.2), "Aluminum": known("Al", 2.70), "Fused quartz": known("SiO2", 2.2)}
        materials = {"Quartz": known("SiO2", 2.65), "Dolomite": known("CaMg(CO3)2", 2.85)}
        shape = (30, 80, 80)
        boxes = {
            "Teflon": (slice(5, 25), slice(5, 25), slice(5, 25)),
            "Aluminum": (slice(5, 25), slice(5, 25), slice(30, 50)),
            "Fused quartz": (slice(5, 25), slice(5, 25), slice(55, 75)),
            "Air": (slice(5, 25), slice(30, 50), slice(5, 25)),
            "Quartz": (slice(5, 25), slice(55, 75), slice(5, 35)),
            "Dolomite": (slice(5, 25), slice(55, 75), slice(45, 75)),
        }
        rho, zeff = np.zeros(shape), np.zeros(shape)
        for name, (r, z) in {**standards, **materials}.items():
            rho[boxes[name]], zeff[boxes[name]] = r, z
        dualNodes = []
        for k in range(2):
            gray = airs[k] + scales[k] * rho * (1 + ratios[k] * zeff**exponent) + rng.normal(0, 3.0, shape)
            dualNodes.append(
                slicer.util.addVolumeFromArray(np.round(gray).astype(np.uint16), name=f"SpectralProfileDual{k}")
            )
        referenceNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SpectralProfileReferences")
        referenceNode.CreateDefaultDisplayNodes()
        referenceNode.SetReferenceImageGeometryParameterFromVolumeNode(dualNodes[0])
        for value, name in enumerate([*standards, "Air"], start=1):
            mask = np.zeros(shape, dtype=np.uint8)
            mask[boxes[name]] = 1
            referenceNode.GetSegmentation().AddEmptySegment(f"ref{value}", name, [1.0, 1.0, 1.0])
            slicer.util.updateSegmentBinaryLabelmapFromArray(mask, referenceNode, f"ref{value}", dualNodes[0])
        created = [*dualNodes, referenceNode]
        try:
            widget.dualLowSelector.setCurrentNode(dualNodes[0])
            widget.dualHighSelector.setCurrentNode(dualNodes[1])
            widget.dualReferenceSelector.setCurrentNode(referenceNode)
            calibration = widget._dualDensityCalibration()
            assert calibration["exponent"] == exponent
            for k, fit in enumerate(calibration["volumes"]):  # no energy is told: the ratio R stands for it
                assert abs(fit["air"] - airs[k]) < 10.0
                assert np.isclose(fit["scale"], scales[k], rtol=0.02) and np.isclose(fit["ratio"], ratios[k], rtol=0.05)
                assert fit["freedom"] == 1 and fit["relative"] < 0.01
            # the materials in the sample (not references) come out with their density and Zeff
            samples = [
                np.column_stack([slicer.util.arrayFromVolume(node)[boxes[name]].ravel() for node in dualNodes]).astype(
                    float
                )
                for name in materials
            ]
            properties, calibrationUsed = widget._dualVolumeProperties(samples)
            for item, (r, z) in zip(properties, materials.values()):
                assert np.isclose(item["values"][0], r, rtol=0.03) and np.isclose(item["values"][1], z, rtol=0.03)
                assert np.isclose(item["values"][2], r / 0.4995, rtol=0.03)
            assert widget._dualClassProperties(samples)[0] is not None

            # no multi-energy scan: the voxels of the SOI are clustered, and each cluster is named after its mineral
            soiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SpectralProfileClusterSOI")
            created.append(soiNode)
            soiNode.CreateDefaultDisplayNodes()
            soiNode.SetReferenceImageGeometryParameterFromVolumeNode(dualNodes[0])
            soiMask = np.zeros(shape, dtype=np.uint8)
            for name in materials:
                soiMask[boxes[name]] = 1
            soiNode.GetSegmentation().AddEmptySegment("soi", "SOI", [1.0, 1.0, 1.0])
            slicer.util.updateSegmentBinaryLabelmapFromArray(soiMask, soiNode, "soi", dualNodes[0])
            widget.dualSoiSelector.setCurrentNode(soiNode)
            widget.dualMethodSelector.setCurrentIndex(widget.dualMethodSelector.findData("cluster"))
            widget.dualClustersSpinBox.setValue(2)
            widget.dualOutputNameLineEdit.setText("SpectralProfileClusters")
            widget._onDualClicked()
            clustered = slicer.util.getNode("SpectralProfileClusters")
            created.append(clustered)
            segmentation = clustered.GetSegmentation()
            assert sorted(segmentation.GetNthSegment(n).GetName() for n in range(2)) == ["Dolomite", "Quartz"]
            labels = self._labelsOf(clustered, dualNodes[0])
            assert (labels[soiMask == 0] == 0).all() and (labels[soiMask > 0] > 0).all()
            widget.dualMethodSelector.setCurrentIndex(0)
            widget.dualSoiSelector.setCurrentNode(None)

            widget._onDualHistogramClicked()  # electron density and photoelectric term of the voxels
            assert not widget.dualHistogramView.isHidden() and "Mvoxels of" in widget.dualStatusLabel.text
            widget.dualReferenceSelector.setCurrentNode(
                None
            )  # without the standards there is nothing to calibrate with
            assert widget._dualClassProperties(samples)[0] is None
        finally:
            widget.dualReferenceSelector.setCurrentNode(None)
            for node in created:
                if node is not None and slicer.mrmlScene.IsNodePresent(node):
                    slicer.mrmlScene.RemoveNode(node)

    def test_dual_energy_segments_with_the_classes_of_the_multi_energy_slice(self):
        from scipy.ndimage import gaussian_filter, map_coordinates

        widget = slicer.modules.SpectralProfileWidget
        rng = np.random.default_rng(4)
        sliceZ, offset, scale = 14, (10.0, 12.0), 2.0
        texture = gaussian_filter(rng.normal(size=(30, 100, 100)), (4, 4, 4)).astype(np.float32)
        low, high = np.percentile(texture[sliceZ], [33, 66])  # three classes of equal size in the slice
        levels = [(1000.0, 1500.0), (3000.0, 2700.0), (5000.0, 3900.0)]  # gray of each class in the two volumes

        def classesOf(values):
            return (values > low).astype(int) + (values > high).astype(int)

        reference = np.stack(
            [1645.0 + 40.0 * classesOf(texture[sliceZ]) + rng.normal(0, 3, (100, 100)) for _ in range(12)]
        )
        multiNode = slicer.util.addVolumeFromArray(
            np.round(reference).astype(np.uint16), name="SpectralProfileLearnMulti"
        )
        multiNode.SetSpacing(0.072, 0.072, 0.072)
        rows, columns = np.mgrid[:160, :160]
        coordinates = [rows / scale + offset[0], columns / scale + offset[1]]
        truth = np.zeros((30, 160, 160), dtype=np.uint8)
        volumes = [np.zeros((30, 160, 160), dtype=np.float32), np.zeros((30, 160, 160), dtype=np.float32)]
        for z in range(30):
            truth[z] = classesOf(map_coordinates(texture[z], coordinates, order=1))
            for k in range(2):
                gray = np.array([levels[c][k] for c in range(3)], dtype=np.float32)[truth[z]]
                volumes[k][z] = gray + rng.normal(0, 80.0, gray.shape)
        dualNodes = [
            slicer.util.addVolumeFromArray(np.round(v).astype(np.uint16), name=f"SpectralProfileLearnDual{k}")
            for k, v in enumerate(volumes)
        ]
        for node in dualNodes:
            node.SetSpacing(0.036, 0.036, 0.036)
        classesNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SpectralProfileLearnClasses")
        classesNode.CreateDefaultDisplayNodes()
        classesNode.SetReferenceImageGeometryParameterFromVolumeNode(multiNode)
        sliceClasses = classesOf(texture[sliceZ])
        for value, name in enumerate(["Dark", "Middle", "Bright"]):
            mask = np.broadcast_to((sliceClasses == value).astype(np.uint8), (12, 100, 100)).copy()
            classesNode.GetSegmentation().AddEmptySegment(f"class{value}", name, [0.2 + 0.3 * value, 0.5, 0.5])
            slicer.util.updateSegmentBinaryLabelmapFromArray(mask, classesNode, f"class{value}", multiNode)
        created = [multiNode, *dualNodes, classesNode]
        try:
            widget.inputSelector.setCurrentNode(multiNode)
            widget.dualGaussiansSelector.setCurrentNode(classesNode)
            widget.dualLowSelector.setCurrentNode(dualNodes[0])
            widget.dualHighSelector.setCurrentNode(dualNodes[1])
            assert widget._dualProblem() == ""

            found = widget._registerDualSlice()  # runs by itself when segmenting; here, to look at where it is
            assert found is not None and abs(found["z"] - sliceZ) <= 1 and found["score"] > 0.8
            assert np.allclose(found["offset"], offset, atol=1.5) and abs(found["scale"] - 2.0) < 1e-6

            widget.dualWorkingMemoryGB = 0.05  # slabs of a few slices, not the whole volume
            widget.dualConfidenceSpinBox.setValue(0)
            widget.dualOutputNameLineEdit.setText("SpectralProfileLearnLabels")
            widget._onDualClicked()
            segmentationNode = slicer.util.getNode("SpectralProfileLearnLabels")
            created.append(segmentationNode)
            labels = self._labelsOf(segmentationNode, dualNodes[0])
            assert labels.shape == truth.shape and segmentationNode.GetSegmentation().GetNumberOfSegments() == 3
            inner = (slice(3, 27), slice(8, 152), slice(8, 152))
            assert (labels[inner] == truth[inner] + 1).mean() > 0.99
            assert "need them" in widget.dualStatusLabel.text  # no standards: no table of density and Zeff

            # a SOI chosen in the section is the region that is segmented, in 3D
            soiNode = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SpectralProfileLearnSOI")
            created.append(soiNode)
            soiNode.CreateDefaultDisplayNodes()
            soiNode.SetReferenceImageGeometryParameterFromVolumeNode(dualNodes[0])
            soiMask = np.zeros(truth.shape, dtype=np.uint8)
            soiMask[5:20, :, :80] = 1
            soiNode.GetSegmentation().AddEmptySegment("soi", "SOI", [1.0, 1.0, 1.0])
            slicer.util.updateSegmentBinaryLabelmapFromArray(soiMask, soiNode, "soi", dualNodes[0])
            widget.dualSoiSelector.setCurrentNode(soiNode)
            widget.dualOutputNameLineEdit.setText("SpectralProfileLearnLabelsSOI")
            widget._onDualClicked()
            segmentationNode = slicer.util.getNode("SpectralProfileLearnLabelsSOI")
            created.append(segmentationNode)
            labels = self._labelsOf(segmentationNode, dualNodes[0])
            assert (labels[soiMask == 0] == 0).all() and (labels[soiMask > 0] > 0).all()
        finally:
            widget.dualWorkingMemoryGB = 2.0
            widget.dualSoiSelector.setCurrentNode(None)
            for node in created:
                if node is not None and slicer.mrmlScene.IsNodePresent(node):
                    slicer.mrmlScene.RemoveNode(node)

    def test_reference_segmentation_a_fraction_of_a_voxel_off_the_grid_is_read_on_the_nearest_voxel(self):
        logic = slicer.modules.SpectralProfileWidget.logic
        array = np.full((20, 40, 40), 1000, dtype=np.uint16)
        array[5:15, 10:30, 10:30] = 5000
        volume = slicer.util.addVolumeFromArray(array, name="SpectralProfileGridVolume")
        other = slicer.util.addVolumeFromArray(array, name="SpectralProfileGridOther")
        other.SetOrigin(0.3, 0.2, 0.7)  # another origin, the way two scans of a sample can have it
        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "SpectralProfileGridSegmentation")
        segmentation.CreateDefaultDisplayNodes()
        segmentation.SetReferenceImageGeometryParameterFromVolumeNode(other)
        segmentation.GetSegmentation().AddEmptySegment("cube", "Cube", [1.0, 1.0, 1.0])
        mask = np.zeros(array.shape, dtype=np.uint8)
        mask[5:15, 10:30, 10:30] = 1
        slicer.util.updateSegmentBinaryLabelmapFromArray(mask, segmentation, "cube", other)
        created = [volume, other, segmentation]
        try:
            values = logic.referenceGrayValues(segmentation, "cube", [volume])[0]
            assert len(values) > 1000 and np.median(values) == 5000
            assert (values == 5000).mean() >= 0.85  # rounding the 0.7 to a voxel moves the cube by a slice of ten
            rotated = slicer.util.addVolumeFromArray(array, name="SpectralProfileGridScaled")
            created.append(rotated)
            rotated.SetSpacing(2.0, 2.0, 2.0)  # not the spacing of the segmentation: still refused
            raised = False
            try:
                logic.referenceGrayValues(segmentation, "cube", [rotated])
            except ValueError:
                raised = True
            assert raised
        finally:
            for node in created:
                if node is not None and slicer.mrmlScene.IsNodePresent(node):
                    slicer.mrmlScene.RemoveNode(node)
