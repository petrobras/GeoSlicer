import math
import os
from pathlib import Path
import sys
import time

from joblib import Parallel, delayed
from skopt import Optimizer

from pnflow_parallel import PnFlow


if sys.platform.startswith("linux"):
    PNFLOW_BINARY_PATH = "./pnflow"
else:
    PNFLOW_BINARY_PATH = ".\\pnflow.exe"


class OutputFile:
    def __init__(self, name):
        self.file = open(name, "w")

    def __del__(self):
        if self.file is not None:
            self.file.close()

    def add(self, swi, kro, values):
        self.file.write("{},{},{},{}\n".format(swi, kro, *values))


def run_parallel_optmizers(number_of_jobs, number_of_iterations):
    PnFlow.set_binary_path(PNFLOW_BINARY_PATH)

    file_directory = Path(os.path.dirname(os.path.realpath(__file__)))
    execution_directory = file_directory / "execution"
    pnflow = PnFlow(execution_directory)

    file = OutputFile("output.txt")

    execution_id = 0
    opt = Optimizer(
        [(20.0, 100.0), (20.0, 100.0)],
        base_estimator="GP",
        n_initial_points=number_of_jobs,
        acq_optimizer="sampling",
        random_state=42,
    )
    for i in range(number_of_iterations):
        values_list = opt.ask(number_of_jobs)
        arguments_list = []
        for values in values_list:
            args = values.copy()
            args.append(execution_id)
            execution_id += 1
            arguments_list.append(args)

        y = Parallel(n_jobs=number_of_jobs)(delayed(pnflow.run)(*args) for args in arguments_list)

        for i, v in enumerate(values_list):
            swi, kro = y[i]
            file.add(swi, kro, v)
            opt.tell(v, math.sqrt(swi**2 + kro**2))


if __name__ == "__main__":
    run_parallel_optmizers(number_of_jobs=4, number_of_iterations=10)
