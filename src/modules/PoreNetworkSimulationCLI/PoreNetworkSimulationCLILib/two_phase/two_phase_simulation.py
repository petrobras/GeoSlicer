import itertools
from pathlib import Path
import random
import string
import time

from ltrace.slicer.cli_utils import progressUpdate
from PoreNetworkSimulationCLILib.pnflow.pnflow_subprocess import PnflowSubprocess
from PoreNetworkSimulationCLILib.pore_flow.pore_flow_subprocess import PoreFlowSubprocess


PNFLOW = 0
PORE_FLOW = 1


class TwoPhaseSimulation:
    def __init__(
        self,
        cwd: Path,
        statoil_dict: dict,
        params: dict,
        num_tests: int,
        timeout_enabled: bool,
        write_debug_files: bool,
    ):
        self.cwd = cwd
        self.statoil_file_strings = self.create_statoil_file_strings(statoil_dict)
        self.params_dict = params
        self.num_tests = num_tests
        self.timeout_enabled = timeout_enabled
        self.subprocess_id_count = 0
        self.subprocess_timeout_s = 0.1 * (len(statoil_dict["node1"]) + len(statoil_dict["link1"]))
        self.simulator_class = PnflowSubprocess
        self.simulator = PNFLOW
        self.write_debug_files = write_debug_files

    def set_simulator(self, simulator):
        self.simulator = simulator

    def run(self, max_subprocesses=8):
        LOOP_REFRESH_RATE_S = 0.01
        SUBPROCESS_RETRY_LIMIT = 0

        params_iterator = self.get_params_iterator(self.params_dict)

        running_subprocesses = []
        finished_subprocesses = []

        i = 0
        while True:
            # Listening to allocate slots for new processes to be started
            for j, subprocess in enumerate(running_subprocesses):
                if subprocess.is_finished():
                    running_subprocesses[j] = None
                    finished_subprocesses.append(subprocess)
                elif (
                    self.timeout_enabled
                    and self.simulator == PNFLOW
                    and (subprocess.uptime() > self.subprocess_timeout_s)
                ):
                    subprocess.terminate()
                    if subprocess.get_run_count() < SUBPROCESS_RETRY_LIMIT:
                        subprocess.start()
                    else:
                        print(
                            f"timeout: process {subprocess.get_id()} couldn't finish in any of the {SUBPROCESS_RETRY_LIMIT} retries"
                        )
                        running_subprocesses[j] = None

            running_subprocesses = [p for p in running_subprocesses if p is not None]

            # Listening to terminate, cleanup
            for subprocess in finished_subprocesses:
                subprocess.finish()
                simulation_result = self.create_result(subprocess.params, subprocess.get_cycle_result(), subprocess.cwd)
                i += 1
                progressUpdate(value=0.1 + (i / self.num_tests) * 0.85)
                yield simulation_result
            finished_subprocesses = []

            # Max running process limiter
            if len(running_subprocesses) == max_subprocesses:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Get a new set of parameters
            params = next(params_iterator)

            # Listening to finish or wait processes to finish
            if params is None and len(running_subprocesses) == 0 and len(finished_subprocesses) == 0:
                break
            if params is None:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Start a new process in the loop if passed all above conditions
            subprocess = self.run_subprocess(params.copy())
            running_subprocesses.append(subprocess)
            time.sleep(LOOP_REFRESH_RATE_S)

    def run_subprocess(self, params):
        directory_name = self.generate_directory_name(22)
        directory_path = self.cwd / directory_name
        directory_path.mkdir(parents=True, exist_ok=True)
        if self.simulator == PNFLOW:
            simulator_class = PnflowSubprocess
        else:
            simulator_class = PoreFlowSubprocess
        subprocess = simulator_class(
            params=params,
            cwd=str(directory_path),
            link1=self.statoil_file_strings["link1"],
            link2=self.statoil_file_strings["link2"],
            node1=self.statoil_file_strings["node1"],
            node2=self.statoil_file_strings["node2"],
            id=self.subprocess_id_count,
            write_debug_files=self.write_debug_files,
        )
        self.subprocess_id_count += 1
        subprocess.start()
        return subprocess

    def generate_directory_name(self, length):
        characters = string.ascii_letters
        directory_name = "".join(random.choices(characters, k=length))
        return directory_name

    def create_result(self, params, cycle_results, cwd):
        return {"input_params": params, "table": cycle_results, "cwd": cwd}

    @staticmethod
    def create_statoil_file_strings(statoil_dict):
        output = {}
        for name in ("link1", "link2", "node1", "node2"):
            output[name] = "\n".join(statoil_dict[name]) + "\n"
        return output

    @staticmethod
    def get_params_iterator(params: dict):
        sensibility_variables = {}

        for key, value in params.items():
            if type(value) == list:
                sensibility_variables[key] = value

        combinations = []
        for key, value in sensibility_variables.items():
            combinations.append(itertools.product([key], value))
        combinations = itertools.product(*combinations)

        mutable_params = params.copy()
        for combination in combinations:
            for key, value in combination:
                mutable_params[key] = value
            for i in ("init", "second", "equil", "frac"):
                center = mutable_params[f"{i}_contact_angle"]
                width = mutable_params[f"{i}_contact_angle_range"]
                mutable_params[f"{i}_contact_angle_min"] = max(center - width / 2, 0)
                mutable_params[f"{i}_contact_angle_max"] = min(center + width / 2, 180)
            center = mutable_params["frac_cluster_count"]
            width = mutable_params["frac_cluster_count_range"]
            mutable_params["frac_cluster_count_min"] = round(max(center - width / 2, 0))
            mutable_params["frac_cluster_count_max"] = round(center + width / 2)
            yield mutable_params

        while True:
            yield None
