import shutil
import tempfile
from pathlib import Path

import numpy as np
import slicer
import tifffile

from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events
from commons.slicer.virtual import attributes as virtualAttributes
from commons.slicer.virtual import folder as virtualFolder
from commons.slicer.virtual import virtual_node
from commons.slicer.virtual.fourd import proxy as fourdProxy
from commons.slicer.virtual.fourd.manager import get_manager as getFourDManager
from commons.slicer.virtual.monitor import FolderMonitorService


class FolderMonitorTest(LTracePluginTest):
    """Deferred folder import, monitoring, and 4D sequences built from a folder."""

    def pre_setup(self):
        self.workspace = Path(tempfile.mkdtemp(prefix="folder-monitor-test-"))

    def tear_down(self):
        getFourDManager().closeAll()
        FolderMonitorService.instance().clear()
        for folder in virtualFolder.manager().folders():
            virtualFolder.manager().unregister(folder.root)
        shutil.rmtree(self.workspace, ignore_errors=True)

    # -- fixtures -------------------------------------------------------------------------------------
    def _writeStack(self, folder: Path, planes=4, value=0, size=(64, 48)):
        folder.mkdir(parents=True, exist_ok=True)
        for plane in range(planes):
            tifffile.imwrite(
                (folder / f"slice_{plane:03d}.tif").as_posix(),
                np.full(size, value + plane, dtype=np.uint16),
            )
        return folder

    def _writeTable(self, path: Path, rows=40):
        lines = ["sw krw krn"] + [f"{1 - index / rows:.4f} 0.1 0.2" for index in range(rows)]
        path.write_text("\n".join(lines) + "\n")
        return path

    def _selectFolder(self, folder: Path):
        widget = self._module_widget
        widget.directoryButton.directory = folder.as_posix()
        process_events()
        return widget

    @staticmethod
    def _bounds(node):
        box = [0.0] * 6
        node.GetRASBounds(box)
        return [round(value, 6) for value in box]

    # -- cases ----------------------------------------------------------------------------------------
    def test_deferred_import_creates_virtual_nodes(self):
        """A folder is listed as nodes holding samples, not as fully loaded data."""
        folder = self.workspace / "dataset"
        self._writeStack(folder / "recon_0", value=10)
        self._writeStack(folder / "recon_1", value=20)
        self._writeTable(folder / "timelog.csv")

        widget = self._selectFolder(folder)
        # 'recon_0' and 'recon_1' form a numbered family, so the module offers them as a sequence and says
        # so; unchecking that is what lists them as separate datasets.
        assert "kept for the sequence" in widget.scanLabel.text, widget.scanLabel.text
        widget.excludeFramesCheckBox.setChecked(False)
        process_events()
        assert "3 datasets found" in widget.scanLabel.text, widget.scanLabel.text

        widget.deferredCheckBox.setChecked(True)
        widget.importButton.click()
        process_events()

        volumes = [
            node
            for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
            if virtual_node.is_virtual_node(node)
        ]
        tables = [
            node for node in slicer.util.getNodesByClass("vtkMRMLTableNode") if virtual_node.is_virtual_node(node)
        ]

        assert len(volumes) == 2, [node.GetName() for node in volumes]
        assert len(tables) == 1

        spec = virtual_node.spec(volumes[0])
        assert spec.full_shape == (4, 64, 48), spec.full_shape  # 4 planes of 64 rows x 48 columns
        assert spec.uri.startswith("file://")
        assert volumes[0].GetAttribute(virtualAttributes.VIRTUAL_NODE) == "True"

        # The table node holds only its first rows, while remembering how many there are.
        assert tables[0].GetNumberOfRows() == 10
        assert virtual_node.spec(tables[0]).full_rows == 40

    def test_monitored_folder_lists_data_that_appears_later(self):
        """The point of monitoring: a dataset written after the import shows up on its own."""
        folder = self.workspace / "growing"
        self._writeStack(folder / "recon_0")

        widget = self._selectFolder(folder)
        widget.excludeFramesCheckBox.setChecked(False)
        widget.monitorCheckBox.setChecked(True)
        widget.importButton.click()
        process_events()

        assert FolderMonitorService.instance().isWatched(folder)
        before = len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"))

        self._writeStack(folder / "recon_1", value=50)
        FolderMonitorService.instance().check(folder)
        process_events()

        after = len(slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode"))
        assert after == before + 1, f"expected one more volume, went from {before} to {after}"

    def test_missing_data_is_marked_stale_not_deleted(self):
        """A vanished source is usually an unmounted share, so the node stays and says so."""
        folder = self.workspace / "vanishing"
        self._writeStack(folder / "recon_0")
        self._writeStack(folder / "recon_1")

        widget = self._selectFolder(folder)
        widget.excludeFramesCheckBox.setChecked(False)
        widget.importButton.click()
        process_events()

        shutil.rmtree(folder / "recon_1")
        report = virtualFolder.manager().sync(folder)
        process_events()

        assert report.stale, "the removed dataset should be reported"
        stale = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if virtual_node.is_stale(node)]
        assert len(stale) == 1
        assert slicer.mrmlScene.GetNodeByID(stale[0].GetID()) is not None

    def test_frame_pattern_is_suggested_and_creates_a_sequence(self):
        """Numbered entries become one 4D node, played from its preview."""
        folder = self.workspace / "sequence"
        for index in range(4):
            self._writeStack(folder / f"frame_{index:03d}", value=index * 10)

        widget = self._selectFolder(folder)

        patterns = [widget.patternComboBox.itemData(index) for index in range(widget.patternComboBox.count)]
        assert r"frame_\d+" in patterns, patterns

        widget.patternComboBox.setCurrentIndex(patterns.index(r"frame_\d+"))
        process_events()
        assert "4 frames" in widget.frameLabel.text, widget.frameLabel.text

        widget.createFourDButton.click()
        process_events()

        proxies = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if fourdProxy.is_proxy(node)]
        assert len(proxies) == 1
        node = proxies[0]
        player = getFourDManager().player(node)
        assert player is not None
        assert player.frameCount == 4
        assert widget.playerWidget.visible

        # Scrubbing paints from the preview cache and keeps the sequence's geometry.
        spacingBefore = node.GetSpacing()
        assert player.seek(2)
        process_events()
        assert player.index == 2
        assert node.GetAttribute(virtualAttributes.FOURD_RESOLUTION) == "preview"
        assert node.GetSpacing() == spacingBefore

        values = slicer.util.arrayFromVolume(node)
        assert int(values.min()) == 20, "frame 2 was written with values starting at 20"

    def test_creating_a_sequence_twice_reuses_it(self):
        """A folder that gained frames is the same sequence: a second click refreshes it, it does not clone it."""
        folder = self.workspace / "recreated"
        for index in range(2):
            self._writeStack(folder / f"frame_{index:03d}", value=index * 10)

        widget = self._selectFolder(folder)
        patterns = [widget.patternComboBox.itemData(index) for index in range(widget.patternComboBox.count)]
        widget.patternComboBox.setCurrentIndex(patterns.index(r"frame_\d+"))
        process_events()

        widget.createFourDButton.click()
        process_events()

        first = widget.playerWidget.player
        assert first is not None, "the first click should have created a player"
        assert first.frameCount == 2

        # The scrubber owns whether the view follows the newest frame, so a second click must not reset it
        # to whatever the module's own checkbox happens to say.
        first.setFollow(True)
        assert not widget.followCheckBox.checked
        self._writeStack(folder / "frame_002", value=20)

        widget.createFourDButton.click()
        process_events()

        assert widget.playerWidget.player is first, "a second node was created for the same folder"
        assert first.frameCount == 3, "the second click should have picked up the new frame"
        assert first.follow, "recreating must not override the player's own Follow latest"

        proxies = [node for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode") if fourdProxy.is_proxy(node)]
        assert len(proxies) == 1, [node.GetName() for node in proxies]

    def test_full_resolution_is_loaded_only_on_request(self):
        """The preview is what scrubbing shows; full resolution is an explicit action."""
        folder = self.workspace / "resolution"
        for index in range(2):
            self._writeStack(folder / f"frame_{index:03d}", value=index, size=(512, 384))

        node, player = getFourDManager().create(folder, pattern=r"frame_\d+")
        process_events()

        assert player.cache.factor > 1, "a large frame must be previewed downsampled"
        previewDimensions = node.GetImageData().GetDimensions()
        previewBounds = self._bounds(node)

        player.seek(0)
        player._onSettled()
        process_events()

        assert player.settled
        assert player.loadFullResolution()
        process_events()

        fullDimensions = node.GetImageData().GetDimensions()
        assert fullDimensions == (384, 512, 4), fullDimensions  # dims are (x, y, z) of a (z, rows, columns) array
        assert fullDimensions != previewDimensions
        assert node.GetAttribute(virtualAttributes.FOURD_RESOLUTION) == "full"

        # Promoting a frame changes its detail, never where it is: the two resolutions occupy the same
        # physical box, so the slice views neither jump nor rescale.
        assert self._bounds(node) == previewBounds, (self._bounds(node), previewBounds)

        # And that box is where GeoSlicer would have put the same image had it been loaded eagerly:
        # centred on the world origin, as every importer does by default.
        for lower, upper in zip(previewBounds[::2], previewBounds[1::2]):
            assert abs(lower + upper) < 1e-9, f"the frame is not centred: {previewBounds}"

        player.showPreview()
        process_events()
        assert node.GetImageData().GetDimensions() == previewDimensions

    def test_stop_monitoring_keeps_the_nodes(self):
        folder = self.workspace / "stopping"
        self._writeStack(folder / "recon_0")

        widget = self._selectFolder(folder)
        widget.excludeFramesCheckBox.setChecked(False)
        widget.importButton.click()
        process_events()

        assert widget.monitoredList.count >= 1
        widget.monitoredList.setCurrentRow(0)
        widget.stopButton.click()
        process_events()

        assert not FolderMonitorService.instance().isWatched(folder)
        assert any(
            virtual_node.is_virtual_node(node) for node in slicer.util.getNodesByClass("vtkMRMLScalarVolumeNode")
        ), "stopping the monitor must not remove what was already listed"
