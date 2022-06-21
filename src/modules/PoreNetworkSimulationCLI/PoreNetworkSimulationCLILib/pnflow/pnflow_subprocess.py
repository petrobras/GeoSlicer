import ctypes
import logging
import os
from multiprocessing import Process, Manager
from string import Template
import time

from pnflow import pnflow

PNFLOW_INPUT = Template(
    """TITLE  $output_name;  // base name for the output files

writeStatistics true;

NETWORK  F Image;   // the base name for of the network file, without _link1.dat, _link2, _pore1

//!cycle#  Final Sw        Final Pc       Sw steps          Compute Kr   Compute RI
cycle1:    $enforced_swi_1 $enforced_pc_1 $enforced_steps_1     T            F;
cycle2:    $enforced_swi_2 $enforced_pc_2 $enforced_steps_2     T            F;
${run_third_cycle}cycle3:    $enforced_swi_1 $enforced_pc_1 $enforced_steps_1     T            F;

//!cycle#       Inject from                    Produce from                  Boundary-condition
//!        Left           Right            Left            Right            Type   Water  Oil
cycle1_BC: $inject_1_left $inject_1_right  $produce_1_left $produce_1_right  DP    1.00   2.00;
cycle2_BC: $inject_2_left $inject_2_right  $produce_2_left $produce_2_right  DP    2.00   1.00;
${run_third_cycle}cycle3_BC:  $inject_1_left $inject_1_right  $produce_1_left $produce_1_right  DP    1.00   2.00;

//!       x[range]
CALC_BOX: $calc_box_lower_boundary $calc_box_upper_boundary; //!bounding box for computing rel-permss

//!            model                min                      max                       delta                      gamma                     RCtrl                        Mdl2Sep
INIT_CONT_ANG: $init_contact_model  $init_contact_angle_min  $init_contact_angle_max   $init_contact_angle_del    $init_contact_angle_eta   $init_contact_angle_rctrl    $init_contact_angle_separation;
EQUIL_CON_ANG: $equil_contact_model $equil_contact_angle_min $equil_contact_angle_max  $equil_contact_angle_del   $equil_contact_angle_eta  $equil_contact_angle_rctrl   $equil_contact_angle_separation;

//!          fraction                  min                        max                        delta                       gamma                      RCtrl
2ND_CON_ANG: $second_contact_fraction  $second_contact_angle_min  $second_contact_angle_max  $second_contact_angle_del   $second_contact_angle_eta  $second_contact_angle_rctrl;

//!            fraction              volBased              min              max              delta              gamma              method               corrDiam
FRAC_CON_ANG:  $frac_contact_angle_fraction $frac_contact_angle_volbased $frac_contact_angle_min $frac_contact_angle_max $frac_contact_angle_del $frac_contact_angle_eta $frac_contact_method  $frac_contact_angle_corrdiam

//     viscosity(Pa.s)   resistivity(Ohm.m)  density(kg/m3)
Water  $water_viscosity  1  $water_density;
Oil    $oil_viscosity    1    $oil_density;
ClayResistivity          1

WaterOilInterface        $interfacial_tension;  // interfacial tension (N/m)

DRAIN_SINGLETS: T;   // T for yes, F for no. singlets are dead-end pores

visuaLight  T        T          T         F          T ;

PORE_FILL_ALG: $pore_fill_algorithm;
PORE_FILL_WGT: $pore_fill_weight_a1 $pore_fill_weight_a2 $pore_fill_weight_a3 $pore_fill_weight_a4 $pore_fill_weight_a5 $pore_fill_weight_a6;

OUTPUT T $enable_vtu_output;
"""
)


def _write_data(file: str, data: str) -> None:
    try:
        file = open(file, "w")
        file.write(data)
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        if file:
            file.close()


class PnFlowSubprocess:
    def __init__(
        self,
        manager: Manager,
        params: dict,
        cwd: str,
        link1: str,
        link2: str,
        node1: str,
        node2: str,
        id: int,
        write_debug_files: bool,
    ):
        self.manager = manager
        self.params = params
        self.cwd = cwd
        self.link1 = link1
        self.link2 = link2
        self.node1 = node1
        self.node2 = node2
        self.process = None
        self.id = id
        self.write_debug_files = write_debug_files

        self.input_string = PNFLOW_INPUT.substitute(
            output_name="Output", enable_vtu_output=params["create_sequence"], **params
        )
        self.start_time = 0
        self.run_count = 0

    def start(self):
        self.result = self.manager.Value(ctypes.c_char_p, "")
        self.process = Process(
            target=self.pnflow_caller,
            args=(
                self.result,
                self.cwd,
                self.input_string,
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

    @staticmethod
    def pnflow_caller(result, cwd, input_string, link1, link2, node1, node2, write_debug_files=False):
        os.chdir(cwd)
        if write_debug_files:
            _write_data("input.txt", input_string)
            _write_data("Image_link1.dat", link1)
            _write_data("Image_link2.dat", link2)
            _write_data("Image_node1.dat", node1)
            _write_data("Image_node2.dat", node2)
        result.value = pnflow(input_string, link1, link2, node1, node2)

    def terminate(self):
        self.process.terminate()
        self.process.join()
        self.start_time = 0

    def get_result(self):
        return self.result.value

    def is_finished(self):
        if not self.process.is_alive():
            return True
        return False

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
