import io
import json
import numpy as np
import os
from pathlib import Path
from string import Template

import openpnm

import py_pore_flow as ppf
from PoreNetworkSimulationCLILib.two_phase.two_phase_subprocess import TwoPhaseSubprocess


class PoreFlowSubprocess(TwoPhaseSubprocess):
    def __init__(
        self,
        params: dict,
        cwd: str,
        statoil_data: dict,
        snapshot_file: str,
        id: int,
        write_debug_files: bool,
    ):
        super().__init__(
            params,
            cwd,
            statoil_data,
            snapshot_file,
            id,
            write_debug_files,
        )

    def get_cycle_result(self):
        try:
            with open(str(Path(self.cwd) / "result.txt"), "r") as file:
                cycle_results = json.load(file)
        except Exception as e:
            cycle_results = {"cycle": [], "Sw": [], "Pc": [], "Krw": [], "Kro": [], "RI": []}
        return cycle_results

    def get_snapshot_file(self):
        if self.params["create_drainage_snapshot"] == "T":
            return str(Path(self.cwd) / "snapshot.bin")
        else:
            return None

    @staticmethod
    def caller(cwd, params_in, statoil_data, snapshot_file=None, write_debug_files=False):
        link1 = statoil_data["link1"]
        link2 = statoil_data["link2"]
        link3 = statoil_data["link3"]
        node1 = statoil_data["node1"]
        node2 = statoil_data["node2"]
        node3 = statoil_data["node3"]

        params = params_in.copy()
        os.chdir(cwd)

        py_pore_flow_parameters = {
            "seed": int(params["seed"]),
            "water_viscosity": params["water_viscosity"] / 1000,
            "water_density": params["water_density"],
            "oil_viscosity": params["oil_viscosity"] / 1000,
            "oil_density": params["oil_density"],
            "interfacial_tension": params["interfacial_tension"] / 1000,
            "initial_ca_center": params["init_contact_angle"],
            "initial_ca_range": params["init_contact_angle_range"],
            "initial_ca_model": int(params["init_contact_model"]),
            "initial_ca_separation": params["init_contact_angle_separation"],
            "initial_ca_correlation": PoreFlowSubprocess.rctrl_to_correlation(params["init_contact_angle_rctrl"]),
            "equilibrium_ca_center": params["equil_contact_angle"],
            "equilibrium_ca_range": params["equil_contact_angle_range"],
            "equilibrium_ca_model": int(params["equil_contact_model"]),
            "equilibrium_ca_separation": params["equil_contact_angle_separation"],
            "equilibrium_ca_correlation": PoreFlowSubprocess.rctrl_to_correlation(params["equil_contact_angle_rctrl"]),
            "second_ca_center": params["frac_contact_angle"],
            "second_ca_range": params["frac_contact_angle_range"],
            "second_ca_fraction": params["frac_contact_angle_fraction"],
            "second_ca_correlation": PoreFlowSubprocess.rctrl_to_correlation(params["frac_contact_angle_rctrl"]),
            "pc_maximum": params["enforced_pc_1"],
            "pc_minimum": params["enforced_pc_2"],
            "drainage_sw_step": params["enforced_steps_1"],
            "imbibition_sw_step": params["enforced_steps_2"],
            "pore_fill_algorithm": params["pore_fill_algorithm"],
            "pore_fill_weight_a1": params["pore_fill_weight_a1"],
            "pore_fill_weight_a2": params["pore_fill_weight_a2"],
            "pore_fill_weight_a3": params["pore_fill_weight_a3"],
            "pore_fill_weight_a4": params["pore_fill_weight_a4"],
            "pore_fill_weight_a5": params["pore_fill_weight_a5"],
            "pore_fill_weight_a6": params["pore_fill_weight_a6"],
            "skip_imbibition": params["skip_imbibition"],
            "skip_2nd_drainage": False,
            "enforced_swi_1": params["enforced_swi_1"],
            "enforced_swi_2": params["enforced_swi_2"],
        }

        generate_vtu = params["create_sequence"] == "T"

        if write_debug_files:
            ppf.log.configure(output=ppf.log.FILE, level=ppf.log.INFO)
        else:
            ppf.log.configure(level=ppf.log.WARNING)

        if snapshot_file is not None:
            pn, parameters, config = ppf.load_snapshot(snapshot_file)
            parameters.update(py_pore_flow_parameters)
            cycle, Pc, Sw, Krw, Kro = ppf.run_two_phase_simulation(
                pn, parameters, generate_vtu=generate_vtu, generate_cas=True, setup_network=False, config=config
            )
        else:
            input_file = open("input.txt", "w")
            link1_file = open("Image_link1.dat", "w")
            link2_file = open("Image_link2.dat", "w")
            node1_file = open("Image_node1.dat", "w")
            node2_file = open("Image_node2.dat", "w")
            input_file.write(json.dumps(py_pore_flow_parameters))
            link1_file.write(link1)
            link2_file.write(link2)
            node1_file.write(node1)
            node2_file.write(node2)
            input_file.close()
            link1_file.close()
            link2_file.close()
            node1_file.close()
            node2_file.close()

            pn = openpnm.io.network_from_statoil(".", "Image")
            pn["pore.N"], pn["throat.N"] = PoreFlowSubprocess.__get_n_from_statoil(pn, link3, node3)

            if params["create_drainage_snapshot"] == "T":
                drainage_snapshot_pc = "final"
            else:
                drainage_snapshot_pc = None

            cycle, Pc, Sw, Krw, Kro = ppf.run_two_phase_simulation(
                pn, py_pore_flow_parameters, generate_vtu=generate_vtu, drainage_snapshot_pc=drainage_snapshot_pc
            )
        result_string = json.dumps(
            {"cycle": cycle.tolist(), "Pc": Pc.tolist(), "Sw": Sw.tolist(), "Krw": Krw.tolist(), "Kro": Kro.tolist()}
        )

        if params["create_ca_distributions"] == "T":
            ca_distribution = {
                "drainage": {
                    "advancing_ca": np.degrees(
                        np.concatenate(
                            (
                                pn["pore.initial_advancing_ca"],
                                pn["throat.initial_advancing_ca"],
                            )
                        )
                    ).tolist(),
                    "receding_ca": np.degrees(
                        np.concatenate(
                            (
                                pn["pore.initial_receding_ca"],
                                pn["throat.initial_receding_ca"],
                            )
                        )
                    ).tolist(),
                },
                "imbibition": {
                    "advancing_ca": np.degrees(
                        np.concatenate(
                            (
                                pn["pore.equilibrium_advancing_ca"],
                                pn["throat.equilibrium_advancing_ca"],
                            )
                        )
                    ).tolist(),
                    "receding_ca": np.degrees(
                        np.concatenate(
                            (
                                pn["pore.equilibrium_receding_ca"],
                                pn["throat.equilibrium_receding_ca"],
                            )
                        )
                    ).tolist(),
                },
            }
            with open("ca_distribution.json", "w") as fp:
                json.dump(ca_distribution, fp)

        with open("result.txt", "w") as result_file:
            result_file.write(result_string)

    @staticmethod
    def rctrl_to_correlation(rctrl):
        if rctrl == "rand":
            return ppf.UNCORRELATED
        elif rctrl == "rMin":
            return ppf.NEGATIVE_RADIUS
        elif rctrl == "rMax":
            return ppf.POSITIVE_RADIUS

    @staticmethod
    def __get_n_from_statoil(pn, link3, node3):
        pore_N_array = PoreFlowSubprocess.__get_pores_n_from_statoil(pn, node3)
        throat_N_array = PoreFlowSubprocess.__get_throats_n_from_statoil(pn, link3)

        return pore_N_array, throat_N_array

    @staticmethod
    def __get_pores_n_from_statoil(pn, node3):
        number_of_pores = len(pn["pore.all"])

        lines = node3.strip().split("\n")
        id_list = []
        N_list = []
        for line in lines:
            splitted = line.split()
            id_list.append(int(splitted[0]))
            N_list.append(float(splitted[1]))
        id_list = np.array(id_list)
        N_list = np.array(N_list)

        pore_N_array = np.full(number_of_pores, 1.0, np.float64)
        pore_N_array[id_list - 1] = N_list

        return pore_N_array

    @staticmethod
    def __get_throats_n_from_statoil(pn, link3):
        number_of_throats = len(pn["throat.all"])

        lines = link3.strip().split("\n")
        id_list = []
        N_list = []
        for line in lines:
            splitted = line.split()
            id = int(splitted[0])
            if id <= number_of_throats:
                id_list.append(id)
                N_list.append(float(splitted[3]))
        id_list = np.array(id_list)
        N_list = np.array(N_list)

        throat_N_array = np.full(number_of_throats, 1.0, np.float64)
        throat_N_array[id_list - 1] = N_list
        return throat_N_array
