import io
import itertools
import random
import re
import string
import time
from multiprocessing import Manager
from pathlib import Path

from ltrace.slicer.cli_utils import progressUpdate
from .pnflow_subprocess import PnFlowSubprocess

IGNORE_RI = True


class PnFlow:
    def __init__(self, cwd: Path, statoil_dict: dict, params: dict, num_tests: int):
        self.cwd = cwd
        self.statoil_file_strings = self.create_statoil_file_strings(statoil_dict)
        self.params_dict = params
        self.num_tests = num_tests
        self.manager = Manager()
        self.subprocess_id_count = 0

    def run_pnflow(self, max_subprocesses=8):
        LOOP_REFRESH_RATE_S = 0.01
        SUBPROCESS_TIMEOUT_S = 1800  # 30min
        SUBPROCESS_RETRY_LIMIT = 0

        params_iterator = self.get_params_iterator(self.params_dict)

        running_pnflow_subprocesses = []
        finished_pnflow_subprocesses = []

        i = 0
        while True:
            # Listening to allocate slots for new processes to be started
            for j, pnflow_subprocess in enumerate(running_pnflow_subprocesses):
                if pnflow_subprocess.is_finished():
                    running_pnflow_subprocesses[j] = None
                    finished_pnflow_subprocesses.append(pnflow_subprocess)
                elif pnflow_subprocess.uptime() > SUBPROCESS_TIMEOUT_S:
                    pnflow_subprocess.terminate()
                    if pnflow_subprocess.get_run_count() < SUBPROCESS_RETRY_LIMIT:
                        pnflow_subprocess.start()
                    else:
                        print(
                            f"error: process {pnflow_subprocess.get_id()} couldn't finish in any of the {SUBPROCESS_RETRY_LIMIT} retries"
                        )
                        running_pnflow_subprocesses[j] = None

            running_pnflow_subprocesses = [p for p in running_pnflow_subprocesses if p is not None]

            # Listening to terminate, cleanup
            for pnflow_subprocess in finished_pnflow_subprocesses:
                pnflow_result = self.create_pnflow_result(
                    pnflow_subprocess.params, pnflow_subprocess.get_result(), pnflow_subprocess.cwd
                )
                pnflow_subprocess.terminate()
                i += 1
                progressUpdate(value=0.1 + (i / self.num_tests) * 0.85)
                yield pnflow_result
            finished_pnflow_subprocesses = []

            # Max running process limiter
            if len(running_pnflow_subprocesses) == max_subprocesses:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Get a new set of parameters
            params = next(params_iterator)

            # Listening to finish or wait processes to finish
            if params is None and len(running_pnflow_subprocesses) == 0 and len(finished_pnflow_subprocesses) == 0:
                break
            if params is None:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Start a new process in the loop if passed all above conditions
            pnflow_subprocess = self.run_pnflow_subprocess(params.copy())
            running_pnflow_subprocesses.append(pnflow_subprocess)
            time.sleep(LOOP_REFRESH_RATE_S)

    def run_pnflow_subprocess(self, params):
        directory_name = self.generate_directory_name(22)
        directory_path = self.cwd / directory_name
        directory_path.mkdir(parents=True, exist_ok=True)
        pnflow_subprocess = PnFlowSubprocess(
            manager=self.manager,
            params=params,
            cwd=str(directory_path),
            link1=self.statoil_file_strings["link1"],
            link2=self.statoil_file_strings["link2"],
            node1=self.statoil_file_strings["node1"],
            node2=self.statoil_file_strings["node2"],
            id=self.subprocess_id_count,
            write_debug_files=self.num_tests == 1,
        )
        self.subprocess_id_count += 1
        pnflow_subprocess.start()
        return pnflow_subprocess

    def generate_directory_name(self, length):
        characters = string.ascii_letters
        directory_name = "".join(random.choices(characters, k=length))
        return directory_name

    def create_pnflow_result(self, params, result, cwd):
        cycle_results = {"cycle": [], "Sw": [], "Pc": [], "Krw": [], "Kro": [], "RI": []}
        file = io.StringIO(result)

        for line in file:
            if "cycle" in line:
                cycle_n = re.search(r"cycle(\d+):", line).group(1)
                for sub_line in file:
                    if sub_line.strip() == "":
                        break
                    if "//" in sub_line:
                        continue
                    values = [float(i.strip()) for i in sub_line.strip().split("\t")]
                    if len(values) < 5:
                        continue
                    if values[2] < 0 or values[2] > 1 or values[3] < 0 or values[3] > 1:
                        continue
                    cycle_results["cycle"].append(int(cycle_n))
                    cycle_results["Sw"].append(values[0])
                    cycle_results["Pc"].append(values[1])
                    cycle_results["Krw"].append(values[2])
                    cycle_results["Kro"].append(values[3])
                    cycle_results["RI"].append(values[4])

        if IGNORE_RI:
            del cycle_results["RI"]

        return {"input_params": params, "pnflow_table": cycle_results, "cwd": cwd}

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
            yield mutable_params

        while True:
            yield None
