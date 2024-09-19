import ctypes
import os
import queue
import threading
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

//!             fraction                     volBased                     totalFrac spatialDistrib        oilInWCluster  clustDiam1              clustDiam2              delta                   eta                     wbClustr.cor
FRAC_CONT_OPT:  $frac_contact_angle_fraction $frac_contact_angle_volbased T         $frac_contact_method  $oilInWCluster $frac_cluster_count_min $frac_cluster_count_max $frac_cluster_count_del $frac_cluster_count_eta $frac_cluster_count_rctrl;

//!             model               min                     max                     delta                   gamma                   RCtrl
FRAC_CONT_ANG:  $frac_contact_model $frac_contact_angle_min $frac_contact_angle_max $frac_contact_angle_del $frac_contact_angle_eta $frac_contact_angle_rctrl;

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
        self.params = self._process_parameters(params)
        self.cwd = cwd
        self.link1 = link1
        self.link2 = link2
        self.node1 = node1
        self.node2 = node2
        self.process = None
        self.id = id
        self.write_debug_files = write_debug_files

        self.input_string = PNFLOW_INPUT.substitute(
            output_name="Output", enable_vtu_output=self.params["create_sequence"], **self.params
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
            input_file = open("input.txt", "w")
            link1_file = open("Image_link1.dat", "w")
            link2_file = open("Image_link2.dat", "w")
            node1_file = open("Image_node1.dat", "w")
            node2_file = open("Image_node2.dat", "w")
            input_file.write(input_string)
            link1_file.write(link1)
            link2_file.write(link2)
            node1_file.write(node1)
            node2_file.write(node2)
            input_file.close()
            link1_file.close()
            link2_file.close()
            node1_file.close()
            node2_file.close()

        # Creating a thread to set a larger stack size and avoid pnflow stack overflow
        threading.stack_size(0x800000)
        result_queue = queue.Queue()
        thread = threading.Thread(
            target=PnFlowSubprocess.pnflow_thread, args=(input_string, link1, link2, node1, node2, result_queue)
        )
        thread.start()
        result.value = result_queue.get()

    @staticmethod
    def pnflow_thread(input_string, link1, link2, node1, node2, result_queue):
        result = pnflow(input_string, link1, link2, node1, node2)
        result_queue.put(result)

    def _process_parameters(self, params):
        params_copy = params.copy()
        params_copy["interfacial_tension"] = params_copy["interfacial_tension"] / 1000
        params_copy["water_viscosity"] = params_copy["water_viscosity"] / 1000
        params_copy["oil_viscosity"] = params_copy["oil_viscosity"] / 1000
        return params_copy

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
