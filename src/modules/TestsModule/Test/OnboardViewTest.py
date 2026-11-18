"""Tests for the GeoSlicer onboarding view (``commons.slicer.app.onboard_view``).

Covers the testable surface of the module:
  * pure helpers (formatting, suffix mapping, recent-path env persistence)
  * NetCDF suggestion / marker logic
  * OnboardWidget structure, picker mode, environment filtering, hover preview
    and launch behaviour
  * OnboardLayout overlay visibility
"""

import json
import qt
import slicer
import tempfile

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from commons.slicer.app import onboard_view
from commons.slicer.app.onboard_view import (
    LOADERS,
    OnboardLayout,
    OnboardWidget,
    _COLUMN_MIN_WIDTH,
    _COLUMN_SPACING,
    PATH_ENV_SETTINGS_KEY,
    PROJECT_SIZE_SETTINGS_KEY,
    YOUTUBE_CHANNEL_URL,
    _buildFooterText,
    _ellipsizeMiddle,
    _environmentForFile,
    _formatBytes,
    _classifyNetcdfVariable,
    _isGeoslicerNetcdf,
    _markdownToHtml,
    _pathSize,
    _projectRoot,
    _recentItemSize,
    recordProjectSize,
    _suggestEnvForDataset,
    _suggestEnvForNetcdf,
    getEnvironmentForPath,
    recordEnvironmentForPath,
)
from commons.slicer.tests.utils import process_events
from commons.slicer_utils import LTracePluginTest


class OnboardViewTest(LTracePluginTest):
    # -- setup / teardown -------------------------------------------------

    def pre_setup(self):
        # Snapshot the user settings we mutate so the user's real recents map
        # and recorded project sizes survive this test run.
        self.__originalPathEnvSetting = slicer.app.userSettings().value(PATH_ENV_SETTINGS_KEY, "")
        self.__originalSizeSetting = slicer.app.userSettings().value(PROJECT_SIZE_SETTINGS_KEY, "")
        slicer.app.userSettings().setValue(PATH_ENV_SETTINGS_KEY, "")
        slicer.app.userSettings().setValue(PROJECT_SIZE_SETTINGS_KEY, "")
        onboard_view._sizeCache.clear()

    def tear_down(self):
        slicer.app.userSettings().setValue(PATH_ENV_SETTINGS_KEY, self.__originalPathEnvSetting)
        slicer.app.userSettings().setValue(PROJECT_SIZE_SETTINGS_KEY, self.__originalSizeSetting)
        onboard_view._sizeCache.clear()
        # Hide overlay if a test left it visible.
        OnboardLayout.hide()

    # -- formatting helpers ----------------------------------------------

    def test_format_bytes_handles_units(self) -> None:
        assert _formatBytes(None) == "—"
        assert _formatBytes(0) == "0 B"
        assert _formatBytes(1024) == "1.0 KB"
        assert _formatBytes(1024 * 1024) == "1.0 MB"
        assert _formatBytes(2.5 * 1024**3) == "2.5 GB"

    def __moduleToolbar(self) -> qt.QToolBar:
        """The application's real module toolbar, which outlives the singleton overlay that keeps it."""
        return slicer.modules.AppContextInstance.mainWindow.findChild(qt.QToolBar, "ModuleToolBar")

    # -- closing on a scene load -------------------------------------------

    def test_loading_a_scene_closes_the_onboarding_view(self) -> None:
        # File > Load Scene: the user has already said how they want to open a
        # project, so the overlay has nothing left to offer and must not sit on
        # top of the scene they just opened.
        toolbar = self.__moduleToolbar()
        OnboardLayout.show(toolbar)
        process_events()
        assert OnboardLayout.isActive()

        events = slicer.modules.AppContextInstance.projectEventsLogic
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "Scene"
            project.mkdir()
            scene = project / "Scene.mrml"
            slicer.mrmlScene.SetURL(scene.as_posix())
            slicer.util.saveScene(scene.as_posix())

            slicer.mrmlScene.Clear(0)
            OnboardLayout.show(toolbar)
            process_events()
            assert OnboardLayout.isActive()

            assert events.loadScene(scene) is True
            process_events()
            assert not OnboardLayout.isActive(), "onboarding stayed open after a scene load"

    def test_a_cancelled_load_leaves_the_onboarding_view_alone(self) -> None:
        # Nothing was loaded, so nothing should move.
        toolbar = self.__moduleToolbar()
        OnboardLayout.show(toolbar)
        process_events()

        events = slicer.modules.AppContextInstance.projectEventsLogic
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp) / "Nope" / "Nope.mrml"
            with patch.object(type(events), "onCloseScene", return_value=False):
                assert events.loadScene(scene) is False

            process_events()
            assert OnboardLayout.isActive(), "a cancelled load should not close onboarding"

    # -- responsive layout -------------------------------------------------

    def test_walkthroughs_page_has_no_separator(self) -> None:
        # The rule between "Learn the Fundamentals" and "What's New" was noise.
        widget = OnboardWidget()
        page = widget.findChild(qt.QTextBrowser, "Whats New Browser").parent()
        separators = [child for child in page.findChildren(qt.QFrame) if child.frameShape == qt.QFrame.HLine]
        assert separators == []
        widget.cleanup()

    @contextmanager
    def __shownAt(self, width: int, height: int = 900):
        """An onboard widget laid out at a given size.

        The widget is a child of a host, as it is in the application. A top-level
        window cannot be resized below its layout's minimum size, so the narrow
        layouts could never be reached.
        """
        host = qt.QWidget()
        host.resize(width, height)
        widget = OnboardWidget(host)
        widget.setGeometry(0, 0, width, height)
        host.show()
        process_events()
        try:
            yield widget
        finally:
            widget.cleanup()
            host.hide()
            host.deleteLater()

    def test_both_columns_are_shown_when_there_is_room(self) -> None:
        wide = 2 * _COLUMN_MIN_WIDTH + _COLUMN_SPACING + 200
        with self.__shownAt(wide) as widget:
            assert widget.findChild(qt.QFrame, "OnboardSecondColumn").isVisible()

    def test_the_second_column_is_hidden_when_narrow(self) -> None:
        # Opening Slicer's side panels shrinks the central widget; past a point
        # the columns cannot both be drawn wide enough, and forcing them to try
        # is what made the START column spill over WALKTHROUGHS.
        narrow = 2 * _COLUMN_MIN_WIDTH + _COLUMN_SPACING - 100
        with self.__shownAt(narrow) as widget:
            assert not widget.findChild(qt.QFrame, "OnboardSecondColumn").isVisible()
            # START is what the space is given to, and it stays usable.
            assert widget.findChild(qt.QFrame, "OnboardStartColumn").isVisible()

    def test_the_second_column_comes_back_when_there_is_room_again(self) -> None:
        narrow = 2 * _COLUMN_MIN_WIDTH + _COLUMN_SPACING - 100
        with self.__shownAt(narrow) as widget:
            secondColumn = widget.findChild(qt.QFrame, "OnboardSecondColumn")
            assert not secondColumn.isVisible()

            widget.setGeometry(0, 0, 2 * _COLUMN_MIN_WIDTH + _COLUMN_SPACING + 400, 900)
            process_events()
            assert secondColumn.isVisible()

    def test_the_columns_never_overlap(self) -> None:
        # The actual defect: at a width the two could not share, their
        # geometries used to intersect.
        widths = (2200, 1400, 1100, 960, 800, 620)
        for width in widths:
            with self.__shownAt(width) as widget:
                startColumn = widget.findChild(qt.QFrame, "OnboardStartColumn")
                secondColumn = widget.findChild(qt.QFrame, "OnboardSecondColumn")
                if not secondColumn.isVisible():
                    continue
                first = qt.QRect(startColumn.mapTo(widget, qt.QPoint(0, 0)), startColumn.size)
                second = qt.QRect(secondColumn.mapTo(widget, qt.QPoint(0, 0)), secondColumn.size)
                assert not first.intersects(second), f"columns overlap at {width}px"

    def test_cleaned_up_widgets_are_deleted_without_crashing(self) -> None:
        # Regression: the children's signals hold the last Python references to
        # the widget, so a plain ``deleteLater()`` freed the wrapper in the middle
        # of the C++ destructor and crashed the application once the pending
        # deletes ran (after the whole suite, in the main event loop).
        for _ in range(3):
            widget = OnboardWidget()
            widget.show()
            process_events()
            widget.cleanup()
            del widget

        qt.QCoreApplication.sendPostedEvents(None, qt.QEvent.DeferredDelete)
        process_events()

    def test_environment_button_click_requests_its_launch(self) -> None:
        with self.__onboardWidget() as widget:
            requested = []
            button = self.__envButton(widget, "Volumes")
            button.launchRequested.connect(requested.append)
            button.clicked()
            process_events()
            assert requested == ["Volumes"]

    # -- project size ------------------------------------------------------

    @contextmanager
    def __savedProject(self, sceneBytes: int = 120_000, dataBytes: int = 9_000_000):
        """A project laid out the way ProjectManager.saveAs() writes one: a
        folder holding the .mrml plus the nodes' data files."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Well_A_MicroCT"
            (root / "Data").mkdir(parents=True)
            scene = root / "Well_A_MicroCT.mrml"
            scene.write_bytes(b"x" * sceneBytes)
            (root / "Data" / "volume.nrrd").write_bytes(b"y" * dataBytes)
            yield scene, root, sceneBytes + dataBytes

    def test_project_root_is_the_folder_holding_the_scene(self) -> None:
        # A GeoSlicer project is a directory; the recent list stores the .mrml
        # inside it, so the size must come from the folder.
        with self.__savedProject() as (scene, root, _total):
            assert _projectRoot(scene) == root

    def test_recent_size_covers_the_whole_project(self) -> None:
        with self.__savedProject() as (scene, _root, total):
            size, truncated = _recentItemSize(scene)
            assert size == total
            assert truncated is False
            # The scene file on its own is a tiny fraction of it -- reporting
            # that was the bug.
            assert scene.stat().st_size < total / 10

    def test_a_folder_holding_several_scenes_is_not_a_project(self) -> None:
        # Someone keeping scenes side by side in one folder: the folder total
        # belongs to no single entry, so fall back to the file.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            first = folder / "a.mrml"
            first.write_bytes(b"a" * 1000)
            (folder / "b.mrml").write_bytes(b"b" * 1000)
            (folder / "unrelated.bin").write_bytes(b"u" * 5_000_000)

            assert _projectRoot(first) == first
            assert _recentItemSize(first)[0] == 1000

    def test_non_project_entries_report_their_own_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            netcdf = Path(tmp) / "dataset.nc"
            netcdf.write_bytes(b"n" * 4096)

            assert _projectRoot(netcdf) == netcdf
            assert _recentItemSize(netcdf) == (4096, False)

    def test_a_missing_entry_has_no_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assert _recentItemSize(Path(tmp) / "gone" / "gone.mrml")[0] is None

    def test_a_scan_that_runs_out_of_budget_reports_a_lower_bound(self) -> None:
        # Projects can live on slow network shares, and the recent list is
        # rebuilt every time onboarding opens: the walk must be bounded.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            for index in range(300):
                (folder / f"f{index}.bin").write_bytes(b"d" * 1000)

            full, complete = _pathSize(folder, budgetSeconds=None)
            partial, truncated = _pathSize(folder, budgetSeconds=0.0)

            assert complete is False
            assert full == 300 * 1000
            assert truncated is True
            assert partial <= full

    def test_a_recorded_size_is_read_without_walking_the_project(self) -> None:
        # What ProjectManager.save() does, and what onboarding then reads.
        with self.__savedProject() as (scene, _root, total):
            recordProjectSize(scene)
            onboard_view._sizeCache.clear()

            with patch.object(onboard_view.os, "walk", side_effect=AssertionError("walked")):
                assert _recentItemSize(scene) == (total, False)

    def test_a_re_saved_project_is_measured_again(self) -> None:
        with self.__savedProject() as (scene, _root, total):
            recordProjectSize(scene)
            onboard_view._sizeCache.clear()

            scene.write_bytes(b"x" * 500_000)
            assert _recentItemSize(scene)[0] == total - 120_000 + 500_000

    def test_a_project_never_saved_here_is_measured_once(self) -> None:
        # Copied from a colleague, restored from a backup, or saved before
        # sizes were recorded: no record exists, so it is walked -- and the
        # result kept so it only happens the once.
        with self.__savedProject() as (scene, _root, total):
            assert _recentItemSize(scene) == (total, False)
            onboard_view._sizeCache.clear()

            with patch.object(onboard_view.os, "walk", side_effect=AssertionError("walked twice")):
                assert _recentItemSize(scene) == (total, False)

    def test_an_incomplete_measurement_is_never_recorded(self) -> None:
        # A partial total must not be persisted as the truth.
        with self.__savedProject() as (scene, _root, _total):
            with patch.object(onboard_view, "_SIZE_RECORD_BUDGET_SECONDS", 0.0):
                recordProjectSize(scene)

            assert slicer.app.userSettings().value(PROJECT_SIZE_SETTINGS_KEY, "") in ("", "{}")

    def test_recorded_sizes_stay_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for index in range(onboard_view._MAX_REMEMBERED_SIZES + 6):
                root = Path(tmp) / f"P{index}"
                root.mkdir()
                scene = root / f"P{index}.mrml"
                scene.write_bytes(b"x" * 10)
                recordProjectSize(scene)

            stored = json.loads(slicer.app.userSettings().value(PROJECT_SIZE_SETTINGS_KEY, "{}"))
            assert len(stored) == onboard_view._MAX_REMEMBERED_SIZES

    def test_ellipsize_middle(self) -> None:
        assert _ellipsizeMiddle("short") == "short"
        long = "/very/long/path/" + ("a" * 100) + "/file.txt"
        out = _ellipsizeMiddle(long, maxLen=30)
        assert len(out) == 30
        assert "…" in out
        # head and tail of original preserved
        assert out.startswith(long[:5])
        assert out.endswith(long[-5:])

    def test_environment_for_file_known_suffixes(self) -> None:
        assert _environmentForFile(Path("scene.mrml")) == "Project"
        assert _environmentForFile(Path("data.nc")) == "NetCDF"
        assert _environmentForFile(Path("a.dlis")) == "Well Logs"
        assert _environmentForFile(Path("a.las")) == "Well Logs"
        assert _environmentForFile(Path("a.dcm")) == "DICOM"
        assert _environmentForFile(Path("readme.md")) == "MD"
        assert _environmentForFile(Path("noext")) == "File"

    def test_markdown_to_html_subset(self) -> None:
        markdown = "# Title\n\n## Section\n\n- one\n- two\n\nplain"
        html = _markdownToHtml(markdown)
        assert "<h2" in html and "Title" in html
        assert "<h3" in html and "Section" in html
        assert "<ul" in html and "<li>one</li>" in html
        assert "<p" in html and "plain" in html
        assert "<ul" in html and html.count("</ul>") == 1

    def test_build_footer_text_contains_ltrace(self) -> None:
        text = _buildFooterText()
        assert text.endswith("LTrace")
        assert " · " in text

    # -- recent path → env persistence -----------------------------------

    def test_record_environment_round_trip(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mrml", delete=False) as tmp:
            path = tmp.name
        try:
            assert getEnvironmentForPath(path) is None
            recordEnvironmentForPath(path, "Volumes")
            assert getEnvironmentForPath(path) == "Volumes"

            # Updating reassigns the env for the same path.
            recordEnvironmentForPath(path, "Thin Section")
            assert getEnvironmentForPath(path) == "Thin Section"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_record_environment_ignores_empty_inputs(self) -> None:
        # No-op for empty path or env name.
        recordEnvironmentForPath("", "Volumes")
        recordEnvironmentForPath("/some/path", "")
        # Map should still be empty (we cleared in pre_setup).
        raw = slicer.app.userSettings().value(PATH_ENV_SETTINGS_KEY, "")
        assert raw in ("", "{}")

    def test_record_environment_caps_at_64_entries(self) -> None:
        # Insert 70 entries — only the most recent 64 should survive.
        for i in range(70):
            recordEnvironmentForPath(f"/tmp/path_{i:03d}.mrml", "Volumes")

        raw = slicer.app.userSettings().value(PATH_ENV_SETTINGS_KEY, "")
        mapping = json.loads(raw) if raw else {}
        assert len(mapping) == 64

        # Oldest entries dropped, newest kept (paths are normalized via resolve()
        # so we look up by the same form).
        assert getEnvironmentForPath("/tmp/path_069.mrml") == "Volumes"
        assert getEnvironmentForPath("/tmp/path_000.mrml") is None

    # -- NetCDF helpers --------------------------------------------------

    def test_geoslicer_netcdf_marker(self) -> None:
        try:
            import xarray as xr
            import numpy as np
        except ImportError:  # pragma: no cover - xarray ships with GeoSlicer
            return

        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            # File without geoslicer attr.
            ds = xr.Dataset({"img": (("y", "x"), np.zeros((4, 4)))})
            ds.to_netcdf(path, engine="h5netcdf")
            assert _isGeoslicerNetcdf(path) is False

            # File with marker.
            ds.attrs["geoslicer_version"] = "test"
            ds.to_netcdf(path, engine="h5netcdf")
            assert _isGeoslicerNetcdf(path) is True
        finally:
            path.unlink(missing_ok=True)

    def test_suggest_env_for_netcdf_3d_volumes(self) -> None:
        try:
            import xarray as xr
            import numpy as np
        except ImportError:  # pragma: no cover
            return

        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            ds = xr.Dataset({"img": (("z", "y", "x"), np.zeros((2, 2, 2)))})
            ds.to_netcdf(path, engine="h5netcdf")
            assert _suggestEnvForNetcdf(path) == ["Volumes"]
        finally:
            path.unlink(missing_ok=True)

    def test_suggest_env_for_netcdf_2d_thin_section(self) -> None:
        try:
            import xarray as xr
            import numpy as np
        except ImportError:  # pragma: no cover
            return

        with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp:
            path = Path(tmp.name)
        try:
            ds = xr.Dataset({"img": (("y", "x"), np.zeros((4, 4)))})
            ds.to_netcdf(path, engine="h5netcdf")
            assert _suggestEnvForNetcdf(path) == ["Thin Section"]
        finally:
            path.unlink(missing_ok=True)

    def test_suggest_env_for_netcdf_unreadable_falls_back(self) -> None:
        # Non-existent file → exception path returns [] so the caller shows the picker.
        assert _suggestEnvForNetcdf(Path("/no/such/file.nc")) == []

    # -- NetCDF variable classification (metadata-only, no file I/O) ------

    def __xr(self):
        """Return (xarray, numpy) or None when unavailable."""
        try:
            import xarray as xr
            import numpy as np

            return xr, np
        except ImportError:  # pragma: no cover - xarray ships with GeoSlicer
            return None

    def test_classify_rgb_is_thin_section(self) -> None:
        mods = self.__xr()
        if mods is None:
            return
        xr, np = mods
        # A colour channel (2D or 3D) is thin-section imagery.
        rgb2d = xr.DataArray(np.zeros((4, 4, 3)), dims=("y", "x", "c"))
        rgb3d = xr.DataArray(np.zeros((2, 2, 2, 3)), dims=("z", "y", "x", "c"))
        assert _classifyNetcdfVariable(rgb2d) == "Thin Section"
        assert _classifyNetcdfVariable(rgb3d) == "Thin Section"

    def test_classify_2d_by_spacing_anisotropy(self) -> None:
        mods = self.__xr()
        if mods is None:
            return
        xr, np = mods
        # One axis spacing >= 7x the other -> image log (Well Logs).
        wellLog = xr.DataArray(
            np.zeros((10, 10)),
            dims=("y", "x"),
            coords={"y": np.arange(10) * 1.0, "x": np.arange(10) * 0.1},  # ratio 10
        )
        assert _classifyNetcdfVariable(wellLog) == "Well Logs"

        # Near-isotropic spacing -> Thin Section.
        thin = xr.DataArray(
            np.zeros((10, 10)),
            dims=("y", "x"),
            coords={"y": np.arange(10) * 1.0, "x": np.arange(10) * 1.0},  # ratio 1
        )
        assert _classifyNetcdfVariable(thin) == "Thin Section"

    def test_classify_3d_core_vs_volumes(self) -> None:
        mods = self.__xr()
        if mods is None:
            return
        xr, np = mods

        # Elongated (extent ratio 10) AND coarse (0.5 mm > 50 um) -> Core.
        core = xr.DataArray(
            np.zeros((40, 4, 4)),
            dims=("z", "y", "x"),
            coords={"z": np.arange(40) * 0.5, "y": np.arange(4) * 0.5, "x": np.arange(4) * 0.5},
        )
        assert _classifyNetcdfVariable(core) == "Core"

        # Fine, roughly cubic -> Volumes (MicroCT).
        micro = xr.DataArray(
            np.zeros((8, 8, 8)),
            dims=("z", "y", "x"),
            coords={"z": np.arange(8) * 0.005, "y": np.arange(8) * 0.005, "x": np.arange(8) * 0.005},
        )
        assert _classifyNetcdfVariable(micro) == "Volumes"

        # Elongated but FINE spacing -> still Volumes (the coarse gate blocks Core).
        fineElongated = xr.DataArray(
            np.zeros((40, 4, 4)),
            dims=("z", "y", "x"),
            coords={"z": np.arange(40) * 0.005, "y": np.arange(4) * 0.005, "x": np.arange(4) * 0.005},
        )
        assert _classifyNetcdfVariable(fineElongated) == "Volumes"

    def test_classify_ignores_non_images(self) -> None:
        mods = self.__xr()
        if mods is None:
            return
        xr, np = mods
        # 1D (fewer than 2 spatial dims) and table columns are not classifiable.
        assert _classifyNetcdfVariable(xr.DataArray(np.zeros(5), dims=("x",))) is None
        assert _classifyNetcdfVariable(xr.DataArray(np.zeros(3), dims=("table__t",))) is None

    def test_suggest_env_for_dataset_combines(self) -> None:
        mods = self.__xr()
        if mods is None:
            return
        xr, np = mods

        # Distinct dim names per variable to avoid coordinate-merge conflicts.
        wellLog = xr.DataArray(
            np.zeros((10, 10)),
            dims=("wy", "wx"),
            coords={"wy": np.arange(10) * 1.0, "wx": np.arange(10) * 0.1},
        )
        rgb = xr.DataArray(np.zeros((4, 4, 3)), dims=("ty", "tx", "c"))
        thin = xr.DataArray(np.zeros((4, 4)), dims=("ay", "ax"))
        micro = xr.DataArray(
            np.zeros((6, 6, 6)),
            dims=("vz", "vy", "vx"),
            coords={"vz": np.arange(6) * 0.005, "vy": np.arange(6) * 0.005, "vx": np.arange(6) * 0.005},
        )

        # Single environment passes through.
        assert _suggestEnvForDataset(xr.Dataset({"a": thin})) == ["Thin Section"]

        # Image log + another type -> Multiscale.
        assert _suggestEnvForDataset(xr.Dataset({"log": wellLog, "photo": rgb})) == ["Multiscale"]

        # Two distinct non-image-log types -> ambiguous -> picker.
        assert _suggestEnvForDataset(xr.Dataset({"photo": thin, "vol": micro})) == []

        # Nothing classifiable -> picker.
        assert _suggestEnvForDataset(xr.Dataset({"col": xr.DataArray(np.zeros(3), dims=("table__t",))})) == []

    # -- OnboardWidget structure & toggles -------------------------------

    @contextmanager
    def __onboardWidget(self):
        parent = self._module_widget.parent
        widget = OnboardWidget(parent)
        # Provide a dummy toolbar so __loadEnvironmentByName paths are
        # exercised without actually loading modules.
        widget.setToolbar(qt.QToolBar(widget))
        try:
            yield widget
        finally:
            widget.cleanup()
            process_events()

    def __envButton(self, widget, displayName):
        return widget.findChild(qt.QPushButton, f"{displayName} Environment Button")

    def test_widget_has_expected_children(self) -> None:
        with self.__onboardWidget() as widget:
            assert widget.findChild(qt.QToolButton, "Onboard Close Button") is not None
            assert widget.findChild(qt.QToolButton, "Onboard Back Button") is not None
            assert widget.findChild(qt.QStackedWidget, "Onboard Content Stack") is not None
            assert widget.findChild(qt.QPushButton, "Open Project Button") is not None
            assert widget.findChild(qt.QPushButton, "Open NetCDF Project Button") is not None
            assert widget.findChild(qt.QPushButton, "Open Documentation Button") is not None
            assert widget.findChild(qt.QPushButton, "Open Youtube Button") is not None
            # One launcher per environment.
            for displayName in LOADERS:
                assert self.__envButton(widget, displayName) is not None

    def test_widget_close_signal(self) -> None:
        with self.__onboardWidget() as widget:
            received = []
            widget.closeRequested.connect(lambda: received.append(True))
            closeBtn = widget.findChild(qt.QToolButton, "Onboard Close Button")
            closeBtn.clicked()
            process_events()
            assert received == [True]

    def test_widget_picker_mode_toggle_visibility(self) -> None:
        with self.__onboardWidget() as widget:
            widget.show()
            process_events()
            backBtn = widget.findChild(qt.QToolButton, "Onboard Back Button")
            openMrml = widget.findChild(qt.QPushButton, "Open Project Button")
            openNc = widget.findChild(qt.QPushButton, "Open NetCDF Project Button")
            volumesBtn = self.__envButton(widget, "Volumes")

            # Full mode: back hidden; open actions + env launchers visible.
            assert backBtn.isVisibleTo(widget) is False
            assert openMrml.isVisibleTo(widget) is True
            assert openNc.isVisibleTo(widget) is True
            assert volumesBtn.isVisibleTo(widget) is True

            # Picker mode: back shown; open actions hidden; env launchers stay.
            widget.setDataTypesOnly(True)
            process_events()
            assert backBtn.isVisibleTo(widget) is True
            assert openMrml.isVisibleTo(widget) is False
            assert openNc.isVisibleTo(widget) is False
            assert volumesBtn.isVisibleTo(widget) is True

            # Back to full mode restores the open actions.
            widget.setDataTypesOnly(False)
            process_events()
            assert backBtn.isVisibleTo(widget) is False
            assert openMrml.isVisibleTo(widget) is True
            assert openNc.isVisibleTo(widget) is True

    def test_widget_env_filtering(self) -> None:
        with self.__onboardWidget() as widget:
            buttons = {name: self.__envButton(widget, name) for name in LOADERS}
            for button in buttons.values():
                assert button is not None

            # Without a filter, all environments are visible.
            widget.setDataTypesOnly(True, suggestedEnvs=None)
            process_events()
            for button in buttons.values():
                assert button.isHidden() is False

            # With a single suggested env, only that launcher shows.
            widget.setDataTypesOnly(True, suggestedEnvs=["Volumes"])
            process_events()
            visibleNames = [name for name, button in buttons.items() if not button.isHidden()]
            assert visibleNames == ["Volumes"]

            # Restoring full mode shows everything again.
            widget.setDataTypesOnly(False)
            process_events()
            for button in buttons.values():
                assert button.isHidden() is False

    def test_widget_env_hover_previews_and_reverts(self) -> None:
        with self.__onboardWidget() as widget:
            stack = widget.findChild(qt.QStackedWidget, "Onboard Content Stack")
            timer = widget.findChild(qt.QTimer, "Onboard Preview Revert Timer")
            button = self.__envButton(widget, "Volumes")
            assert button is not None
            assert timer is not None

            # Default panel is the Walkthroughs page (index 0).
            assert stack.currentIndex == 0

            # Hovering shows the environment preview page (index 1).
            button.enterEvent(None)
            process_events()
            assert stack.currentIndex == 1

            # Leaving does NOT revert immediately — it is debounced.
            button.leaveEvent(None)
            process_events()
            assert stack.currentIndex == 1
            assert timer.isActive() is True

            # When the debounce elapses, it reverts to Walkthroughs.
            timer.timeout()
            process_events()
            assert stack.currentIndex == 0

    def test_widget_env_hover_swaps_without_flicker(self) -> None:
        with self.__onboardWidget() as widget:
            stack = widget.findChild(qt.QStackedWidget, "Onboard Content Stack")
            timer = widget.findChild(qt.QTimer, "Onboard Preview Revert Timer")
            envTitle = widget.findChild(qt.QLabel, "Onboard Env Title")

            volumes = self.__envButton(widget, "Volumes")
            thinSection = self.__envButton(widget, "Thin Section")
            assert volumes is not None and thinSection is not None
            assert envTitle is not None

            # Hover A, then leave A (revert pending), then hover B before the
            # debounce fires: the pending revert is cancelled and B is shown
            # directly, so Walkthroughs never flashes in between.
            volumes.enterEvent(None)
            process_events()
            assert stack.currentIndex == 1
            assert envTitle.text == "Volumes"

            volumes.leaveEvent(None)
            process_events()
            assert timer.isActive() is True

            thinSection.enterEvent(None)
            process_events()
            assert timer.isActive() is False
            assert stack.currentIndex == 1
            assert envTitle.text == "Thin Section"

    def test_widget_env_click_in_picker_mode_loads_directly(self) -> None:
        with self.__onboardWidget() as widget:
            widget.setDataTypesOnly(True)
            button = self.__envButton(widget, "Volumes")
            assert button is not None

            # Patch loadEnvironment so we don't actually swap the env.
            with patch.object(onboard_view, "loadEnvironment") as mockLoad:
                button.clicked()
                process_events()
                assert mockLoad.called
                # First arg is the toolbar we attached, second the LoaderInfo.
                _toolbar, loaderInfo = mockLoad.call_args[0]
                assert loaderInfo.displayName == "Volumes"

    def test_widget_env_click_in_normal_mode_starts_project(self) -> None:
        with self.__onboardWidget() as widget:
            button = self.__envButton(widget, "Volumes")
            assert button is not None
            events = slicer.modules.AppContextInstance.projectEventsLogic

            # Clicking starts fresh: close the scene first, then load the env.
            with (
                patch.object(onboard_view, "loadEnvironment") as mockLoad,
                patch.object(events, "onCloseScene", return_value=True) as mockClose,
            ):
                button.clicked()
                process_events()
                assert mockClose.called
                assert mockLoad.called
                _toolbar, loaderInfo = mockLoad.call_args[0]
                assert loaderInfo.displayName == "Volumes"

    def test_widget_env_click_normal_mode_cancel_aborts(self) -> None:
        with self.__onboardWidget() as widget:
            button = self.__envButton(widget, "Volumes")
            assert button is not None
            events = slicer.modules.AppContextInstance.projectEventsLogic

            # If the close is cancelled, the environment must not load.
            with (
                patch.object(onboard_view, "loadEnvironment") as mockLoad,
                patch.object(events, "onCloseScene", return_value=False),
            ):
                button.clicked()
                process_events()
                assert not mockLoad.called

    # -- opening a project routes to the badged environment ---------------

    def test_open_mrml_prefers_recorded_environment(self) -> None:
        """The RECENT badge shows the recorded env, so opening must honour it.

        Detection only looks at top-level folder names and picks arbitrarily
        when a scene holds several data types, which is how a project badged
        "Volumes" used to open in "Thin Section".
        """
        with self.__onboardWidget() as widget:
            path = Path(tempfile.gettempdir()) / "badged_project.mrml"
            recordEnvironmentForPath(str(path), "Volumes")
            events = slicer.modules.AppContextInstance.projectEventsLogic

            with (
                patch.object(onboard_view, "loadEnvironment") as mockLoad,
                patch.object(events, "loadScene", return_value=True),
                patch("commons.slicer.app.tryDetectProjectDataType", return_value="Thin Section") as mockDetect,
            ):
                widget._OnboardWidget__openMrmlScene(path)
                process_events()

            assert mockLoad.called
            _toolbar, loaderInfo = mockLoad.call_args[0]
            assert loaderInfo.displayName == "Volumes"
            assert not mockDetect.called
            assert getEnvironmentForPath(str(path)) == "Volumes"

    def test_open_mrml_falls_back_to_detection(self) -> None:
        with self.__onboardWidget() as widget:
            path = Path(tempfile.gettempdir()) / "unknown_project.mrml"
            assert getEnvironmentForPath(str(path)) is None
            events = slicer.modules.AppContextInstance.projectEventsLogic

            with (
                patch.object(onboard_view, "loadEnvironment") as mockLoad,
                patch.object(events, "loadScene", return_value=True),
                patch("commons.slicer.app.tryDetectProjectDataType", return_value="Core"),
            ):
                widget._OnboardWidget__openMrmlScene(path)
                process_events()

            assert mockLoad.called
            _toolbar, loaderInfo = mockLoad.call_args[0]
            assert loaderInfo.displayName == "Core"
            # The detected environment becomes the badge for next time.
            assert getEnvironmentForPath(str(path)) == "Core"

    def test_open_netcdf_prefers_recorded_environment(self) -> None:
        with self.__onboardWidget() as widget:
            path = Path(tempfile.gettempdir()) / "badged_project.nc"
            recordEnvironmentForPath(str(path), "Well Logs")

            with (
                patch.object(onboard_view, "loadEnvironment") as mockLoad,
                patch.object(onboard_view, "_suggestEnvForNetcdf", return_value=["Volumes"]) as mockSuggest,
                patch.object(onboard_view, "_notifyAutoSelectedEnvironment") as mockNotify,
                patch.object(widget, "_OnboardWidget__importNetcdf") as mockImport,
            ):
                widget._OnboardWidget__openNetcdfProject(path)
                process_events()

            assert mockLoad.called
            _toolbar, loaderInfo = mockLoad.call_args[0]
            assert loaderInfo.displayName == "Well Logs"
            assert mockImport.called
            assert not mockSuggest.called
            # It is the user's own earlier choice, not an automatic guess.
            assert not mockNotify.called

    # -- OnboardLayout overlay -------------------------------------------

    def test_onboard_layout_show_and_hide(self) -> None:
        toolbar = self.__moduleToolbar()
        OnboardLayout.show(toolbar)
        process_events()
        assert OnboardLayout.isActive()

        OnboardLayout.hide()
        process_events()
        assert OnboardLayout.isActive() is False

    def test_onboard_layout_show_only_data_types_filters(self) -> None:
        toolbar = self.__moduleToolbar()
        OnboardLayout.showOnlyDataTypes(toolbar, suggestedEnvs=["Volumes"])
        process_events()

        container = OnboardLayout._container
        assert container is not None
        backBtn = container.findChild(qt.QToolButton, "Onboard Back Button")
        assert backBtn.isVisibleTo(container) is True

        buttons = {name: container.findChild(qt.QPushButton, f"{name} Environment Button") for name in LOADERS}
        visibleNames = [name for name, button in buttons.items() if not button.isHidden()]
        assert visibleNames == ["Volumes"]

        # show() resets the mode back to full.
        OnboardLayout.show(toolbar)
        process_events()
        assert backBtn.isVisibleTo(container) is False
        for button in buttons.values():
            assert button.isHidden() is False

    # -- Constants ---------------------------------------------------------

    def test_youtube_url_is_ltrace_channel(self) -> None:
        assert "ltracegeo" in YOUTUBE_CHANNEL_URL
