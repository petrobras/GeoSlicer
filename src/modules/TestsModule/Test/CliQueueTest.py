import slicer
import qt
import numpy as np

from commons.slicer.cli_queue import CliQueue, CliNodeInformation
from commons.slicer_utils import LTracePluginTest
from commons.slicer.tests.utils import process_events
from unittest.mock import MagicMock, Mock


class CliQueueTest(LTracePluginTest):
    def setUp(self, test_case):
        super().setUp(test_case)
        self.cli_module = slicer.modules.gaussianblurimagefilter

    def _createCliInfo(self, params=None, callback=None, progress_text="Test CLI"):
        if params is None:
            inputVolume = slicer.util.addVolumeFromArray(
                np.random.random((100, 100, 100)).astype(np.int16),
                name="n",
                nodeClassName="vtkMRMLScalarVolumeNode",
            )
            outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "OutputTestVolume")
            params = {
                "inputVolume": inputVolume.GetID(),
                "outputVolume": outputVolume.GetID(),
                "sigma": 0.57,
            }

        """Helper to create a CliNodeInformation for the test CLI module."""
        node = slicer.cli.createNode(self.cli_module, params)
        self.assertIsNotNone(node, "Failed to create CLI node.")
        return CliNodeInformation(
            node=node,
            module=self.cli_module,
            parameters=params or {},
            modified_callback=callback or (lambda x, y, z: None),
            progress_text=progress_text,
        )

    def _waitForQueue(self, queue, timeout_ms=10000):
        """Processes events until the queue is no longer running or a timeout occurs."""
        timer = qt.QElapsedTimer()
        timer.start()
        while queue.is_running():
            process_events()
            if timer.elapsed() > timeout_ms:
                self.fail("Queue did not finish within the timeout period.")

    def test_run_single_node_success(self):
        """Tests running a single successful CLI node."""
        queue = CliQueue()
        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"
        cliInfo = self._createCliInfo()
        queue.add_cli_node(cliInfo)

        successfulMock = MagicMock()
        finishedMock = MagicMock()
        failedMock = MagicMock()

        queue.signal_queue_successful.connect(successfulMock)
        queue.signal_queue_finished.connect(finishedMock)
        queue.signal_queue_failed.connect(failedMock)

        queue.run()
        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"
        self._waitForQueue(queue)

        successfulMock.assert_called_once()
        finishedMock.assert_called_once()
        failedMock.assert_not_called()
        self.assertEqual(cliInfo.node.GetStatus(), cliInfo.node.Completed)
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

    def test_run_multiple_nodes_success(self):
        """Tests running a queue of multiple successful CLI nodes."""
        queue = CliQueue()
        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"
        cliInfo1 = self._createCliInfo(progress_text="Node 1")
        cliInfo2 = self._createCliInfo(progress_text="Node 2")
        queue.add_cli_node(cliInfo1)
        queue.add_cli_node(cliInfo2)

        successfulMock = MagicMock()
        finishedMock = MagicMock()

        queue.signal_queue_successful.connect(successfulMock)
        queue.signal_queue_finished.connect(finishedMock)

        queue.run()
        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"
        self._waitForQueue(queue)

        successfulMock.assert_called_once()
        finishedMock.assert_called_once()
        self.assertEqual(cliInfo1.node.GetStatus(), cliInfo1.node.Completed)
        self.assertEqual(cliInfo2.node.GetStatus(), cliInfo2.node.Completed)
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

    def test_run_node_fails(self):
        """Tests a queue where a node fails."""
        queue = CliQueue()
        # ExecutionModelTour fails if an input file doesn't exist
        invalidParams = {"file_test": "/tmp/non_existent_file_for_ltrace_testing"}
        cliInfo = self._createCliInfo(params=invalidParams)

        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

        queue.add_cli_node(cliInfo)

        failedMock = MagicMock()
        finishedMock = MagicMock()
        successfulMock = MagicMock()

        queue.signal_queue_failed.connect(failedMock)
        queue.signal_queue_finished.connect(finishedMock)
        queue.signal_queue_successful.connect(successfulMock)

        queue.run()
        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"
        self._waitForQueue(queue)

        failedMock.assert_called_once()
        finishedMock.assert_called_once()
        successfulMock.assert_not_called()
        self.assertIsNotNone(queue.get_error_message())
        self.assertEqual(cliInfo.node.GetStatus(), cliInfo.node.CompletedWithErrors)
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

    def test_run_and_cancel(self):
        """Tests cancelling a running queue."""
        queue = CliQueue()
        # Use a real CLI that might take a moment, like Threshold
        thresholder = slicer.modules.thresholdscalarvolume
        inputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        outputVolume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")
        params = {"InputVolume": inputVolume.GetID(), "OutputVolume": outputVolume.GetID()}
        cli_node = slicer.cli.createNode(thresholder, params)

        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

        cliInfo = CliNodeInformation(
            node=cli_node,
            module=thresholder,
            parameters=params,
            progress_text="Thresholding",
            modified_callback=lambda x, y, z: None,
        )
        queue.add_cli_node(cliInfo)

        cancelled_mock = MagicMock()
        finishedMock = MagicMock()

        queue.signal_queue_cancelled.connect(cancelled_mock)
        queue.signal_queue_finished.connect(finishedMock)

        queue.run()
        process_events()
        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"
        queue.Cancel()
        self._waitForQueue(queue)

        cancelled_mock.assert_called_once()
        finishedMock.assert_called_once()
        self.assertIn(cliInfo.node.GetStatusString(), ["Cancelling", "Cancelled"])
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

    def test_add_node_while_running(self):
        """Tests adding a new node to an already running queue."""
        queue = CliQueue()

        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"
        cliInfo1 = self._createCliInfo(progress_text="First")
        cliInfo2 = self._createCliInfo(progress_text="Second")
        queue.add_cli_node(cliInfo1)

        successfulMock = MagicMock()
        finishedMock = MagicMock()
        queue.signal_queue_successful.connect(successfulMock)
        queue.signal_queue_finished.connect(finishedMock)

        queue.run()
        process_events()
        self.assertTrue(queue.is_running())

        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"

        queue.add_cli_node(cliInfo2)  # Add the second one

        self._waitForQueue(queue)

        successfulMock.assert_called_once()
        finishedMock.assert_called_once()
        self.assertEqual(cliInfo1.node.GetStatus(), cliInfo1.node.Completed)
        self.assertEqual(cliInfo2.node.GetStatus(), cliInfo2.node.Completed)
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"

    def test_modified_callback(self):
        """Tests that the modified_callback is invoked during execution."""
        callbackMock = MagicMock()

        queue = CliQueue()
        queueObserverList = queue._CliQueue__current_observer_handlers
        assert len(queueObserverList) == 0, "Expected number of observers to be '0'"
        cliInfo = self._createCliInfo(callback=callbackMock)
        queue.add_cli_node(cliInfo)

        queue.run()
        assert len(queueObserverList) == 1, "Expected number of observers to be '1'"
        self._waitForQueue(queue)

        self.assertGreater(callbackMock.call_count, 0)
        # Check one of the calls' arguments
        last_call_args = callbackMock.call_args_list[-1].args
        self.assertEqual(last_call_args[0], cliInfo.node)
        self.assertEqual(last_call_args[1], "ModifiedEvent")

    def test_progress_label_update(self):
        """Tests that the progress label is updated correctly."""
        mockLabel = Mock(spec=qt.QLabel)
        queue = CliQueue(progress_label=mockLabel)
        cliInfo1 = self._createCliInfo(progress_text="First step")
        cliInfo2 = self._createCliInfo(progress_text="Second step")
        queue.add_cli_node(cliInfo1)
        queue.add_cli_node(cliInfo2)

        queue.run()
        self._waitForQueue(queue)

        # Check calls to setText
        calls = mockLabel.setText.call_args_list
        self.assertIn("Step 1/2: First step", calls[0].args[0])
        self.assertIn("Step 2/2: Second step", calls[1].args[0])

        # Check calls to setVisible
        mockLabel.setVisible.assert_any_call(False)  # Init
        mockLabel.setVisible.assert_any_call(True)  # Run
        self.assertEqual(mockLabel.setVisible.call_args_list[-1].args[0], False)  # Stop

    def test_quick_start_initialization(self):
        """Tests the quick_start functionality on initialization."""
        cliInfo = self._createCliInfo()
        queue = CliQueue(cli_node=cliInfo, quick_start=True)

        self.assertTrue(queue.is_running())
        self._waitForQueue(queue)
        self.assertFalse(queue.is_running())
        self.assertEqual(cliInfo.node.GetStatus(), cliInfo.node.Completed)

    def test_initialization_with_list(self):
        """Tests initializing the queue with a list of nodes."""
        cliInfo1 = self._createCliInfo(progress_text="Node1")
        cliInfo2 = self._createCliInfo(progress_text="Node2")
        queue = CliQueue(cli_node=[cliInfo1, cliInfo2], quick_start=True)

        self.assertTrue(queue.is_running())
        self._waitForQueue(queue)
        self.assertEqual(cliInfo1.node.GetStatus(), cliInfo1.node.Completed)
        self.assertEqual(cliInfo2.node.GetStatus(), cliInfo2.node.Completed)
