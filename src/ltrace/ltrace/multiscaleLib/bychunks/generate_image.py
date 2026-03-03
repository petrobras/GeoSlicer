import numpy as np
import mpslib as mps


class GenerateImage:
    def __init__(self):
        pass

    def create_TI_file(self, array):
        """
        Build the ti.dat file
        Parameters
        -------
        array:  array_like(int, ndim=3)
            Array of the image to be used as training
        """
        # self.original_ti = mps.eas.write_mat(array.T, filename=f"ti.dat")
        self.original_ti = mps.eas.write_mat(array, filename=f"ti.dat")

    def configure_MPS_method(
        self,
        hard_data,
        sim_grid_size,
        grid_cell_size,
        ncond,
        nreal,
        hard_data_res,
        n_max_it,
        rseed,
        colocate_dimensions,
        max_search_radius,
        distance_max,
        distance_power,
        distance_measure,
    ):
        """
        Update mps defaults
        Parameters
        -------
        image_array:  array_like(int, ndim=3)
            Array of the image to be used as hard data
        sim_grid_size:  list(int, ndim=3)
            List with image size used to build the final image
        grid_cell_size:  list(int, ndim=3)
            List with image resolution used to build the final image
        ncond: int
            Number of conditioning points used in each simulation
        nreal: int
            Number of realizations to be performed (max = nthreads)
        hard_data_res:  list(int, ndim=3)
            List with image resolution used as hard_data
        n_max_it: int
                A maximum of n_max_it iterations of searching through the training image are performed.
                if n_max_ite < 0 the full training image is scanned.
        rseed:  int
            An integer determines the random seed. A fixed value will return the same realizations for each run.
            [0] assign a ‘random’ seed at each iteration (new seed every second)
        """
        # Initialize MPSlib using mps_genesim algorithm, and settings
        self.mpslib = mps.mpslib(method="mps_genesim", verbose_level=-1)
        self.mpslib.par["simulation_grid_size"] = np.array(sim_grid_size)
        self.mpslib.par["grid_cell_size"] = np.array(grid_cell_size)
        self.mpslib.par["n_cond"] = ncond
        self.mpslib.par["n_real"] = nreal
        self.mpslib.par["ti_fnam"] = f"ti.dat"
        self.mpslib.par["n_max_ite"] = n_max_it
        self.mpslib.par["rseed"] = rseed
        self.mpslib.par["colocate_dimension"] = colocate_dimensions
        self.mpslib.par["max_search_radius"] = max_search_radius
        self.mpslib.par["distance_max"] = distance_max
        self.mpslib.par["distance_pow"] = distance_power
        self.mpslib.par["distance_measure"] = distance_measure

        if hard_data is not None:
            # print("USANDO HARD_DATA")
            self.mpslib.d_hard = hard_data
            self.mpslib.par["hard_data_fnam"] = f"hard.dat"
        return self.mpslib

    def run(self):
        "Main function"
        self.mpslib.run()
        return self.mpslib.sim, self.mpslib.time
