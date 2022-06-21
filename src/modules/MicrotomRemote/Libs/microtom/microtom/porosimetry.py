#### Próxima versão
# Funcionar via ssh
# Atualizar notebooks com a opção de ser via ssh
# Usar diretamente a saída da função e não o arquivo criado (criado para quê?) na definição do .nc.

#### Desenvolvimento futuro
# Fazer gráficos e manipulação mais amigável dos resultados de simulação numérica.
# Funções do tipo run_psd estão importando apenas os .raw para análise, quando deveriam importar também .nc.
# Fazer transformação entre radii X Sw e Pc X Sw de maneira simples.

import logging
import sys, time, os, datetime
import numpy as np
import xarray as xr
from scipy import ndimage
from skimage import measure
from os.path import isdir
from .io import ds_from_np


def psd(input_data, sat_resolution=0.03, rad_resolution=0.5, output_file_path="./psd.csv", verbose=True):
    """
    Calculate the porous size distribution defined by the radii of the maximum spheres which fits inside a binary porous medium.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        sat_resolution : float, optional
            Resolution of the saturation calculated. Determines a limit for the discretization of the PSD curve in saturation.
            The default is 0.03.
        rad_resolution : float, optional
            Resolution of the radii calculated. Determines a limit for the discretization of the PSD curve in the radii.
            The default is 0.5.
        output_file_path : str, optional
            Full path to the file created in this simulation.
            The default is './psd.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of psd evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_psd : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_psd : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            psd : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.

    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    if verbose:
        output_image = bin_data.copy()

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)
    try:
        output_psd_file = open(output_file_path, "a")

        start = time.time()
        porosity = bin_data.mean()
        bin_edt = ndimage.distance_transform_edt(bin_data)
        max_radius = bin_edt.max()

        nw_saturation = np.zeros(3, dtype=np.float32)
        list_radii = np.array([1, max_radius / 4, max_radius], dtype=np.float32)
        for i in range(len(list_radii)):
            nw_image = np.multiply(
                bin_data,
                (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]).astype(np.uint8),
                dtype=np.uint8,
            )
            if verbose:
                output_image = np.maximum(output_image, nw_image * list_radii[i])
            nw_saturation[i] = nw_image.mean() / porosity
            print("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]))
            output_psd_file.write("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]) + "\n")
            output_psd_file.flush()

        more_radii = True
        cur_resolution = np.max([nw_saturation[0] - nw_saturation[1], nw_saturation[1] - nw_saturation[2]])
        while (cur_resolution > sat_resolution) and (more_radii):
            more_radii = False
            new_list_radii = list_radii
            new_nw_saturation = nw_saturation
            for i in range(len(list_radii) - 1):
                if np.abs(nw_saturation[i + 1] - nw_saturation[i]) > sat_resolution:
                    if np.abs(list_radii[i + 1] - list_radii[i]) > 2 * rad_resolution:
                        new_list_radii = np.append(new_list_radii, (list_radii[i + 1] + list_radii[i]) / 2)
                        new_nw_saturation = np.append(new_nw_saturation, -1)
                        more_radii = True
            nw_saturation = new_nw_saturation
            list_radii = new_list_radii

            for i in range(len(list_radii)):
                if nw_saturation[i] < 0:
                    nw_image = np.multiply(
                        bin_data,
                        (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]).astype(
                            np.uint8
                        ),
                        dtype=np.uint8,
                    )
                    if verbose:
                        output_image = np.maximum(output_image, nw_image * list_radii[i])
                    nw_saturation[i] = nw_image.mean() / porosity
                    print("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]))
                    output_psd_file.write("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]) + "\n")
                    output_psd_file.flush()
            list_radii = np.sort(list_radii)
            nw_saturation = np.sort(nw_saturation)[::-1]

            cur_resolution = 0
            for i in range(len(list_radii) - 1):
                cur_resolution = np.max([cur_resolution, np.abs(nw_saturation[i + 1] - nw_saturation[i])])
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        if output_psd_file:
            output_psd_file.close()

    print("Time spent in psd: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["psd"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_psd": nw_saturation})
        input_data["radii_psd"] = (("snw_psd"), list_radii)
        return input_data

    return xr.Dataset({"radii_psd": (("snw_psd"), list_radii)}, coords={"snw_psd": nw_saturation})


def hpsd(input_data, output_file_path="./hpsd.csv", verbose=True):
    """
    Calculate the hierarquical porous size distribution defined by the radii of the maximum spheres which fits inside a binary porous medium, when the spheres do not overlap.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        output_file_path : str, optional
            Full path to the files created in this simulation.
            The default is './hpsd.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of hpsd evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_hpsd : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_hpsd : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            hpsd : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.

    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    output_image = bin_data.copy()
    start = time.time()
    porosity = bin_data.mean()

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)
    output_hpsd_file = open(output_file_path, "a")

    nw_saturation = []
    list_radii = []
    cur_bin = bin_data.copy()
    cur_index = 0

    while cur_bin.max() > 0:
        bin_edt = ndimage.distance_transform_edt(cur_bin)
        cur_radius = bin_edt.max()
        nw_image = np.multiply(
            cur_bin,
            (ndimage.distance_transform_edt(1 - (bin_edt >= cur_radius)) < cur_radius).astype(np.uint8),
            dtype=np.uint8,
        )
        output_image = np.maximum(output_image, nw_image * cur_radius)

        nw_saturation.append((nw_image.mean() / porosity))
        list_radii.append(cur_radius)
        print("Radius: " + str(cur_radius) + ", Snw: " + str(nw_saturation[cur_index]))
        output_hpsd_file.write("Radius: " + str(cur_radius) + ", Snw: " + str(nw_saturation[cur_index]) + "\n")
        output_hpsd_file.flush()

        cur_index += 1
        cur_bin -= nw_image

    output_hpsd_file.close()

    accumulated = []
    accumulated.append(nw_saturation[0])
    for i in range(1, len(nw_saturation)):
        accumulated.append(nw_saturation[i] + accumulated[i - 1])
    accumulated = accumulated / accumulated[-1]

    print("Time spent in hpsd: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["hpsd"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_hpsd": np.array(accumulated)})
        input_data["radii_hpsd"] = (("snw_hpsd"), np.array(list_radii))
        return input_data

    return xr.Dataset({"radii_hpsd": (("snw_hpsd"), np.array(list_radii))}, coords={"snw_hpsd": np.array(accumulated)})


def micp(
    input_data, sat_resolution=0.03, rad_resolution=0.5, direction="z-", output_file_path="./micp.csv", verbose=True
):
    """
    Calculate the mercury injection capillary pressure defined by the radii of the maximum spheres which fits inside a binary porous medium and are connected to the entry.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        sat_resolution : float, optional
            Resolution of the saturation calculated. Determines a limit for the discretization of the MICP curve in saturation.
            The default is 0.03.
        rad_resolution : float, optional
            Resolution of the radii calculated. Determines a limit for the discretization of the MICP curve in the radii.
            The default is 0.5.
        direction : str, optional
            The default is 'z-', it can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-' or 'all' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively.
        output_file_path : str, optional
            Full path to the files created in this simulation.
            The default is './micp.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of micp evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_micp : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_micp : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            micp : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    if verbose:
        output_image = bin_data.copy()

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)
    output_micp_file = open(output_file_path, "a")

    start = time.time()
    porosity = bin_data.mean()
    bin_edt = ndimage.distance_transform_edt(bin_data)
    max_radius = bin_edt.max()

    nw_saturation = np.zeros(3, dtype=np.float32)
    list_radii = np.array([1, max_radius / 4, max_radius], dtype=np.float32)
    for i in range(len(list_radii)):
        nw_image = connected_image(
            np.multiply(
                bin_data,
                (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]).astype(np.uint8),
                dtype=np.uint8,
            ),
            direction=direction,
        )

        if verbose:
            output_image = np.maximum(output_image, nw_image * list_radii[i])
        nw_saturation[i] = nw_image.mean() / porosity
        print("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]))
        output_micp_file.write("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]) + "\n")
        output_micp_file.flush()

    more_radii = True
    cur_resolution = np.max([nw_saturation[0] - nw_saturation[1], nw_saturation[1] - nw_saturation[2]])
    while (cur_resolution > sat_resolution) and (more_radii):
        more_radii = False
        new_list_radii = list_radii
        new_nw_saturation = nw_saturation
        for i in range(len(list_radii) - 1):
            if np.abs(nw_saturation[i + 1] - nw_saturation[i]) > sat_resolution:
                if np.abs(list_radii[i + 1] - list_radii[i]) > 2 * rad_resolution:
                    new_list_radii = np.append(new_list_radii, (list_radii[i + 1] + list_radii[i]) / 2)
                    new_nw_saturation = np.append(new_nw_saturation, -1)
                    more_radii = True
        nw_saturation = new_nw_saturation
        list_radii = new_list_radii

        for i in range(len(list_radii)):
            if nw_saturation[i] < 0:
                nw_image = connected_image(
                    np.multiply(
                        bin_data,
                        (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]).astype(
                            np.uint8
                        ),
                        dtype=np.uint8,
                    ),
                    direction=direction,
                )
                if verbose:
                    output_image = np.maximum(output_image, nw_image * list_radii[i])
                nw_saturation[i] = nw_image.mean() / porosity
                print("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]))
                output_micp_file.write("Radius: " + str(list_radii[i]) + ", Snw: " + str(nw_saturation[i]) + "\n")
                output_micp_file.flush()
        list_radii = np.sort(list_radii)
        nw_saturation = np.sort(nw_saturation)[::-1]

        cur_resolution = 0
        for i in range(len(list_radii) - 1):
            cur_resolution = np.max([cur_resolution, np.abs(nw_saturation[i + 1] - nw_saturation[i])])

    output_micp_file.close()

    print("Time spent in micp: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["micp"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_micp": nw_saturation})
        input_data["radii_micp"] = (("snw_micp"), list_radii)
        return input_data

    return xr.Dataset(
        {"radii_micp": (("snw_micp"), np.array(list_radii))}, coords={"snw_micp": np.array(nw_saturation)}
    )


def drainage_incompressible(
    input_data, sat_resolution=0.03, rad_resolution=0.5, direction="z-", output_file_path="./drainage.csv", verbose=True
):
    """
    Calculate the drainage capillary pressure defined by the radii of the maximum spheres which fits inside a binary porous medium and are connected to the entry.
    The Swi is not zero in this process, since the wetting phase is trapped as the cappilary pressure increases.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        sat_resolution : float, optional
            Resolution of the saturation calculated. Determines a limit for the discretization of the imbibition curve in saturation.
            The default is 0.03.
        rad_resolution : float, optional
            Resolution of the radii calculated. Determines a limit for the discretization of the imbibition curve in the radii.
            The default is 0.5.
        direction : str, optional
            The default is 'z-', it can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-' or 'all' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively.
        output_file_path : str, optional
            Full path to the files created in this simulation.
            The default is './imbibition.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of drainage evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_drainage_incompressible : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_drainage_incompressible : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            drainage_incompressible : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)

    try:
        output_drai_file = open(output_file_path, "a")
        start = time.time()
        porosity = bin_data.mean()
        bin_edt = ndimage.distance_transform_edt(bin_data)
        max_radius = bin_edt.max()

        list_radii = np.array(
            [max_radius, (3.0 * max_radius / 4), (max_radius / 2), (max_radius / 4), 1.0], dtype=np.float32
        )

        not_found = True
        while not_found:
            nw_saturation = []
            unconnected_phase = np.zeros(bin_data.shape)

            if verbose:
                output_image = 0.5 * bin_data.copy()

            for i in range(len(list_radii)):
                nw_image = connected_image(
                    np.multiply(
                        bin_data - unconnected_phase,
                        ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i],
                    ),
                    direction=direction,
                )
                unconnected_phase = bin_data - nw_image - connected_image(bin_data - nw_image, direction="z+")
                if verbose:
                    output_image = np.maximum(output_image, nw_image * list_radii[i])
                nw_saturation.append((nw_image.mean() / porosity))
                print("Radius: " + str(list_radii[i]) + ", Saturation: " + str(nw_saturation[-1]))
                output_drai_file.write(
                    "Radius: " + str(list_radii[i]) + ", Saturation: " + str(nw_saturation[-1]) + "\n"
                )
                output_drai_file.flush()

            print("list_radii: " + str(list_radii))
            print("nw_saturation: " + str(nw_saturation))
            new_list_radii = list_radii
            number_of_radii = len(new_list_radii)
            for i in range(1, len(nw_saturation)):
                if nw_saturation[i] - nw_saturation[i - 1] > sat_resolution:
                    if list_radii[i - 1] - list_radii[i] > rad_resolution:
                        new_list_radii = np.append(
                            new_list_radii, list_radii[i] + (list_radii[i - 1] - list_radii[i]) / 3
                        )
                        new_list_radii = np.append(
                            new_list_radii, list_radii[i] + 2.0 * (list_radii[i - 1] - list_radii[i]) / 3
                        )
            new_list_radii = np.sort(new_list_radii)[::-1]
            if number_of_radii == len(new_list_radii):
                not_found = False
            list_radii = new_list_radii
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        if output_drai_file:
            output_drai_file.close()

    print("Time spent in drainage: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["drainage_incompressible"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_drainage_incompressible": nw_saturation})
        input_data["radii_drainage_incompressible"] = (("snw_drainage_incompressible"), list_radii)
        return input_data

    return xr.Dataset(
        {"radii_drainage_incompressible": (("snw_drainage_incompressible"), list_radii)},
        coords={"snw_drainage_incompressible": nw_saturation},
    )


def imbibition_compressible(
    input_data,
    sat_resolution=0.03,
    rad_resolution=0.5,
    direction="z-",
    output_file_path="./imbibition.csv",
    verbose=True,
):
    """
    Calculate the imbibition capillary pressure defined by the radii of the maximum spheres which fits inside a binary porous medium and are connected to the entry.
    There is no Sor in this process, the non-wetting phase is incorporated in the wetting fluid as the cappilary pressure diminishes.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        sat_resolution : float, optional
            Resolution of the saturation calculated. Determines a limit for the discretization of the imbibition curve in saturation.
            The default is 0.03.
        rad_resolution : float, optional
            Resolution of the radii calculated. Determines a limit for the discretization of the imbibition curve in the radii.
            The default is 0.5.
        direction : str, optional
            The default is 'z-', it can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-' or 'all' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively.
        output_file_path : str, optional
            Full path to the files created in this simulation.
            The default is './imbibition.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of imbibition evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_imbibition_compressible : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_imbibition_compressible : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            imbibition_compressible : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    if verbose:
        output_image = np.max(bin_data.shape) * bin_data.copy()

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)

    try:
        output_imb_file = open(output_file_path, "a")

        start = time.time()
        porosity = bin_data.mean()
        bin_edt = ndimage.distance_transform_edt(bin_data)
        max_radius = bin_edt.max()

        w_saturation = np.zeros(3, dtype=np.float32)
        list_radii = np.array([1, max_radius / 2.0, max_radius], dtype=np.float32)
        for i in range(len(list_radii)):
            w_image = connected_image(
                np.multiply(
                    bin_data, 1 - (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i])
                ),
                direction=direction,
            )
            if verbose:
                output_image = np.multiply(w_image, np.minimum(output_image, w_image * list_radii[i])) + np.multiply(
                    (1 - w_image), output_image
                )
            w_saturation[i] = w_image.mean() / porosity
            print("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[i]))
            output_imb_file.write("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[i]) + "\n")
            output_imb_file.flush()

        more_radii = True
        cur_resolution = np.max([w_saturation[1] - w_saturation[0], w_saturation[2] - w_saturation[1]])
        while (cur_resolution > sat_resolution) and (more_radii):
            more_radii = False
            new_list_radii = list_radii
            new_w_saturation = w_saturation
            for i in range(len(list_radii) - 1):
                if np.abs(w_saturation[i + 1] - w_saturation[i]) > sat_resolution:
                    if np.abs(list_radii[i + 1] - list_radii[i]) > 2 * rad_resolution:
                        new_list_radii = np.append(new_list_radii, (list_radii[i + 1] + list_radii[i]) / 2)
                        new_w_saturation = np.append(new_w_saturation, -1)
                        more_radii = True
            w_saturation = new_w_saturation
            list_radii = new_list_radii

            for i in range(len(list_radii)):
                if w_saturation[i] < 0:
                    w_image = connected_image(
                        np.multiply(
                            bin_data,
                            1 - (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]),
                        ),
                        direction=direction,
                    )
                    if verbose:
                        output_image = np.multiply(
                            w_image, np.minimum(output_image, w_image * list_radii[i])
                        ) + np.multiply(1 - w_image, output_image)
                    w_saturation[i] = w_image.mean() / porosity
                    print("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[i]))
                    output_imb_file.write("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[i]) + "\n")
                    output_imb_file.flush()
            list_radii = np.sort(list_radii)
            w_saturation = np.sort(w_saturation)

            cur_resolution = 0
            for i in range(len(list_radii) - 1):
                cur_resolution = np.max([cur_resolution, np.abs(w_saturation[i + 1] - w_saturation[i])])
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        if output_imb_file:
            output_imb_file.close()

    print("Time spent in imbibition: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["imbibition_compressible"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_imbibition_compressible": (1.0 - w_saturation)})
        input_data["radii_imbibition_compressible"] = (("snw_imbibition_compressible"), list_radii)
        return input_data

    return xr.Dataset(
        {"radii_imbibition_compressible": (("snw_imbibition_compressible"), list_radii)},
        coords={"snw_imbibition_compressible": (1.0 - w_saturation)},
    )


def imbibition_incompressible(
    input_data,
    sat_resolution=0.03,
    rad_resolution=0.5,
    direction="z-",
    output_file_path="./imbibition.csv",
    verbose=True,
):
    """
    Calculate the imbibition capillary pressure defined by the radii of the maximum spheres which fits inside a binary porous medium and are connected to the entry.
    The Sor is not zero in this process, since the non-wetting phase is trapped as the cappilary pressure diminishes.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        sat_resolution : float, optional
            Resolution of the saturation calculated. Determines a limit for the discretization of the imbibition curve in saturation.
            The default is 0.03.
        rad_resolution : float, optional
            Resolution of the radii calculated. Determines a limit for the discretization of the imbibition curve in the radii.
            The default is 0.5.
        direction : str, optional
            The default is 'z-', it can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-' or 'all' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively.
        output_file_path : str, optional
            Full path to the files created in this simulation.
            The default is './imbibition.csv'.
        verbose : bool, optional
            If it is True, create a full image with the information of imbibition evaluation and output it.
            The default is False.
    Returns :
        A xr.Dataset with:
            snw_imbibition_incompressible : numpy.ndarray, one dimension
                Array with the non-wetting saturation in each one of the radii.
            radii_imbibition_incompressible : numpy.ndarray, one dimension
                Array with the saturation in each one of the saturations.
            imbibition_incompressible : optional, numpy.ndarray
                It is an output only if verbose is True.
                Full map of regions with their characteristic lengths.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    output_path = os.path.dirname(os.path.abspath(output_file_path))
    if not isdir(output_path):
        os.makedirs(output_path)

    try:
        output_imb_file = open(output_file_path, "a")
        start = time.time()
        porosity = bin_data.mean()
        bin_edt = ndimage.distance_transform_edt(bin_data)
        max_radius = bin_edt.max()

        list_radii = np.array(
            [1, (max_radius / 4), (max_radius / 2), (3 * max_radius / 4), max_radius], dtype=np.float32
        )

        not_found = True
        while not_found:
            w_saturation = []
            unconnected_phase = np.zeros(bin_data.shape)

            if verbose:
                output_image = np.max(bin_data.shape) * bin_data.copy()

            for i in range(len(list_radii)):
                w_image = connected_image(
                    np.multiply(
                        bin_data - unconnected_phase,
                        1 - (ndimage.distance_transform_edt(1 - (bin_edt >= list_radii[i])) < list_radii[i]),
                    ),
                    direction=direction,
                )
                unconnected_phase = bin_data - w_image - connected_image(bin_data - w_image, direction="z+")
                if verbose:
                    output_image = np.multiply(
                        w_image, np.minimum(output_image, w_image * list_radii[i])
                    ) + np.multiply((1 - w_image), output_image)
                w_saturation.append((w_image.mean() / porosity))
                print("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[-1]))
                output_imb_file.write("Radius: " + str(list_radii[i]) + ", Sw: " + str(w_saturation[-1]) + "\n")
                output_imb_file.flush()

            print("list_radii: " + str(list_radii))
            print("Sw: " + str(w_saturation))
            new_list_radii = list_radii
            number_of_radii = len(new_list_radii)
            for i in range(1, len(w_saturation)):
                if w_saturation[i] - w_saturation[i - 1] > sat_resolution:
                    if list_radii[i] - list_radii[i - 1] > rad_resolution:
                        new_list_radii = np.append(
                            new_list_radii, list_radii[i - 1] + (list_radii[i] - list_radii[i - 1]) / 3
                        )
                        new_list_radii = np.append(
                            new_list_radii, list_radii[i - 1] + 2.0 * (list_radii[i] - list_radii[i - 1]) / 3
                        )
            new_list_radii.sort()
            if number_of_radii == len(new_list_radii):
                not_found = False
            list_radii = new_list_radii

        list_radii = np.sort(list_radii)
        w_saturation = np.sort(w_saturation)
    except Exception as error:
        logging.debug(f"Error: {error}")
    finally:
        if output_imb_file:
            output_imb_file.close()

    print("Time spent in imbibition: " + str(time.time() - start))
    if verbose:
        if type(input_data) == np.ndarray:
            input_data = ds_from_np(input_data)
        input_data["imbibition_incompressible"] = (("z", "y", "x"), output_image)
        input_data = input_data.assign_coords({"snw_imbibition_incompressible": (1.0 - w_saturation)})
        input_data["radii_imbibition_incompressible"] = (("snw_imbibition_incompressible"), list_radii)
        return input_data

    return xr.Dataset(
        {"radii_imbibition_incompressible": (("snw_imbibition_incompressible"), list_radii)},
        coords={"snw_imbibition_incompressible": (1.0 - w_saturation)},
    )


def psd_nw_image(input_data, radius):
    """
    Calculate the image related to the radius of the maximum spheres which fits inside a binary porous medium.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        radius : float
            Radius of the spheres to fit in the porous medium.

    Returns :
        nw_image : numpy.ndarray
            Image of the same size of the entry, where one are places where there is a sphere with the informed radius.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data
    return np.multiply(
        bin_data,
        (ndimage.distance_transform_edt(1 - (ndimage.distance_transform_edt(bin_data) >= radius)) < radius).astype(
            np.uint8
        ),
        dtype=np.uint8,
    )


def connected_image(input_data, connectivity=1, direction="z"):
    """
    Calculate the connected image in the direction given.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        connectivity: int, optional
            Maximum number of orthogonal hops to consider a pixel/voxel as a neighbor. Accepted values are ranging from 1 to input.ndim.
            If None, a full connectivity of input.ndim is used.
            The default is 1, which means connected by the faces.
        direction : str, optional
            The default is 'z', can be 'y', 'x', 'z+', 'y+', 'x+', 'z-', 'y-', 'x-', 'all' or 'any' too. '-' and '+' denotes just one face, in the beggining or the end of the sample, respectively. The 'any' option retains all aggregates that touch any of the faces.

    Returns :
        nw_image : numpy.ndarray
            Image of the same size of the entry, where one is connected porous.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data

    label_image = measure.label(bin_data, connectivity=1)
    if direction == "z":
        entry_labels = np.unique(label_image[0, :, :])
        connected = entry_labels[np.isin(entry_labels, np.unique(label_image[len(label_image) - 1, :, :]))]
    elif direction == "z-":
        connected = np.unique(label_image[0, :, :])
    elif direction == "z+":
        connected = np.unique(label_image[len(label_image) - 1, :, :])
    elif direction == "y":
        entry_labels = np.unique(label_image[:, 0, :])
        connected = entry_labels[np.isin(entry_labels, np.unique(label_image[:, len(label_image[0]) - 1, :]))]
    elif direction == "y-":
        connected = np.unique(label_image[:, 0, :])
    elif direction == "y+":
        connected = np.unique(label_image[:, len(label_image[0]) - 1, :])
    elif direction == "x":
        entry_labels = np.unique(label_image[:, :, 0])
        connected = entry_labels[np.isin(entry_labels, np.unique(label_image[:, :, len(label_image[0][0]) - 1]))]
    elif direction == "x-":
        connected = np.unique(label_image[:, :, 0])
    elif direction == "x+":
        connected = np.unique(label_image[:, :, len(label_image[0][0]) - 1])
    elif direction == "all":
        entry_labels = np.unique(label_image[0, :, :])
        connected_z = entry_labels[np.isin(entry_labels, np.unique(label_image[len(label_image) - 1, :, :]))]
        entry_labels = np.unique(label_image[:, 0, :])
        connected_y = entry_labels[np.isin(entry_labels, np.unique(label_image[:, len(label_image[0]) - 1, :]))]
        entry_labels = np.unique(label_image[:, :, 0])
        connected_x = entry_labels[np.isin(entry_labels, np.unique(label_image[:, :, len(label_image[0][0]) - 1]))]
        connected = np.unique(np.concatenate((connected_z, connected_y, connected_x)))
    elif direction == "any":
        connected_zp = np.unique(label_image[0, :, :])
        connected_zm = np.unique(label_image[label_image.shape[0] - 1, :, :])
        connected_yp = np.unique(label_image[:, 0, :])
        connected_ym = np.unique(label_image[:, label_image.shape[1] - 1, :])
        connected_xp = np.unique(label_image[:, :, 0])
        connected_xm = np.unique(label_image[:, :, label_image.shape[2] - 1])
        connected = np.unique(
            np.concatenate((connected_zp, connected_zm, connected_yp, connected_ym, connected_xp, connected_xm))
        )
    else:
        print("Direction option is not valid.")
        sys.exit()
    connected = connected[connected != 0]
    connected_image = np.zeros(bin_data.shape, dtype=np.uint8)
    for j in range(len(connected)):
        connected_image += label_image == connected[j]
    return connected_image


def micp_nw_image(input_data, radius, direction="z"):
    """
    Calculate the image related to the radius of the maximum spheres which fits inside a binary porous medium and it is connected to the entry.

    Parameters :
        input_data : numpy.ndarray OR xr.Dataset
            Binary data, which can be a numpy or a bin numpy inside a xr.Dataset, where one is porous and zero is solid.
        radius : float, optional
            Radius of the sphere to fit in the porous medium.
        direction : str, option
            The default is 'z', can be 'y' and 'x' too.

    Returns :
        nw_image : numpy.ndarray
            Image of the same size of the entry, where one are places where there is a sphere with the informed radius.
    """
    if type(input_data) == np.ndarray:
        bin_data = input_data
    elif type(input_data) == xr.core.dataset.Dataset:
        bin_data = input_data["bin"].data
    return connected_image(psd_nw_image(bin_data, radius), direction=direction)


def run_generic_psd(
    file_name,
    sim_type="psd",
    cut_info=None,
    sat_resolution=0.03,
    rad_resolution=0.5,
    direction="z",
    n_threads_per_node=40,
    cluster="atena",
    account="default",
    partition="default",
    output_path=".",
    verbose=True,
):
    """
    Function which simulates psd, hpsd, micp, drainage_incompressible, imbibition_compressible or imbibition_incompressible from a .raw file in a HPC environment and process the results into a .nc file.

    Parameters
    ----------
    file_name : str
        Full path of the .raw used as entry. It assumes the filename follows the format:
        WELL_SAMPLE_STATE_TYPE_TYPEOFIMAGE_NX_NY_NZ_RESOLUTION.raw (example: 'LL36A_V011830H_LIMPA_B1_BIN_0256_0256_0256_04000nm.raw').
    sim_type : str, optional
        The type of porous size distribution determination which will be run. Can be 'psd', 'hpsd', 'micp', 'drainage_incompressible', 'imbibition_compressible' or 'imbibition_incompressible'.
        The default is 'psd'.
    cut_info : numpy.ndarray, optional
        Parameters to cut the data to test only a small part of it, in the format [ox, oy, oz, ex, ey, ez].
        ox, oy and oz are the coordinates in voxels of the origin of the cut and ex, ey an ez are the coordinates of the end of the cut.
        The default is None.
    sat_resolution : float, optional
        Resolution of the saturation calculated. Determines a limit for the discretization of the MICP curve in saturation.
        It is not considered in 'hpsd' simulations.
        The default is 0.03.
    rad_resolution : float, optional
        Resolution of the radii calculated. Determines a limit for the discretization of the MICP curve in the radii.
        It is not considered in 'hpsd' simulations.
        The default is 0.5.
    direction : str, optional
        The default is 'z', can be 'y', 'x' or 'all' too.
        It is considered only in the ''micp' simulations.
    n_threads_per_node : int, optional
        Partition to run the simulations.
        The default is 'default', which means the functions called later will choose what is default for the system choosed in the cluster_name argument.
        The default is 40.
    cluster : str, optional
        Cluster to run the simulations.
        The default is 'atena', but can run also in 'dgx', 'lncc' and 'ogbon'.
    partition : str, optional
        Partition where the simulation will be run.
        The default is 'default', which means the functions called later will choose what is default for the system choosed in the cluster_name argument.
    account : str, optional
        Account which will be used to run the simulations.
        The default is 'default', which means the functions called later will choose what is default for the system choosed in the cluster_name argument.
    output_path : str, optional
        Path to the files created in this simulation.
        The default is '.'.
    verbose : bool, optional
        If it is True, create a full image with the information of psd evaluation and output it.
        The default is False.

    Returns
    -------
    job_id : int
        Job id in the cluster.
    """
    str_time = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    # Definition of the clusters used.
    if cluster == "lncc":
        partition = "sd_cpu" if (partition == "default") else partition
        account = "drppetrobras" if (account == "default") else account
    elif cluster == "ogbon":
        partition = "CPUlongAB" if (partition == "default") else partition
        account = "petrobras" if (account == "default") else account
    elif cluster == "atena":
        partition = "cpu" if (partition == "default") else partition
        account = "TCR" if (account == "default") else account
    elif cluster == "dgx":
        partition = None if (partition == "default") else partition
        account = None if (account == "default") else account
    output_path = os.path.abspath(output_path)

    # Definition of the run_psd, run_hpsd, run_micp, run_drainage_incompressible, run_imbibition_compressible or run_imbibition_incompressibl, which will set up the simulation, simulate, and compile the results into a .nc file
    script_file = open("./run_" + sim_type + ".sh", "w")
    script_file.write("#!/bin/bash\n")
    if partition is not None:
        script_file.write("# Project/Partition\n")
        script_file.write("#SBATCH --partition " + partition + "\n")
    if account is not None:
        script_file.write("# Project/Account\n")
        script_file.write("#SBATCH -A " + account + "\n")
    script_file.write("#SBATCH -J " + sim_type + "_" + str_time + "\n")
    script_file.write("# Number of nodes\n")
    script_file.write("#SBATCH --nodes=1\n")
    script_file.write("# Number of nodes\n")
    script_file.write("#SBATCH --ntasks-per-node=" + str(n_threads_per_node) + "\n")
    script_file.write("# Runtime of this jobs\n")
    script_file.write("#SBATCH --time=300:00:00\n")
    script_file.write("\n")
    script_file.write("CURRENT_DIR=$PWD\n")
    script_file.write("INPUT_FILE=" + file_name.split("/")[-1] + "\n")
    script_file.write("OUTPUT_PATH=" + output_path + "/" + cluster + "_${SLURM_JOBID}\n")
    script_file.write("\n")
    script_file.write('if [ ! -d "$OUTPUT_PATH" ]; then\n')
    script_file.write("    mkdir -p $OUTPUT_PATH\n")
    script_file.write("fi\n")
    script_file.write("cp " + file_name + " $OUTPUT_PATH/\n")
    script_file.write("cd $OUTPUT_PATH\n")
    script_file.write("CHECKSUM_INFO=`md5sum $INPUT_FILE`\n")
    script_file.write("\n")

    # The process is done in python
    script_file.write("# The process is done in python\n")
    script_file.write('echo "from microtom import read_raw_file, ' + sim_type + "\n")
    script_file.write("import xarray as xr\n")
    script_file.write("import pandas as pd\n")
    script_file.write("import numpy as np\n")
    script_file.write('nc_data=read_raw_file(\\"$INPUT_FILE\\")\n')
    script_file.write("mango_image=(np.array(list(nc_data.keys()))=='mango').astype(np.uint8).sum().astype(bool)\n")
    script_file.write("if mango_image:\n")
    script_file.write("    nc_data['bin']=(nc_data['mango']<2)\n")
    script_file.write("\n")
    if cut_info is not None:
        try:
            script_file.write(
                "bin_data=nc_data['bin'].data["
                + str(cut_info[2])
                + ":"
                + str(cut_info[5])
                + ", "
                + str(cut_info[1])
                + ":"
                + str(cut_info[4])
                + ", "
                + str(cut_info[0])
                + ":"
                + str(cut_info[3])
                + "]\n"
            )
            script_file.write("if mango_image:\n")
            script_file.write(
                "    mango_data=nc_data['mango'].data["
                + str(cut_info[2])
                + ":"
                + str(cut_info[5])
                + ", "
                + str(cut_info[1])
                + ":"
                + str(cut_info[4])
                + ", "
                + str(cut_info[0])
                + ":"
                + str(cut_info[3])
                + "]\n"
            )
        except:
            print("There were problems with the cut_info variable.")
            sys.exit()
    else:
        script_file.write("bin_data=nc_data['bin'].data\n")
        script_file.write("if mango_image:\n")
        script_file.write("    mango_data=nc_data['mango'].data\n")

    output_file_path = "./" + sim_type + "_" + str_time + ".csv"
    # Run the simulation
    script_file.write("# Run the simulation\n")
    if sim_type == "psd":
        script_file.write(
            "results=psd(bin_data.astype(np.uint8), sat_resolution="
            + str(sat_resolution)
            + ", rad_resolution="
            + str(rad_resolution)
            + ", verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    elif sim_type == "hpsd":
        script_file.write(
            "results=hpsd(bin_data.astype(np.uint8), verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    elif sim_type == "micp":
        script_file.write(
            "results=micp(bin_data.astype(np.uint8), sat_resolution="
            + str(sat_resolution)
            + ", rad_resolution="
            + str(rad_resolution)
            + ", direction='"
            + str(direction)
            + "', verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    elif sim_type == "drainage_incompressible":
        script_file.write(
            "results=drainage_incompressible(bin_data.astype(np.uint8), sat_resolution="
            + str(sat_resolution)
            + ", rad_resolution="
            + str(rad_resolution)
            + ", direction='"
            + str(direction)
            + "', verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    elif sim_type == "imbibition_compressible":
        script_file.write(
            "results=imbibition_compressible(bin_data.astype(np.uint8), sat_resolution="
            + str(sat_resolution)
            + ", rad_resolution="
            + str(rad_resolution)
            + ", direction='"
            + str(direction)
            + "', verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    elif sim_type == "imbibition_incompressible":
        script_file.write(
            "results=imbibition_incompressible(bin_data.astype(np.uint8), sat_resolution="
            + str(sat_resolution)
            + ", rad_resolution="
            + str(rad_resolution)
            + ", direction='"
            + str(direction)
            + "', verbose="
            + str(verbose)
            + ", output_file_path='"
            + output_file_path
            + "')\n"
        )
    script_file.write("\n")

    # Processing results
    script_file.write("# Processing results\n")
    script_file.write("\n")
    script_file.write("resolved_porosity=bin_data.sum()/(bin_data.shape[0]*bin_data.shape[1]*bin_data.shape[2])\n")
    script_file.write("if mango_image:\n")
    script_file.write(
        "    total_porosity=((mango_data<2).astype(np.float64)+(mango_data>1).astype(np.float64)*(mango_data<102).astype(np.float64)*((mango_data).astype(np.float32)-1.5)/100.).sum()\n"
    )
    script_file.write("    total_porosity=total_porosity/(bin_data.shape[0]*bin_data.shape[1]*bin_data.shape[2])\n")
    script_file.write("else:\n")
    script_file.write("    total_porosity=resolved_porosity\n")
    if cut_info is not None:
        try:
            script_file.write("x=nc_data['x'][" + str(cut_info[0]) + ":" + str(cut_info[3]) + "]\n")
            script_file.write("y=nc_data['y'][" + str(cut_info[1]) + ":" + str(cut_info[4]) + "]\n")
            script_file.write("z=nc_data['z'][" + str(cut_info[2]) + ":" + str(cut_info[5]) + "]\n")
        except:
            print("There were problems with the cut_info variable.")
            sys.exit()
    else:
        script_file.write("x=nc_data['x']\n")
        script_file.write("y=nc_data['y']\n")
        script_file.write("z=nc_data['z']\n")
    script_file.write("snw_" + sim_type + "=np.array(results['snw_" + sim_type + "'])\n")
    script_file.write("radii_" + sim_type + "=np.array(results['radii_" + sim_type + "'])\n")
    script_file.write("\n")
    script_file.write("attrs=nc_data.attrs\n")
    script_file.write("attrs['dimx']=len(x)\n")
    script_file.write("attrs['dimy']=len(y)\n")
    script_file.write("attrs['dimz']=len(z)\n")
    script_file.write("attrs['resolved_porosity']=resolved_porosity\n")
    script_file.write("attrs['total_porosity']=total_porosity\n")
    script_file.write("attrs['simulation_type']='microtom_" + sim_type + "'\n")
    script_file.write("attrs['original_file']=\\\"$INPUT_FILE\\\"\n")
    script_file.write("attrs['original_file_md5sum']=\\\"$CHECKSUM_INFO\\\".split(' ')[0]\n")
    if cut_info is not None:
        script_file.write("nc_data.attrs['cut_info']=" + str(list(cut_info)) + "\n")
    else:
        script_file.write("nc_data.attrs['cut_info']='None'\n")
    script_file.write("attrs['run_" + sim_type + ".py']=''.join(open('run_" + sim_type + ".py', 'r').readlines())\n")
    script_file.write("\n")
    script_file.write(
        "ds = xr.Dataset({'bin': (('z', 'y', 'x'), bin_data.astype(np.uint8)), 'radii_"
        + sim_type
        + "': (('snw_"
        + sim_type
        + "'), radii_"
        + sim_type
        + ")}, coords={'snw_"
        + sim_type
        + "': snw_"
        + sim_type
        + ", 'z': z, 'y': y, 'x': x}, attrs=attrs)\n"
    )
    script_file.write("if mango_image:\n")
    script_file.write("    ds['mango'] = (('z', 'y', 'x'), mango_data.astype(np.uint8))\n")
    if verbose:
        script_file.write("ds['" + sim_type + "'] = (('z', 'y', 'x'), np.array(results['" + sim_type + "']))\n")
    script_file.write("ds.to_netcdf('" + cluster + "_${SLURM_JOBID}.nc', 'w')\n\" > run_" + sim_type + ".py\n")
    # Run the python which has been created
    script_file.write("python run_" + sim_type + ".py\n")
    script_file.write("mv " + cluster + "_${SLURM_JOBID}.nc ../\n")
    script_file.write("cd ../\n")
    script_file.write("rm -r " + cluster + "_${SLURM_JOBID}\n")
    script_file.write("\n")
    script_file.close()

    os.system(
        "chmod 777 run_"
        + sim_type
        + ".sh;echo `sbatch run_"
        + sim_type
        + '.sh | egrep -o -e "\\b[0-9]+$"` > job_id;sleep 0.2'
    )
    try:
        job_id_file = open("job_id", "r")
        job_id = int(job_id_file.readline())
    except ValueError:
        job_id = -1
    finally:
        if job_id_file:
            job_id_file.close()
    print("job_id = " + str(job_id))
    print("work_dir = " + output_path.replace(".", "") + "/" + cluster + "_" + str(job_id))
    print("final_results = " + output_path.replace(".", "") + "/" + cluster + "_" + str(job_id) + ".nc")
    print("slurm_file = " + "/".join((os.getcwd(), "slurm-" + str(job_id) + ".out")))
    print("start_time = " + str(datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")))
    print("simulation_type = microtom_" + sim_type)
    output_file_path = output_path + "/" + cluster + "_" + str(job_id) + "/" + sim_type + "_" + str_time + ".csv"
    print("simulation_output = " + output_file_path)
    print("cluster = " + str(cluster))
    return job_id
