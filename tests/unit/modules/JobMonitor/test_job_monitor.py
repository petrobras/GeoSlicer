import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from commons.remote.constants import (
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_DEPLOYING,
    JOB_STATE_DONE,
    JOB_STATE_FAILED,
    JOB_STATE_GHOST,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)

from modules.JobMonitor.JobMonitor import (
    JobSearchQuery,
    _drainPendingUpdates,
    _listener,
    partition_by_cancellable,
    should_allow_cancel,
    should_allow_forget,
    should_allow_reconnect,
)

ALL_STATES = (
    JOB_STATE_CANCELLED,
    JOB_STATE_COMPLETED,
    JOB_STATE_DEPLOYING,
    JOB_STATE_FAILED,
    JOB_STATE_GHOST,
    JOB_STATE_IDLE,
    JOB_STATE_NOTCONNECTED,
    JOB_STATE_PENDING,
    JOB_STATE_RUNNING,
)


@dataclass
class MockHost:
    name: str
    address: str = ""
    protocol: str = ""


@dataclass
class MockJob:
    name: str
    host: MockHost
    status: str
    uid: str = "uid-1"
    job_type: str = "generic"


def make_job(
    name="job1",
    host_name="atena02",
    status="RUNNING",
    address="10.0.0.1",
    protocol="ssh",
    uid="uid-1",
    job_type="generic",
):
    return MockJob(
        name=name,
        host=MockHost(name=host_name, address=address, protocol=protocol),
        status=status,
        uid=uid,
        job_type=job_type,
    )


class TestJobSearchQueryParse(unittest.TestCase):
    def test_empty_input(self):
        q = JobSearchQuery.parse("")
        self.assertIsNone(q.host_filter)
        self.assertIsNone(q.name_filter)
        self.assertIsNone(q.status_filter)
        self.assertEqual(q.free_text, "")

    def test_free_text_only(self):
        q = JobSearchQuery.parse("backup")
        self.assertIsNone(q.host_filter)
        self.assertEqual(q.free_text, "backup")

    def test_host_flag(self):
        q = JobSearchQuery.parse("@host atena")
        self.assertEqual(q.host_filter, "atena")
        self.assertEqual(q.free_text, "")

    def test_name_flag(self):
        q = JobSearchQuery.parse("@name puc_model")
        self.assertEqual(q.name_filter, "puc_model")

    def test_status_flag(self):
        q = JobSearchQuery.parse("@status running")
        self.assertEqual(q.status_filter, "running")

    def test_combined_flags(self):
        q = JobSearchQuery.parse("@host atena @status running")
        self.assertEqual(q.host_filter, "atena")
        self.assertEqual(q.status_filter, "running")
        self.assertIsNone(q.name_filter)
        self.assertEqual(q.free_text, "")

    def test_flag_with_free_text(self):
        q = JobSearchQuery.parse("@host atena backup")
        self.assertEqual(q.host_filter, "atena")
        self.assertEqual(q.free_text, "backup")

    def test_all_flags(self):
        q = JobSearchQuery.parse("@host atena @name puc @status running")
        self.assertEqual(q.host_filter, "atena")
        self.assertEqual(q.name_filter, "puc")
        self.assertEqual(q.status_filter, "running")
        self.assertEqual(q.free_text, "")

    def test_address_flag(self):
        q = JobSearchQuery.parse("@address 10.0")
        self.assertEqual(q.address_filter, "10.0")

    def test_protocol_flag(self):
        q = JobSearchQuery.parse("@protocol ssh")
        self.assertEqual(q.protocol_filter, "ssh")

    def test_uid_flag(self):
        q = JobSearchQuery.parse("@uid abc-123")
        self.assertEqual(q.uid_filter, "abc-123")

    def test_type_flag(self):
        q = JobSearchQuery.parse("@type segmentation")
        self.assertEqual(q.type_filter, "segmentation")

    def test_all_new_flags_combined(self):
        q = JobSearchQuery.parse("@address 10.0 @protocol ssh @uid abc @type seg")
        self.assertEqual(q.address_filter, "10.0")
        self.assertEqual(q.protocol_filter, "ssh")
        self.assertEqual(q.uid_filter, "abc")
        self.assertEqual(q.type_filter, "seg")

    def test_flag_at_end_without_value(self):
        q = JobSearchQuery.parse("@host")
        self.assertIsNone(q.host_filter)
        self.assertEqual(q.free_text, "@host")

    def test_unknown_flag_treated_as_free_text(self):
        q = JobSearchQuery.parse("@unknown value")
        self.assertEqual(q.free_text, "@unknown value")

    def test_case_insensitive_flags(self):
        q = JobSearchQuery.parse("@HOST atena")
        self.assertEqual(q.host_filter, "atena")

    def test_last_flag_wins(self):
        q = JobSearchQuery.parse("@host atena @host zeus")
        self.assertEqual(q.host_filter, "zeus")

    def test_free_text_before_and_after_flag(self):
        q = JobSearchQuery.parse("hello @host atena world")
        self.assertEqual(q.host_filter, "atena")
        self.assertEqual(q.free_text, "hello world")


class TestJobSearchQueryMatches(unittest.TestCase):
    def test_empty_query_matches_all(self):
        q = JobSearchQuery.parse("")
        self.assertTrue(q.matches(make_job()))

    def test_free_text_matches_name(self):
        q = JobSearchQuery.parse("backup")
        self.assertTrue(q.matches(make_job(name="puc_backup")))

    def test_free_text_matches_host_in_label(self):
        q = JobSearchQuery.parse("atena")
        self.assertTrue(q.matches(make_job(host_name="atena02")))

    def test_free_text_no_match(self):
        q = JobSearchQuery.parse("segmenter")
        self.assertFalse(q.matches(make_job(name="puc_backup")))

    def test_host_filter_match(self):
        q = JobSearchQuery.parse("@host atena")
        self.assertTrue(q.matches(make_job(host_name="atena02")))

    def test_host_filter_no_match(self):
        q = JobSearchQuery.parse("@host zeus")
        self.assertFalse(q.matches(make_job(host_name="atena02")))

    def test_name_filter_match(self):
        q = JobSearchQuery.parse("@name puc")
        self.assertTrue(q.matches(make_job(name="puc_model_v2")))

    def test_name_filter_no_match(self):
        q = JobSearchQuery.parse("@name segmenter")
        self.assertFalse(q.matches(make_job(name="puc_model_v2")))

    def test_status_filter_match_case_insensitive(self):
        q = JobSearchQuery.parse("@status running")
        self.assertTrue(q.matches(make_job(status="RUNNING")))

    def test_status_filter_no_match(self):
        q = JobSearchQuery.parse("@status idle")
        self.assertFalse(q.matches(make_job(status="RUNNING")))

    def test_combined_filters_and_semantics_all_match(self):
        q = JobSearchQuery.parse("@host atena @status running")
        self.assertTrue(q.matches(make_job(host_name="atena02", status="RUNNING")))

    def test_combined_filters_and_semantics_partial_match(self):
        q = JobSearchQuery.parse("@host atena @status idle")
        self.assertFalse(q.matches(make_job(host_name="atena02", status="RUNNING")))

    def test_filter_plus_free_text_match(self):
        q = JobSearchQuery.parse("@host atena backup")
        self.assertTrue(q.matches(make_job(name="backup_job", host_name="atena02")))

    def test_filter_plus_free_text_no_match(self):
        q = JobSearchQuery.parse("@host atena segmenter")
        self.assertFalse(q.matches(make_job(name="backup_job", host_name="atena02")))

    def test_address_filter_match(self):
        q = JobSearchQuery.parse("@address 10.0")
        self.assertTrue(q.matches(make_job(address="10.0.0.5")))

    def test_address_filter_no_match(self):
        q = JobSearchQuery.parse("@address 192.")
        self.assertFalse(q.matches(make_job(address="10.0.0.5")))

    def test_address_filter_missing_attribute(self):
        job = make_job()
        job.host = type("HostNoAddr", (), {"name": "whatever-host"})()
        q = JobSearchQuery.parse("@address anything")
        self.assertFalse(q.matches(job))

    def test_protocol_filter_match(self):
        q = JobSearchQuery.parse("@protocol ssh")
        self.assertTrue(q.matches(make_job(protocol="ssh")))

    def test_protocol_filter_no_match(self):
        q = JobSearchQuery.parse("@protocol whatever")
        self.assertFalse(q.matches(make_job(protocol="ssh")))

    def test_uid_filter_match(self):
        q = JobSearchQuery.parse("@uid abc")
        self.assertTrue(q.matches(make_job(uid="abc-123-xyz")))

    def test_uid_filter_no_match(self):
        q = JobSearchQuery.parse("@uid zzz")
        self.assertFalse(q.matches(make_job(uid="abc-123-xyz")))

    def test_type_filter_match(self):
        q = JobSearchQuery.parse("@type segmentation")
        self.assertTrue(q.matches(make_job(job_type="segmentation_job")))

    def test_type_filter_no_match(self):
        q = JobSearchQuery.parse("@type backup")
        self.assertFalse(q.matches(make_job(job_type="segmentation_job")))


class TestShouldAllowCancel(unittest.TestCase):
    def test_running_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_RUNNING, True))

    def test_completed_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_COMPLETED, True))

    def test_deploying_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_DEPLOYING, True))

    def test_pending_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_PENDING, True))

    def test_failed_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_FAILED, True))

    def test_cancelled_and_connected(self):
        self.assertTrue(should_allow_cancel(JOB_STATE_CANCELLED, True))

    def test_idle_and_connected(self):
        self.assertFalse(should_allow_cancel(JOB_STATE_IDLE, True))

    def test_not_connected_and_connected(self):
        self.assertFalse(should_allow_cancel(JOB_STATE_NOTCONNECTED, True))

    def test_ghost_and_connected(self):
        self.assertFalse(should_allow_cancel("GHOST", True))

    def test_running_and_disconnected(self):
        self.assertFalse(should_allow_cancel(JOB_STATE_RUNNING, False))

    def test_idle_and_disconnected(self):
        self.assertFalse(should_allow_cancel(JOB_STATE_IDLE, False))

    def test_pending_and_disconnected(self):
        self.assertFalse(should_allow_cancel(JOB_STATE_PENDING, False))


class TestShouldAllowForget(unittest.TestCase):
    """Local-only removal: the escape hatch that keeps every entry removable."""

    def test_every_row_always_offers_the_local_removal(self):
        # Unlink needs nothing from the cluster, so no state may refuse it.
        # It used to be offered only when Cancel/Delete was not, which trapped
        # a FAILED row whenever a dead client was still cached for its host:
        # check_host reported the host as connected, Cancel/Delete was offered
        # in place of Unlink, and it could not reach the cluster to run.
        for status in ALL_STATES:
            for connected in (True, False):
                with self.subTest(status=status, connected=connected):
                    self.assertTrue(should_allow_forget(status, connected))

    def test_not_connected_can_be_forgotten(self):
        self.assertTrue(should_allow_forget(JOB_STATE_NOTCONNECTED, True))
        self.assertTrue(should_allow_forget(JOB_STATE_NOTCONNECTED, False))

    def test_ghost_can_be_forgotten(self):
        self.assertTrue(should_allow_forget(JOB_STATE_GHOST, True))

    def test_idle_can_be_forgotten(self):
        self.assertTrue(should_allow_forget(JOB_STATE_IDLE, True))

    def test_failed_on_unreachable_host_can_be_forgotten(self):
        # A FAILED job never polls, so nothing ever opens a connection for it:
        # without the local removal it stayed in the list forever.
        self.assertFalse(should_allow_cancel(JOB_STATE_FAILED, False))
        self.assertTrue(should_allow_forget(JOB_STATE_FAILED, False))

    def test_running_on_connected_host_offers_both_ways_out(self):
        # Cancel/Delete is the one that frees the cluster, and the menu says so;
        # Unlink stays available but is worded as the last resort.
        self.assertTrue(should_allow_cancel(JOB_STATE_RUNNING, True))
        self.assertTrue(should_allow_forget(JOB_STATE_RUNNING, True))


class TestShouldAllowReconnect(unittest.TestCase):
    def test_offered_whenever_the_host_is_not_connected(self):
        for status in ALL_STATES:
            with self.subTest(status=status):
                self.assertTrue(should_allow_reconnect(status, False))

    def test_failed_job_can_reconnect_to_regain_remote_cancel(self):
        self.assertTrue(should_allow_reconnect(JOB_STATE_FAILED, False))

    def test_offered_for_resumable_states_even_when_connected(self):
        self.assertTrue(should_allow_reconnect(JOB_STATE_IDLE, True))
        self.assertTrue(should_allow_reconnect(JOB_STATE_NOTCONNECTED, True))
        self.assertTrue(should_allow_reconnect(JOB_STATE_GHOST, True))

    def test_offered_for_every_job_that_is_no_longer_polling(self):
        # check_host reports whether a client is cached, not whether it works,
        # and a job in one of these states never polls again -- so nothing ever
        # revalidates that client. Greying Reconnect out on its word left a
        # FAILED row with no way to reach its host.
        for status in (JOB_STATE_FAILED, JOB_STATE_COMPLETED, JOB_STATE_CANCELLED, JOB_STATE_DONE):
            with self.subTest(status=status):
                self.assertTrue(should_allow_reconnect(status, True))

    def test_not_offered_for_a_polling_job_on_a_connected_host(self):
        # Still following its remote job over a connection we hold: there is
        # nothing to reconnect.
        self.assertFalse(should_allow_reconnect(JOB_STATE_RUNNING, True))
        self.assertFalse(should_allow_reconnect(JOB_STATE_PENDING, True))


class TestJobUpdateBuffer(unittest.TestCase):
    """The observer runs on the JobManager monitor thread, not the main one."""

    def setUp(self):
        _drainPendingUpdates()

    def tearDown(self):
        _drainPendingUpdates()

    def _job(self, uid):
        job = MagicMock()
        job.uid = uid
        return job

    def test_the_observer_never_reaches_into_slicer(self):
        # It used to fetch the logic through
        # slicer.modules.jobmonitor.widgetRepresentation(), calling into the
        # module manager -- and so into Qt -- from the monitor thread. Racing
        # that against the main thread killed the application with an X
        # BadWindow abort and no Python traceback. Removing the name entirely
        # is the only assertion that stays true as the function changes.
        import modules.JobMonitor.JobMonitor as module

        job = self._job("a")
        with patch.object(module, "slicer", None):
            _listener(job, "JOB_MODIFIED")

        self.assertEqual(_drainPendingUpdates(), [(job, "JOB_MODIFIED")])

    def test_draining_empties_the_buffer(self):
        _listener(self._job("a"), "JOB_MODIFIED")

        self.assertEqual(len(_drainPendingUpdates()), 1)
        self.assertEqual(_drainPendingUpdates(), [])

    def test_only_the_latest_event_per_job_survives(self):
        # One redraw per job per tick, however often the monitor polls.
        job = self._job("a")
        _listener(job, "JOB_MODIFIED")
        _listener(job, "JOB_DELETED")

        self.assertEqual(_drainPendingUpdates(), [(job, "JOB_DELETED")])

    def test_jobs_are_buffered_independently(self):
        _listener(self._job("a"), "JOB_MODIFIED")
        _listener(self._job("b"), "JOB_MODIFIED")

        self.assertEqual(len(_drainPendingUpdates()), 2)


class TestPartitionByCancellable(unittest.TestCase):
    """Which of the visible jobs the bulk Cancel/Delete may actually touch."""

    @staticmethod
    def connected(_host):
        return True

    @staticmethod
    def disconnected(_host):
        return False

    def test_running_jobs_on_a_connected_host_are_deletable(self):
        jobs = [make_job(uid="a", status=JOB_STATE_RUNNING), make_job(uid="b", status=JOB_STATE_COMPLETED)]

        deletable, blocked = partition_by_cancellable(jobs, self.connected)

        self.assertEqual([job.uid for job in deletable], ["a", "b"])
        self.assertEqual(blocked, [])

    def test_an_unreachable_host_blocks_everything(self):
        # Cancel/Delete is a remote operation; without a connection there is
        # nothing it can do, so those rows are left listed rather than removed.
        jobs = [make_job(uid="a", status=JOB_STATE_RUNNING), make_job(uid="b", status=JOB_STATE_COMPLETED)]

        deletable, blocked = partition_by_cancellable(jobs, self.disconnected)

        self.assertEqual(deletable, [])
        self.assertEqual([job.uid for job in blocked], ["a", "b"])

    def test_states_that_no_longer_mirror_the_cluster_are_blocked(self):
        jobs = [
            make_job(uid="running", status=JOB_STATE_RUNNING),
            make_job(uid="idle", status=JOB_STATE_IDLE),
            make_job(uid="ghost", status=JOB_STATE_GHOST),
            make_job(uid="lost", status=JOB_STATE_NOTCONNECTED),
        ]

        deletable, blocked = partition_by_cancellable(jobs, self.connected)

        self.assertEqual([job.uid for job in deletable], ["running"])
        self.assertEqual([job.uid for job in blocked], ["idle", "ghost", "lost"])

    def test_the_partition_agrees_with_the_per_row_menu(self):
        # The bulk action must never offer to do something a single row would
        # have refused, or the two would disagree in front of the user.
        jobs = [make_job(uid=status, status=status) for status in ALL_STATES]

        for connected in (True, False):
            with self.subTest(connected=connected):
                deletable, blocked = partition_by_cancellable(jobs, lambda _host: connected)

                self.assertEqual(
                    [job.uid for job in deletable],
                    [status for status in ALL_STATES if should_allow_cancel(status, connected)],
                )
                self.assertEqual(len(deletable) + len(blocked), len(jobs))

    def test_an_empty_list_partitions_into_nothing(self):
        self.assertEqual(partition_by_cancellable([], self.connected), ([], []))
