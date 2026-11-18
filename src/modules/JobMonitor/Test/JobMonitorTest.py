from collections import OrderedDict, defaultdict
from pathlib import Path
from unittest.mock import MagicMock

from commons.remote.connections import ConnectionManager
from commons.remote.jobs import JobManager
from commons.remote.targets import TargetManager
from commons.slicer.tests.ltrace_plugin_test import LTracePluginTest
from commons.slicer.tests.utils import process_events, wait

from commons.slicer.widget.search_filter_bar import SearchFilterBar

TEST_RESOURCES_DIR = Path(__file__).parent / "Resources"
MOCK_JOBS_FILE = TEST_RESOURCES_DIR / "jobs.json"
MOCK_CONFIG_FILE = TEST_RESOURCES_DIR / "config.json"

TOTAL_JOBS = 5


class JobMonitorTest(LTracePluginTest):
    def pre_setup(self):
        self._orig_storage = JobManager.storage
        self._orig_jobs = JobManager.jobs
        self._orig_observers = JobManager.observers[:]
        self._orig_targets_storage = TargetManager.targets_storage
        self._orig_targets = TargetManager.targets
        self._orig_outdated = TargetManager.outdated
        self._orig_connections = ConnectionManager.connections

        JobManager.jobs = OrderedDict()
        JobManager.observers = []
        JobManager.storage = MOCK_JOBS_FILE
        ConnectionManager.connections = defaultdict(lambda: None)

        TargetManager.targets_storage = MOCK_CONFIG_FILE
        TargetManager.load_targets()
        JobManager.load_jobs()

    def post_setup(self):
        pass

    def tear_down(self):
        JobManager.storage = self._orig_storage
        JobManager.jobs = self._orig_jobs
        JobManager.observers = self._orig_observers
        TargetManager.targets_storage = self._orig_targets_storage
        TargetManager.targets = self._orig_targets
        TargetManager.outdated = self._orig_outdated
        ConnectionManager.connections = self._orig_connections

    # -- Helpers --

    def _visible_count(self):
        count = 0
        for uid, (item, job) in self._module_widget.listedJobs.items():
            if not item.isHidden():
                count += 1
        return count

    def _set_search_and_wait(self, text):
        self._module_widget.searchFilterBar.searchField.setText(text)
        wait(0.5)
        process_events()

    def _get_item_widget(self, uid):
        item, job = self._module_widget.listedJobs[uid]
        return self._module_widget.jobListWidget.itemWidget(item)

    def _visible_job_names(self):
        names = []
        for i in range(self._module_widget.jobListWidget.count):
            item = self._module_widget.jobListWidget.item(i)
            if not item.isHidden():
                widget = self._module_widget.jobListWidget.itemWidget(item)
                names.append(widget.jobNameLabel.text)
        return names

    # -- Tests --

    def test_jobs_loaded(self):
        self.assertEqual(len(self._module_widget.listedJobs), TOTAL_JOBS)
        self.assertEqual(self._module_widget.jobListWidget.count, TOTAL_JOBS)

    def test_filter_by_host(self):
        self._set_search_and_wait("@host atena")
        self.assertEqual(self._visible_count(), 3)

        self._set_search_and_wait("")
        self.assertEqual(self._visible_count(), TOTAL_JOBS)

    def test_filter_by_status(self):
        self._set_search_and_wait("@status completed")
        self.assertEqual(self._visible_count(), 1)

        self._set_search_and_wait("@status idle")
        self.assertEqual(self._visible_count(), 1)

    def test_filter_by_name(self):
        self._set_search_and_wait("@name PNS")
        self.assertEqual(self._visible_count(), 2)

    def test_filter_combined(self):
        self._set_search_and_wait("@host atena @status running")
        self.assertEqual(self._visible_count(), 1)

    def test_filter_free_text(self):
        self._set_search_and_wait("Epsilon")
        self.assertEqual(self._visible_count(), 1)

    def test_sort_by_name_asc(self):
        self._module_widget.searchFilterBar._setSortMode(SearchFilterBar.SORT_NAME_ASC)
        process_events()

        names = self._visible_job_names()
        self.assertTrue(len(names) == TOTAL_JOBS)
        self.assertEqual(names, sorted(names, key=str.lower))

    def test_cancel_disabled_for_idle(self):
        widget = self._get_item_widget("uid-idle")
        self.assertFalse(widget.allowCancel)

    def test_cancel_disabled_for_not_connected(self):
        widget = self._get_item_widget("uid-notconn")
        self.assertFalse(widget.allowCancel)

    def test_cancel_enabled_when_connected(self):
        job = JobManager.jobs["uid-running"]
        host_key = job.host.get_key()

        ConnectionManager.connections[host_key] = MagicMock()
        try:
            widget = self._get_item_widget("uid-running")
            widget.update(job)
            self.assertTrue(widget.allowCancel)
        finally:
            del ConnectionManager.connections[host_key]
