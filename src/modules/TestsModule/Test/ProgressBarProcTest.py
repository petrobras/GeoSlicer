import json
import os

from commons.slicer_utils import LTracePluginTest
from commons.utils.ProgressBarProc import ProgressBarProc


class ProgressBarProcTest(LTracePluginTest):
    """Lifecycle and IPC contract of ProgressBarProc.

    ProgressBarProc spawns a subprocess (ProgressBarWidget) that shows a
    "Processing..." window during long operations. The tests assert the
    observable contract only: child process lifecycle, the JSON blob the
    parent writes to the shared region, and cleanup on normal and
    exceptional exits. They do not depend on the specific IPC primitive.
    """

    @staticmethod
    def _read_shared_state(pb):
        raw = bytes(pb.sharedMem[:])
        head = raw.split(b"\x00", 1)[0]
        return json.loads(head) if head else {}

    def test_subprocess_lifecycle(self):
        """Child is alive inside the with block, gone after."""
        with ProgressBarProc() as pb:
            proc = pb.proc
            self.assertIsNone(proc.poll(), "child should be alive inside the with block")
        self.assertIsNotNone(proc.poll(), "child should have exited after the with block")

    def test_state_writes_are_readable(self):
        """setTitle/setMessage/setProgress produce a JSON blob readable from the shared region."""
        with ProgressBarProc() as pb:
            pb.setTitle("TestTitle")
            pb.setMessage("TestMessage")
            pb.setProgress(73)
            state = self._read_shared_state(pb)
            self.assertEqual(state["title"], "TestTitle")
            self.assertEqual(state["message"], "TestMessage")
            self.assertEqual(state["progress"], 73)

    def test_cleanup_on_exception(self):
        """An exception inside the with block still terminates the child."""
        proc = None
        try:
            with ProgressBarProc() as pb:
                proc = pb.proc
                pb.setProgress(1)
                raise RuntimeError("intentional")
        except RuntimeError:
            pass
        self.assertIsNotNone(proc.poll(), "child should have exited after an exception in the with block")

    def test_sequential_instances(self):
        """Two ProgressBarProc instances back-to-back work; no stale-state lockout."""
        with ProgressBarProc() as pb1:
            pb1.setProgress(10)
        with ProgressBarProc() as pb2:
            pb2.setProgress(90)
            state = self._read_shared_state(pb2)
            self.assertEqual(state["progress"], 90)

    def test_no_orphan_subprocess(self):
        """After __exit__, the whole widget process tree must be gone.

        On Windows sys.executable is a wrapper that spawns python-real.exe as
        a grandchild; if the grandchild survives it holds the shm file open
        and os.unlink fails. So a successful unlink proves the process tree
        is fully terminated.
        """
        with ProgressBarProc() as pb:
            shmPath = pb._shmPath
            self.assertTrue(os.path.exists(shmPath))
        self.assertFalse(
            os.path.exists(shmPath),
            f"Temp file {shmPath} still exists after __exit__ — widget subprocess was not cleaned up",
        )
