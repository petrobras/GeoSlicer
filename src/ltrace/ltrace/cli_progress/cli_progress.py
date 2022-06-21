import datetime
import os
import pickle
import time
import zmq
from collections import namedtuple
from pathlib import Path
from queue import Queue, Empty
from threading import Thread


class IPCThread(Thread):
    def __init__(self, zmq_port=None):
        Thread.__init__(self)
        self.to_send = Queue()
        self.received = Queue()
        self.should_stop = False
        self.received_callback = None
        self.zmq_port = zmq_port

    def run(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PAIR)

        if self.zmq_port is None:
            self.zmq_port = self.socket.bind_to_random_port("tcp://*", min_port=49152, max_port=65535, max_tries=100)
        else:
            self.socket.connect("tcp://localhost:{}".format(self.zmq_port))

        self.socket_poller = zmq.Poller()
        self.socket_poller.register(self.socket, zmq.POLLIN)

        while not self.should_stop:
            event_to_send = try_get_from_queue(self.to_send)
            while event_to_send is not None:
                self.socket.send(pickle.dumps(event_to_send))
                event_to_send = try_get_from_queue(self.to_send)

            ready_sockets = self.socket_poller.poll(50)  # 50ms
            if not ready_sockets:
                continue

            assert len(ready_sockets) == 1
            _, ready_events = ready_sockets[0]

            for _ in range(ready_events):
                event = pickle.loads(self.socket.recv())
                if self.received_callback is not None:
                    self.received_callback(event)
                else:
                    self.received.put(event)

        event_to_send = try_get_from_queue(self.to_send)
        while event_to_send is not None:
            self.socket.send(pickle.dumps(event_to_send))
            event_to_send = try_get_from_queue(self.to_send)

    def get_port(self):
        while self.zmq_port is None:
            time.sleep(0.01)
        return self.zmq_port

    def stop(self):
        self.should_stop = True
        self.join()

    def send(self, *args, **kwargs):
        if self.should_stop:
            raise RuntimeError("IPCThread already closing")
        self.to_send.put(*args, **kwargs)

    def try_receive(self, *args, **kwargs):
        if self.should_stop and self.received.empty():
            raise RuntimeError("IPCThread already closing")

        return try_get_from_queue(self.received)

    def receive(self):
        if self.should_stop and self.received.empty():
            raise RuntimeError("IPCThread already closing")

        return self.received.get(block=True, timeout=-1)

    def register_received_callback(self, callback):
        self.received_callback = callback


def try_get_from_queue(q):
    try:
        return q.get(block=True, timeout=0.05)  # 50ms
    except Empty:
        return None


class ProgressBarClient(object):
    def __init__(self, zmq_port):
        self.steps = 0
        self.current_value = 0
        self.should_stop = False

        self.ipc_thread = IPCThread(zmq_port)
        self.ipc_thread.register_received_callback(self._stop)
        self.ipc_thread.start()

    def configure(self, steps, initial_message):
        self.steps = steps
        self.ipc_thread.send(ConfigureEvent(steps, initial_message))

    def progress(self, value, message):
        if self.current_value > value:
            raise RuntimeError(
                "Progress must always increase. Current: {}, Passed: {}".format(self.current_value, value)
            )

        self.current_value = value
        self.ipc_thread.send(ProgressEvent(value, message))

    def error(self, message):
        self.ipc_thread.send(ErrorEvent(message))

    def next_progress_step(self):
        return int(self.current_value + 1)

    def _send_event(self, event):
        self.socket.send(pickle.dumps(event))

    def _stop(self, event):
        if not isinstance(event, StopEvent):
            raise RuntimeError("Unknown event: ", event)

        self.should_stop = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        handled = False
        if isinstance(exc_val, StoppedError):
            self.error("Stopped")
            handled = True
        elif isinstance(exc_val, RuntimeError):
            self.error(str(exc_val))
            handled = True

        self.ipc_thread.stop()
        return handled


class StoppedError(RuntimeError):
    pass


ConfigureEvent = namedtuple("ConfigureEvent", "steps initial_message")
ProgressEvent = namedtuple("ProgressEvent", "value message")
StopEvent = namedtuple("StopEvent", "")
ErrorEvent = namedtuple("ErrorEvent", "message")


def RunCLIWithProgressBar(module, parameters, title=""):
    import qt
    import slicer

    ipc_thread = IPCThread()
    ipc_thread.start()
    port = ipc_thread.get_port()

    progress_dialog = qt.QProgressDialog()
    progress_dialog.setWindowModality(qt.Qt.WindowModal)
    progress_dialog.setWindowTitle(title if title else "Running")
    progress_dialog.setLabelText("Starting")
    progress_dialog.setCancelButtonText("Stop")

    progress_dialog.setRange(0, 1000)

    def stop():
        progress_dialog.show()
        cancel_button = progress_dialog.findChild(qt.QPushButton)
        progress_dialog.setLabelText("Stopping")
        cancel_button.setEnabled(False)
        ipc_thread.send(StopEvent())

    progress_dialog.canceled.connect(stop)

    progress_dialog.show()

    parameters["zmq_port"] = port
    node = slicer.cli.run(module, parameters=parameters, wait_for_completion=False, update_display=False)

    while node.IsBusy() or not ipc_thread.received.empty():
        qt.QApplication.instance().processEvents()
        event = ipc_thread.try_receive()

        if event is None:
            continue

        if not progress_dialog.wasCanceled:
            if isinstance(event, ConfigureEvent):
                progress_dialog.setRange(0, event.steps * 10)
                progress_dialog.setLabelText(event.initial_message)
            elif isinstance(event, ProgressEvent):
                progress_dialog.setValue(int(event.value * 10))
                progress_dialog.setLabelText(event.message)

        if isinstance(event, ErrorEvent):
            progress_dialog.hide()
            ipc_thread.stop()
            progress_dialog.setValue(progress_dialog.maximum)
            return False, event.message

    progress_dialog.setValue(progress_dialog.maximum)
    return True, ""
