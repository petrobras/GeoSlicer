import slicer

from ltrace.image import optimized_transforms
from porespy.networks import regions_to_network_parallel, snow2

import numpy as np
import pandas as pd


def spy2geo(pn_properties):
    properties_keys_to_delete = []
    properties_pairs_to_add = {}
    for name, array in pn_properties.items():
        if array.ndim == 1:
            continue
        for i in range(array.shape[1]):
            properties_pairs_to_add[f"{name}_{i}"] = array[:, i]
        properties_keys_to_delete.append(name)
    for prop in properties_keys_to_delete:
        del pn_properties[prop]
    pn_properties.update(properties_pairs_to_add)


def get_connected_array_from_node(inputVolume: slicer.vtkMRMLLabelMapVolumeNode) -> np.ndarray:
    """
    Receives a volume node, removes its array unconnected elements and returns that array.

    :param inputVolume: The volume node representing the pore-network.

    :return: The volume node array with connected elements only.

    :raises PoreNetworkExtractorError:
        Pore network extraction failed: there was no percolating pore network through any oposite faces of the volume.
    """

    input_array = slicer.util.arrayFromVolume(inputVolume)
    if input_array.max() <= 2**16 - 1:
        input_array = input_array.astype(np.uint16)
    else:
        print(f"{inputVolume} has many indexes: {input_array.max()}")
        input_array = input_array.astype(np.uint32)

    input_array = optimized_transforms.connected_image(input_array, direction="all_combinations")

    if input_array.max() == 0:
        raise PoreNetworkExtractorError(
            "Pore network extraction failed: there was no percolating pore network through any oposite faces of the volume."
        )

    return input_array


def _porespy_extract(multiphase, watershed, scale, porosity_map=None, watershed_blur=[0.4, 0.4], force_cpu=False):

    # Extracts PNM with porespy and "flattens" the data into a dict of 1d arrays

    if watershed is None:
        "Only in multiscale can watershed be None"
        input_array = multiphase
        if type(watershed_blur) is dict:
            keys = list(watershed_blur.keys())
            for key in keys:
                watershed_blur[int(key)] = watershed_blur[key]
        snow_results = snow2(
            multiphase,
            porosity_map=porosity_map,
            voxel_size=scale,
            parallel_extraction=True,
            sigma=watershed_blur,
            force_cpu=force_cpu,
        )
        pn_properties = snow_results.network
        watershed_image = snow_results.regions
    else:
        input_array = watershed
        if multiphase is None:
            pn_properties = regions_to_network_parallel(
                watershed,
                voxel_size=scale,
                force_cpu=force_cpu,
            )
        else:
            watershed[multiphase == 0] = 0
            porosity_map[multiphase == 0] = 0
            pn_properties = regions_to_network_parallel(
                watershed,
                phases=multiphase,
                porosity_map=porosity_map,
                voxel_size=scale,
                force_cpu=force_cpu,
            )
        watershed_image = watershed

    if not pn_properties:
        return False

    porosity = pn_properties["pore.subresolution_porosity"]
    pn_properties["pore.subresolution_porosity"][porosity == 0] = porosity[porosity > 0].min()

    # spy2geo
    spy2geo(pn_properties)

    # Include additional properties

    pn_properties["pore.radius"] = pn_properties["pore.extended_diameter"] / 2

    pn_properties["throat.shape_factor"] = np.clip(
        (pn_properties["throat.inscribed_diameter"] / 2) ** 2 / (4 * pn_properties["throat.cross_sectional_area"]),
        0.01,
        0.09,
    )
    pn_properties["throat.conns_0_length"] = (
        pn_properties["pore.extended_diameter"][pn_properties["throat.conns_0"]] / 2
    )
    pn_properties["throat.conns_1_length"] = (
        pn_properties["pore.extended_diameter"][pn_properties["throat.conns_1"]] / 2
    )
    pn_properties["throat.mid_length"] = (
        pn_properties["throat.total_length"]
        - pn_properties["throat.conns_0_length"]
        - pn_properties["throat.conns_1_length"]
    )

    pn_properties["throat.mid_length"] = np.where(
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.mid_length"],
    )
    pn_properties["throat.volume"] = pn_properties["throat.total_length"] * pn_properties["throat.cross_sectional_area"]

    pn_properties["pore.shape_factor"] = np.zeros((len(pn_properties["pore.all"]),))
    conns_total_area = np.zeros((len(pn_properties["pore.all"]),))

    for throat in range(len(pn_properties["throat.all"])):
        conn_0 = pn_properties["throat.conns_0"][throat]
        conn_1 = pn_properties["throat.conns_1"][throat]
        pn_properties["pore.shape_factor"][conn_0] += (
            pn_properties["throat.shape_factor"][throat] * pn_properties["throat.cross_sectional_area"][throat]
        )
        pn_properties["pore.shape_factor"][conn_1] += (
            pn_properties["throat.shape_factor"][throat] * pn_properties["throat.cross_sectional_area"][throat]
        )
        conns_total_area[conn_0] += pn_properties["throat.cross_sectional_area"][throat]
        conns_total_area[conn_1] += pn_properties["throat.cross_sectional_area"][throat]
    conns_total_area = np.where(conns_total_area > 0, conns_total_area, 1)
    pn_properties["pore.shape_factor"] /= conns_total_area

    # Swap Z and X axis and displace by origin:
    for coord_name in ("pore.coords_", "pore.local_peak_", "pore.global_peak_", "pore.geometric_centroid_"):
        temp_coord = pn_properties[f"{coord_name}0"]
        pn_properties[f"{coord_name}0"] = pn_properties[f"{coord_name}2"]
        pn_properties[f"{coord_name}2"] = temp_coord
    del temp_coord

    labels = pn_properties["pore.region_label"]
    edge_labels = {}
    edge_labels["all"] = []
    # fmt: off
    for face, face_slice in (
            ("pore.xmax", (slice(0, 1), slice(None), slice(None))),
            ("pore.xmin", (slice(-1, None), slice(None), slice(None))),
            ("pore.ymax", (slice(None), slice(0, 1), slice(None))),
            ("pore.ymin", (slice(None), slice(-1, None), slice(None))),
            ("pore.zmax", (slice(None), slice(None), slice(0, 1))),
            ("pore.zmin", (slice(None), slice(None), slice(-1, None))),
            ):
    # fmt: on
        edge_labels[face] = np.unique(watershed_image[face_slice])
        if edge_labels[face][0] == 0:
            edge_labels[face] = edge_labels[face][1:]
        if 0 in edge_labels[face]:
            raise Exception  # should be impossible, but expensive to guarantee
        edge_labels["all"] = np.unique(np.append(edge_labels["all"], edge_labels[face]))
        pn_properties[face] = np.isin(labels, edge_labels[face])

    max_coords = [(i * scale[input_array.ndim-1-coord]) for coord,i in enumerate(input_array.shape[-1::-1])]
    # fmt: off
    for labels_list, coord_axis, new_position in (
            (edge_labels["pore.xmax"], 2, 0),
            (edge_labels["pore.xmin"], 2, max_coords[2]),
            (edge_labels["pore.ymax"], 1, 0),
            (edge_labels["pore.ymin"], 1, max_coords[1]),
            (edge_labels["pore.zmax"], 0, 0),
            (edge_labels["pore.zmin"], 0, max_coords[0]),
            ):
        for label in labels_list:
            if label == 0:
                continue
            pn_properties[f"pore.coords_{coord_axis}"][label - 1] = new_position
    # fmt: on
    for throat in range(len(pn_properties["throat.all"])):
        pore0 = pn_properties["throat.conns_0"][throat]
        pore1 = pn_properties["throat.conns_1"][throat]
        total_distance = np.sqrt(
            (pn_properties["pore.coords_0"][pore0] - pn_properties["pore.coords_0"][pore1]) ** 2
            + (pn_properties["pore.coords_1"][pore0] - pn_properties["pore.coords_1"][pore1]) ** 2
            + (pn_properties["pore.coords_2"][pore0] - pn_properties["pore.coords_2"][pore1]) ** 2
        )
        distance_ratio = total_distance / pn_properties["throat.direct_length"][throat]
        pn_properties["throat.direct_length"][throat] = total_distance
        pn_properties["throat.total_length"][throat] *= distance_ratio
        pn_properties["throat.mid_length"][throat] = (
            total_distance
            - pn_properties["throat.conns_0_length"][throat]
            - pn_properties["throat.conns_1_length"][throat]
        )
    pn_properties["throat.mid_length"] = np.where(
        pn_properties["throat.mid_length"] < pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.total_length"] * 0.01,
        pn_properties["throat.mid_length"],
    )
    pn_properties["pore.effective_volume"] = pn_properties["pore.volume"] * pn_properties["pore.subresolution_porosity"]

    try:
        pore_subresolution_porosity = pn_properties["pore.subresolution_porosity"]
    except KeyError:
        print(
            "The key pore.subresolution_porosity is not available from porespy, check the version of the porespy module."
        )

    # TODO (PL-2213): Create an option at interface to select random subresolution porosity instead of getting from network
    # rng = np.random.default_rng()
    # pore_subresolution_porosity = rng.random((pn_properties["pore.all"]).size)

    throat_phi = np.ones_like(pn_properties["throat.all"], dtype=np.float64)
    for throat_index in range(len(pn_properties["throat.all"])):
        left_index = pn_properties["throat.conns_0"][throat_index]
        right_index = pn_properties["throat.conns_1"][throat_index]

        left_unresolved = pn_properties["throat.phases_0"][throat_index] == 2
        right_unresolved = pn_properties["throat.phases_1"][throat_index] == 2

        if right_unresolved and left_unresolved:
            throat_phi[throat_index] = (
                pore_subresolution_porosity[left_index] * pn_properties["throat.conns_0_length"][throat_index]
                + pore_subresolution_porosity[right_index] * pn_properties["throat.conns_1_length"][throat_index]
            ) / (
                pn_properties["throat.conns_0_length"][throat_index]
                + pn_properties["throat.conns_1_length"][throat_index]
            )

        elif left_unresolved and not right_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[left_index]

        elif right_unresolved and not left_unresolved:
            throat_phi[throat_index] = pore_subresolution_porosity[right_index]

    pn_properties["throat.subresolution_porosity"] = throat_phi

    ### Volume properties
    if porosity_map is not None:
        input_volume_porosity = (porosity_map.sum() / porosity_map.size) / 100
        input_resolved_porosity = (porosity_map[porosity_map == 100].sum() / porosity_map.size) / 100
        input_subscale_porosity = (((0 < porosity_map) & (porosity_map < 100)) * porosity_map).sum() / (
            porosity_map.size * 100
        )
    else:
        input_volume_porosity = (input_array > 0).sum() / input_array.size
        input_resolved_porosity = input_volume_porosity
        input_subscale_porosity = 0.0

    voxel_volume = scale[0] * scale[1] * scale[2]
    input_total_volume = input_array.size * voxel_volume

    pore_resolved_volume = pn_properties["pore.volume"][pn_properties["pore.phase"] == 1].sum()
    pore_subscale_volume = (
        pn_properties["pore.volume"][pn_properties["pore.phase"] > 1]
        * pn_properties["pore.subresolution_porosity"][pn_properties["pore.phase"] > 1]
    ).sum()
    pore_total_volume = pore_resolved_volume + pore_subscale_volume

    throat_resolved_volume = pn_properties["throat.volume"][pn_properties["throat.phases_0"] == 1].sum()
    throat_resolved_volume += pn_properties["throat.volume"][pn_properties["throat.phases_1"] == 1].sum()
    throat_subscale_volume = (
        pn_properties["throat.volume"][pn_properties["throat.phases_0"] > 1]
        * pn_properties["throat.subresolution_porosity"][pn_properties["throat.phases_0"] > 1]
    ).sum()
    throat_subscale_volume += (
        pn_properties["throat.volume"][pn_properties["throat.phases_1"] > 1]
        * pn_properties["throat.subresolution_porosity"][pn_properties["throat.phases_1"] > 1]
    ).sum()
    throat_total_volume = throat_resolved_volume + throat_subscale_volume

    pn_properties["network.input_volume_porosity"] = input_volume_porosity
    pn_properties["network.input_resolved_porosity"] = input_resolved_porosity
    pn_properties["network.input_subscale_porosity"] = input_subscale_porosity
    pn_properties["network.input_total_volume"] = input_total_volume
    pn_properties["network.voxel_volume"] = voxel_volume

    pn_properties["network.pore_resolved_volume"] = pore_resolved_volume
    pn_properties["network.pore_subscale_volume"] = pore_subscale_volume
    pn_properties["network.pore_total_volume"] = pore_total_volume
    pn_properties["network.pore_resolved_porosity"] = pore_resolved_volume / input_total_volume
    pn_properties["network.pore_subscale_porosity"] = pore_subscale_volume / input_total_volume
    pn_properties["network.pore_total_porosity"] = pore_total_volume / input_total_volume

    pn_properties["network.throat_resolved_volume"] = throat_resolved_volume
    pn_properties["network.throat_subscale_volume"] = throat_subscale_volume
    pn_properties["network.throat_total_volume"] = throat_total_volume
    pn_properties["network.throat_resolved_porosity"] = throat_resolved_volume / input_total_volume
    pn_properties["network.throat_subscale_porosity"] = throat_subscale_volume / input_total_volume
    pn_properties["network.throat_total_porosity"] = throat_total_volume / input_total_volume

    return pn_properties


def general_pn_extract(
    multiphaseNode: slicer.vtkMRMLLabelMapVolumeNode,
    watershedNode: slicer.vtkMRMLLabelMapVolumeNode,
    method: str,
    porosity_map=None,
    watershed_blur=0.4,
    force_cpu=False,
):
    """
    Creates two table nodes describing the pore-network represented by multiphaseNode or by the watershedNode.

    :param multiphaseNode:
        The node containing the phases of each pixel (Solid, Pore and Subresolution).
    :param watershedNode:
        The node containing the watershed of the image used to separate pores.
    :param method:
        Either "PoreSpy" or "PNExtract".
        PoreSpy mas receive a labeled volume (each pore must have an unique number),
        while PNExtract receives a binary volume (0 for solid, >0 for por space), a labeled
        volume can be obtained by performing a watershed segmentation on a binary image.
        PNExtract is prone to crash with large volumes, and should be available only on
        developer mode.
    :param porosity_map:
        Numpy array with the porosity map (range 0~100).

    :return:
        Two table nodes describing the pore-network represented by multiphaseNode/watershedNode or False if method if not found or the pore-network
        properties could not be extracted.
    """

    if method == "PoreSpy":
        input_multiphase = None
        input_watershed = None
        if multiphaseNode is not None:
            inputNode = multiphaseNode
            input_multiphase = slicer.util.arrayFromVolume(multiphaseNode)
        if watershedNode is not None:
            inputNode = watershedNode
            input_watershed = get_connected_array_from_node(watershedNode)
        # Convert from adimensional voxel size to node scale
        # TODO: Deal with anisotropic data PL-1370
        scale = inputNode.GetSpacing()[::-1]
        try:
            pn_properties = _porespy_extract(
                input_multiphase,
                input_watershed,
                scale,
                porosity_map=porosity_map,
                watershed_blur=watershed_blur,
                force_cpu=force_cpu,
            )
        except TypeError:
            raise RuntimeError("Empty network extracted from porespy.")
        if pn_properties is False:
            return False
    elif method == "PNExtract":
        print("Method is no longer supported")
        return False
    else:
        print(f"method not found: {method}")
        return False

    pn_throats = {}
    pn_pores = {}
    pn_network = {}
    for i in pn_properties.keys():
        if "pore." in i:
            pn_pores[i] = pn_properties[i]
        elif "throat." in i:
            pn_throats[i] = pn_properties[i]
        elif "network." in i:
            pn_network[i] = pn_properties[i]

    df_pores = pd.DataFrame(pn_pores)
    df_throats = pd.DataFrame(pn_throats)
    df_network = pd.DataFrame(pn_network, index=[0])

    return df_pores, df_throats, df_network


def multiscale_extraction(
    inputPorosityNode: slicer.vtkMRMLScalarVolumeNode,
    inputWatershed: slicer.vtkMRMLLabelMapVolumeNode,
    method: str,
    watershed_blur: dict,
    force_cpu=False,
):
    porosity_array = slicer.util.arrayFromVolume(inputPorosityNode)
    if np.issubdtype(porosity_array.dtype, np.floating):
        if porosity_array.max() <= 1:
            porosity_array = (100 * porosity_array).astype(np.uint8)
        else:
            porosity_array = porosity_array.astype(np.uint8)

    resolved_array = (porosity_array == 100).astype(np.uint8)
    unresolved_array = np.logical_and(porosity_array > 0, porosity_array < 100).astype(np.uint8)
    multiphase_array = resolved_array + (2 * unresolved_array)

    slicer.util.updateVolumeFromArray(inputPorosityNode, multiphase_array)

    extract_result = general_pn_extract(
        inputPorosityNode,
        inputWatershed,
        method=method,
        porosity_map=porosity_array,
        watershed_blur=watershed_blur,
        force_cpu=force_cpu,
    )

    return extract_result
