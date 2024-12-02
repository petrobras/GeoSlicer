from abc import abstractmethod
import ctypes
from multiprocessing import Process
import time


class TwoPhaseSubprocess:
    def __init__(
        self,
        params: dict,
        cwd: str,
        link1: str,
        link2: str,
        node1: str,
        node2: str,
        id: int,
        write_debug_files: bool,
    ):
        self.params = self._process_parameters(params)
        self.cwd = cwd
        self.link1 = link1
        self.link2 = link2
        self.node1 = node1
        self.node2 = node2
        self.process = None
        self.id = id
        self.write_debug_files = write_debug_files
        self.result = None

        self.start_time = 0
        self.run_count = 0

    def start(self):
        self.process = Process(
            target=self.caller,
            args=(
                self.cwd,
                self.params,
                self.link1,
                self.link2,
                self.node1,
                self.node2,
                self.write_debug_files,
            ),
        )
        self.start_time = time.time()
        self.run_count += 1
        self.process.start()

    def terminate(self):
        if self.process.is_alive():
            self.process.kill()
            self.process.join(5)
        self.process.close()
        self.start_time = 0

    def is_finished(self):
        if not self.process.is_alive():
            return True
        return False

    def finish(self):
        self.process.join(5)
        if self.process.is_alive():
            self.terminate()

    def uptime(self) -> float:
        """
        Return duration of the process since started in seconds
        """
        if self.start_time != 0:
            return time.time() - self.start_time
        else:
            return -1

    def get_run_count(self) -> int:
        """
        Get how many times this subprocess was started.
        """
        return self.run_count

    def get_id(self) -> int:
        return self.id

    def _process_parameters(self, params):
        return params

    @abstractmethod
    def get_cycle_result(self):
        pass

    @staticmethod
    @abstractmethod
    def caller(cwd, input_string, link1, link2, node1, node2, write_debug_files=False):
        pass
