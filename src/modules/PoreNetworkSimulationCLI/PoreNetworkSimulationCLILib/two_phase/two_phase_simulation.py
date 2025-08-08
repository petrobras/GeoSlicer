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
        snapshot_file: str,
        params: dict,
        timeout_enabled: bool,
        write_debug_files: bool,
        sim_interval: tuple = (0, None),
    ):
        self.cwd = cwd
        self.statoil_file_strings = self.create_statoil_file_strings(statoil_dict)
        self.snapshot_file = snapshot_file
        self.params_dict = params
        self.sim_interval = sim_interval
        self.timeout_enabled = timeout_enabled
        self.subprocess_id_count = 0
        self.subprocess_timeout_s = 0.1 * (len(statoil_dict["node1"]) + len(statoil_dict["link1"]))
        self.simulator_class = PnflowSubprocess
        self.simulator = PNFLOW
        self.write_debug_files = write_debug_files
        self.params_list = self.get_params_list(self.params_dict)[slice(*sim_interval)]
        self.num_tests = len(self.params_list)

    def set_simulator(self, simulator):
        self.simulator = simulator

    def run(self, max_subprocesses=8):

        # Check if drainage should be reused
        """
        if self.simulator == PORE_FLOW:
            params_group_list = self.__get_unchanged_drainage_parameters(params_list)
            reuse_drainage = True
            for params_group in params_group_list:
                if len(params_group) <= 2 * max_subprocesses:
                    reuse_drainage = False
                    break
        else:
            reuse_drainage = False
        """
        reuse_drainage = False

        # Perform parallel simulations
        if reuse_drainage:
            drainage_params = []
            for params_group in params_group_list:
                drainage_param = params_group[0].copy()
                drainage_param["create_drainage_snapshot"] = "T"
                drainage_param["skip_imbibition"] = True
                drainage_params.append(drainage_param)

            drainage_result_list = []
            for drainage_result in self.run_simulations(drainage_params, None, max_subprocesses):
                drainage_result_list.append(drainage_result)

            for drainage_result in drainage_result_list:
                params_group = params_group_list[drainage_result["id"]]
                for simulation_result in self.run_simulations(
                    params_group,
                    drainage_result["snapshot"],
                    max_subprocesses,
                ):
                    simulation_result["table"] = self.__merge_results(
                        simulation_result["table"], drainage_result["table"]
                    )
                    yield simulation_result
        else:
            for simulation_result in self.run_simulations(
                self.params_list,
                self.snapshot_file,
                max_subprocesses,
            ):
                yield simulation_result

    def run_simulations(self, params_list, snapshot_file, max_subprocesses=8):
        subprocess_manager = SimulationSubprocessManager(
            self.timeout_enabled,
            self.simulator,
            self.subprocess_timeout_s,
            self.num_tests,
            self.cwd,
            self.write_debug_files,
            self.statoil_file_strings,
        )
        for simulation_result in subprocess_manager.run_simulations(params_list, snapshot_file, max_subprocesses):
            yield simulation_result

    @staticmethod
    def create_statoil_file_strings(statoil_dict):
        output = {}
        for name in ("link1", "link2", "link3", "node1", "node2", "node3"):
            output[name] = "\n".join(statoil_dict[name]) + "\n"
        return output

    @staticmethod
    def get_params_list(params: dict):
        sensibility_variables = {}

        for key, value in params.items():
            if type(value) == list:
                sensibility_variables[key] = value

        combinations = []
        for key, value in sensibility_variables.items():
            combinations.append(itertools.product([key], value))
        combinations = itertools.product(*combinations)

        params_list = []
        for combination in combinations:
            new_params = params.copy()
            for key, value in combination:
                new_params[key] = value
            for i in ("init", "second", "equil", "frac"):
                center = new_params[f"{i}_contact_angle"]
                width = new_params[f"{i}_contact_angle_range"]
                new_params[f"{i}_contact_angle_min"] = max(center - width / 2, 0)
                new_params[f"{i}_contact_angle_max"] = min(center + width / 2, 180)
            center = new_params["frac_cluster_count"]
            width = new_params["frac_cluster_count_range"]
            new_params["frac_cluster_count_min"] = round(max(center - width / 2, 0))
            new_params["frac_cluster_count_max"] = round(center + width / 2)
            params_list.append(new_params)

        return params_list

    def __merge_results(self, simulation_result, drainage_result):
        return {key: simulation_result[key] + drainage_result[key] for key in simulation_result}

    def __get_unchanged_drainage_parameters(self, params_list):
        return self.__group_dictionaries_by_keys(
            params_list,
            ["init_contact_angle", "init_contact_angle_range", "init_contact_angle_min", "init_contact_angle_max"],
        )

    @staticmethod
    def __group_dictionaries_by_keys(dictionary_list, keys):
        grouped = {}
        for dictionary in dictionary_list:
            group_key = tuple(dictionary.get(key) for key in keys)
            if group_key not in grouped:
                grouped[group_key] = []
            grouped[group_key].append(dictionary)
        return list(grouped.values())


class SimulationSubprocessManager:
    def __init__(
        self, timeout_enabled, simulator, subprocess_timeout_s, num_tests, cwd, write_debug_files, statoil_file_strings
    ):
        self.timeout_enabled = timeout_enabled
        self.simulator = simulator
        self.subprocess_timeout_s = subprocess_timeout_s
        self.num_tests = num_tests
        self.cwd = cwd
        self.write_debug_files = write_debug_files
        self.statoil_file_strings = statoil_file_strings

        self.subprocess_id_count = 0

    def run_simulations(self, params_list, snapshot_file, max_subprocesses=8):
        LOOP_REFRESH_RATE_S = 0.01
        SUBPROCESS_RETRY_LIMIT = 0

        params_iterator = iter(params_list)

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
                simulation_result = self.__create_result(
                    subprocess.id,
                    subprocess.params,
                    subprocess.get_cycle_result(),
                    subprocess.cwd,
                    subprocess.get_snapshot_file(),
                )
                i += 1
                progressUpdate(value=0.1 + (i / self.num_tests) * 0.85)
                yield simulation_result
            finished_subprocesses = []

            # Max running process limiter
            if len(running_subprocesses) == max_subprocesses:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Get a new set of parameters
            try:
                params = next(params_iterator)
            except StopIteration:
                params = None

            # Listening to finish or wait processes to finish
            if params is None and len(running_subprocesses) == 0 and len(finished_subprocesses) == 0:
                break
            if params is None:
                time.sleep(LOOP_REFRESH_RATE_S)
                continue

            # Start a new process in the loop if passed all above conditions
            subprocess = self.__run_subprocess(params.copy(), snapshot_file)
            running_subprocesses.append(subprocess)
            time.sleep(LOOP_REFRESH_RATE_S)

    def __run_subprocess(self, params, snapshot_file):
        directory_name = self.__generate_directory_name(22)
        directory_path = self.cwd / directory_name
        directory_path.mkdir(parents=True, exist_ok=True)
        if self.simulator == PNFLOW:
            simulator_class = PnflowSubprocess
        else:
            simulator_class = PoreFlowSubprocess
        subprocess = simulator_class(
            params=params,
            cwd=str(directory_path),
            statoil_data=self.statoil_file_strings,
            snapshot_file=snapshot_file,
            id=self.subprocess_id_count,
            write_debug_files=self.write_debug_files,
        )
        self.subprocess_id_count += 1
        subprocess.start()
        return subprocess

    @staticmethod
    def __create_result(id, params, cycle_results, cwd, snapshot_file):
        return {"id": id, "input_params": params, "table": cycle_results, "cwd": cwd, "snapshot": snapshot_file}

    @staticmethod
    def __generate_directory_name(length):
        characters = string.ascii_letters
        directory_name = "".join(random.choices(characters, k=length))
        return directory_name
