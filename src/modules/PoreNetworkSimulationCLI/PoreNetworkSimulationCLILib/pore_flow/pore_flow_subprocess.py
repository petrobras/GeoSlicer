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
        link1: str,
        link2: str,
        node1: str,
        node2: str,
        id: int,
        write_debug_files: bool,
    ):
        super().__init__(
            params,
            cwd,
            link1,
            link2,
            node1,
            node2,
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

    @staticmethod
    def caller(cwd, params_in, link1, link2, node1, node2, write_debug_files=False):
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
            "drainage_sw_step": params["enforced_steps_1"],
            "imbibition_sw_step": params["enforced_steps_2"],
        }

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

        generate_vtu = params["create_sequence"] == "T"

        pn = openpnm.io.network_from_statoil(".", "Image")

        if write_debug_files:
            ppf.log.configure(output=ppf.log.FILE, level=ppf.log.INFO)
        else:
            ppf.log.configure(level=ppf.log.WARNING)
        cycle, Pc, Sw, Krw, Kro = ppf.run_two_phase_simulation(pn, py_pore_flow_parameters, generate_vtu=generate_vtu)
        result_string = json.dumps(
            {"cycle": cycle.tolist(), "Pc": Pc.tolist(), "Sw": Sw.tolist(), "Krw": Krw.tolist(), "Kro": Kro.tolist()}
        )

        if params["create_ca_distributions"]:
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
