from pathlib import Path
import numpy as np
import os, uuid, re, configparser
import random
import pandas as pd
import pyedt
import logging

FORMAT = "%(levelname)s %(asctime)s %(user)-8s %(message)s"
logging.basicConfig(format=FORMAT)

br_green = (0, 133.0 / 255.0, 66.0 / 255.0)
br_blue = (0, 98.0 / 255.0, 152.0 / 255.0)
br_yellow = (253.0 / 255.0, 200.0 / 255.0, 47.0 / 255.0)
drp_path_linux = "/nethome/drp/"
drp_path_windows = "\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\"
microtom_path_linux = "/nethome/drp/servicos/LTRACE/MICROTOM/"
microtom_path_windows = "\\\\dfs.petrobras.biz\\cientifico\\cenpes\\res\\drp\\servicos\\LTRACE\\MICROTOM\\"


def build_filename(ds, data_array="microtom", with_dimensions=False):
    """
    Build filename for a microtom files.

    Parameters :
        ds : xr.DataSet
            microtom xr.DataSet containing the atributes ['well', 'sample_name', 'condition', 'sample_type', 'resolution']
        data_array : str, optional
            Name of the data array to be converted in a raw file.
            The default is microtom.
        with_dimensions : bool, optional
            In the case the information about the dimensions is required, with_dimensions is equal True.
            The default is False.
    Returns:
        output_name: str
            Formated file name.
    """
    if data_array == "microtom":
        image_type = "CT"
    elif data_array == "bin":
        image_type = "BIN"
    elif data_array == "bin_reflected":
        image_type = "BIN"
    elif data_array == "labels":
        image_type = "LABELS"
    elif data_array == "mango":
        image_type = "MANGO"
    elif data_array == "field":
        image_type = "FIELD"
    elif data_array == "pressure":
        image_type = "PRESSURE"
    elif data_array == "velocity":
        image_type = "VELOCITY"
    elif data_array == "porosity":
        image_type = "POR"
    elif (data_array == "kabs") or (data_array == "kabsx") or (data_array == "kabsy"):
        image_type = "KABS"
    elif data_array == "hpsd":
        image_type = "HPSD"
    elif data_array == "psd":
        image_type = "PSD"
    elif data_array == "micp":
        image_type = "MICP"
    elif data_array == "imbibition_compressible":
        image_type = "IMBCOMP"
    elif data_array == "imbibition_incompressible":
        image_type = "IMBINCOMP"
    elif data_array == "drainage_incompressible":
        image_type = "DRAINCOMP"

    if (data_array is not None) and (with_dimensions):
        output_name = "_".join(
            [
                ds.well,
                ds.sample_name,
                ds.condition,
                ds.sample_type,
                image_type,
                "{:04d}".format(int(ds[data_array].data.shape[2])),
                "{:04d}".format(int(ds[data_array].data.shape[1])),
                "{:04d}".format((int(ds[data_array].data.shape[0]))),
                "{:05d}".format(int(round(ds.resolution * 1e6))) + "nm",
            ]
        )
    elif data_array is not None:
        output_name = "_".join(
            [
                ds.well,
                ds.sample_name,
                ds.condition,
                ds.sample_type,
                "{:05d}".format(int(round(ds.resolution * 1e6))) + "nm",
            ]
        )
    else:
        output_name = "_".join(
            [
                ds.well,
                ds.sample_name,
                ds.condition,
                ds.sample_type,
                "{:05d}".format(int(round(ds.resolution * 1e6))) + "nm",
            ]
        )
    return output_name


def reflect_data(data, direction="z"):
    """
    Reflect the information in a 3D data, dupling its total size and making it periodic.

    Parameters
    ----------
    data : numpy.ndarray
        Any data which needs to be doubled.
    direction : str, optional
        Direction in which the medium is doubled, can be 'x', 'y' or 'z'.
        The default is 'z'.

    Returns
    -------
    result_data : numpy.ndarray
        New medium with the size doubled in the direction of the argument.

    """
    if direction == "x":
        result_data = np.concatenate((data, data[:, :, ::-1]), axis=2)
    if direction == "y":
        result_data = np.concatenate((data, data[:, ::-1, :]), axis=1)
    if direction == "z":
        result_data = np.concatenate((data, data[::-1, :, :]), axis=0)
    return result_data


def multiply_data(data, multiply_by=2):
    """
    Multiply the size of each voxel in a 3D data, multiplying its total size by multiply_by

    Parameters
    ----------
    data : numpy.ndarray
        Any data which needs to be multiplied.
    multiply_by : float, optional
        How many times the data should be multiplied.
        The default is 2.
    Returns
    -------
    result_data : numpy.ndarray
        New medium with the size multiplied in all the directions by multiply_by.

    """
    result_data = np.zeros(np.multiply(multiply_by, data.shape))
    for i in range(multiply_by):
        for j in range(multiply_by):
            for k in range(multiply_by):
                result_data[i::multiply_by, j::multiply_by, k::multiply_by] = data
    return result_data


def get_cluster_parameters(cluster, user_key="default", partition="default", account="default"):
    if user_key == "default":
        user_key = "`whoami`"

    file_name = str(uuid.uuid4())
    os.system("sacctmgr show user -s " + user_key + " format=Cluster,Account,Partition > " + file_name)
    possible_choices = pd.read_csv(file_name, delimiter=r"\s+", skiprows=[1])
    possible_choices = possible_choices[
        np.logical_and(
            np.logical_and(possible_choices["Account"] != "teste", possible_choices["Account"] != "none"),
            possible_choices["Account"] != "remoto",
        )
    ]

    function_intro = ""
    if cluster == "lncc":
        partition = "sd_cpu" if (partition == "default") else partition
        account = "drpbrasil" if (account == "default") else account
        return function_intro, partition, account
    elif cluster == "ogbon":
        partition = "CPUlongAB" if (partition == "default") else partition
        account = "petrobras" if (account == "default") else account
        return function_intro, partition, account
    elif cluster == "atena":
        env_activation_path = Path(microtom_path_linux) / "bin" / "activate"
        function_intro = f"bash -c 'source /etc/bashrc'; source {env_activation_path};"
        if partition == "default":
            cur_partition = "cpu"
            if len(possible_choices[possible_choices["Partition"] == cur_partition]) == 1:
                return (
                    function_intro,
                    cur_partition,
                    possible_choices["Account"][possible_choices["Partition"] == cur_partition].iloc[0],
                )
            elif len(possible_choices[possible_choices["Partition"] == cur_partition]) > 0:
                return (
                    function_intro,
                    cur_partition,
                    random.choice(
                        possible_choices["Account"][possible_choices["Partition"] == cur_partition].to_numpy()
                    ),
                )
            else:
                print("Default partition had to be altered to give a valid answer.")
                if (len(possible_choices[possible_choices["Cluster"] == "atena1"])) > 0:
                    return (
                        function_intro,
                        possible_choices["Partition"][possible_choices["Cluster"] == "atena1"].iloc[0],
                        possible_choices["Account"][possible_choices["Cluster"] == "atena1"].iloc[0],
                    )
                else:
                    print("No valid partition for atena")
                    return
        else:
            return (
                function_intro,
                partition,
                np.unique(possible_choices["Account"][possible_choices["Cluster"] == "atena1"].to_numpy())[0],
            )


def parse_name(name):
    """Parse microtom filenames

    Args:
        name (str): Filename using the format  <well>_<sample_name>_<condition>_<sample_type>_<resolution>nm'

    Returns:
        dict: Dictionary with filename attributes
    """
    attrs = re.search(
        r"(?P<well>\w+)_(?P<sample_name>\w+)_(?P<condition>\w+)_(?P<sample_type>\w+)_(?P<resolution>\d+)nm", name
    ).groupdict()
    attrs["resolution"] = float(attrs["resolution"]) / 1e6  # mm
    return attrs


def structural_element_2d(diameter):
    """
    Generate a 2D structural circular element to be applied when necessary.

    Parameters
    ----------
    diameter : int
        Diameter of the structural element.

    Returns
    -------
    element : numpy.ndarray, two dimensions
        Represents the structural element.

    """
    element = np.ones((diameter, diameter))
    for j in range(diameter):
        for i in range(diameter):
            if ((i - (diameter - 1) / 2) ** 2 + (j - (diameter - 1) / 2) ** 2) > ((diameter - 1) / 2) ** 2 + 1:
                element[i, j] = 0
    return element


def structural_element_3d(diameter):
    """
    Generate a 3D structural spherical element to be applied when necessary.

    Parameters
    ----------
    diameter : int
        Diameter of the structural element.

    Returns
    -------
    element : numpy.ndarray, three dimensions
        Represents the structural element.

    """
    element = np.ones((diameter, diameter, diameter))
    for k in range(diameter):
        for j in range(diameter):
            for i in range(diameter):
                if ((i - (diameter - 1) / 2) ** 2 + (j - (diameter - 1) / 2) ** 2 + (k - (diameter - 1) / 2) ** 2) > (
                    (diameter - 1) / 2
                ) ** 2 + 1:
                    element[i, j, k] = 0
    return element


def _get_config(config_path, section, option):
    config = configparser.ConfigParser()
    config.read(config_path)
    return config.get(section, option)


class BufferedPyEDT:
    def __init__(self, shape, dtype=np.int32, sqrt_result=True, device="cpu") -> None:
        self.sqrt_result = sqrt_result
        self.device = device
        self.shape = shape
        self.dtype = dtype
        self.__buffer = None

    def __call__(self, A, copy=False):
        if self.__buffer is None and not copy:
            self.__buffer = np.zeros(self.shape, dtype=self.dtype)

        return pyedt.edt(A, sqrt_result=self.sqrt_result, force_method=self.device, buffer=self.__buffer)


def writelog(logfile, logline):
    """
    Write a logline in a logfile.

    Parameters :
        logfile : str
            Full path to the file created in this simulation.
        logline : str
            Line to be written in the logfile.
    """
    logging.info(logline)
    logfile.write(logline + "\n")
    logfile.flush()
