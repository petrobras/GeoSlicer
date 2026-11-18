from unittest.mock import MagicMock

import pytest

from commons.remote.utils import is_benign_scancel_error, try_scancel


@pytest.mark.parametrize(
    "stderr",
    [
        "",
        "   \n  ",
        "scancel: error: Kill job error on job id 1234: Invalid job id specified",
        "scancel: error: Kill job error on job id 1234: Job/step already completing or completed",
        "scancel: error: Invalid job id specified\nscancel: error: Invalid job id specified",
    ],
)
def test_stderr_that_only_says_the_job_is_already_gone_is_benign(stderr):
    assert is_benign_scancel_error(stderr) is True


@pytest.mark.parametrize(
    "stderr",
    [
        "scancel: error: Kill job error on job id 1234: Access/permission denied",
        "scancel: error: Unable to contact slurm controller (connect failure)",
        # A single real error among benign ones must not be swallowed
        "scancel: error: Invalid job id specified\nscancel: error: Access/permission denied",
    ],
)
def test_real_failures_are_not_benign(stderr):
    assert is_benign_scancel_error(stderr) is False


def test_no_job_ids_is_nothing_to_cancel():
    assert try_scancel(MagicMock(), []) is None
    assert try_scancel(MagicMock(), None) is None
    assert try_scancel(MagicMock(), ["", "  "]) is None


def test_missing_client_is_reported_instead_of_crashing():
    # Used to raise AttributeError on client.run_command, which the caller read
    # as a cancellation failure and turned into an unremovable entry.
    reason = try_scancel(None, ["1234"])

    assert reason and "No connection" in reason


def test_already_finished_job_counts_as_cancelled():
    """The reported trap: cancelling a job whose slurm ids are already gone
    flagged it NOT CONNECTED/GHOST over a healthy connection, and the monitor
    then refused to cancel it ever again."""
    client = MagicMock()
    client.run_command.return_value = {
        "stdout": "",
        "stderr": "scancel: error: Kill job error on job id 1234: Invalid job id specified",
    }

    assert try_scancel(client, ["1234"]) is None


def test_successful_cancel_reports_nothing():
    client = MagicMock()
    client.run_command.return_value = {"stdout": "", "stderr": ""}

    assert try_scancel(client, ["1234", "1235"]) is None
    client.run_command.assert_called_once_with("scancel 1234,1235")


def test_real_scancel_error_is_reported():
    client = MagicMock()
    client.run_command.return_value = {"stdout": "", "stderr": "scancel: error: Access/permission denied"}

    assert try_scancel(client, ["1234"]) == "scancel: error: Access/permission denied"


def test_broken_connection_is_reported():
    client = MagicMock()
    client.run_command.side_effect = OSError("socket closed")

    reason = try_scancel(client, ["1234"])

    assert reason and "socket closed" in reason


def test_job_ids_are_stringified_and_stripped():
    client = MagicMock()
    client.run_command.return_value = {"stdout": "", "stderr": ""}

    try_scancel(client, [1234, " 1235 ", None])

    client.run_command.assert_called_once_with("scancel 1234,1235")


def test_a_handler_that_never_submitted_has_nothing_to_cancel():
    """Handlers call try_scancel(client, [self.jobid]), and self.jobid is None
    for a job that failed before submitting anything to slurm."""
    client = MagicMock()

    assert try_scancel(client, [None]) is None
    client.run_command.assert_not_called()
