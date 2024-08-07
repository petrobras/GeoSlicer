import math
import time
from multiprocessing import Pool

import numpy as np
from numba import njit, jit
from recordtype import recordtype
from scipy.ndimage import distance_transform_edt
from skimage.filters import gaussian
from skimage.segmentation import expand_labels

import pyedt


def generate_pore_network_label_map(pore_label_map, smooth_filter_sigma, num_processes):
    """
    Generates the segmentation of the pore label map, using medial surface and maximal spheres, as described by:
    https://journals.aps.org/pre/abstract/10.1103/PhysRevE.96.013312

    :param pore_label_map: the input pore space labeled as 1, and the matrix as 0
    :param smooth_filter_sigma: the strength of the smoothing filter applied at the final result
    :return: Results object, containing the segmented pore space
    """

    start_time = time.time()

    pore_distance_map = generate_pore_distance_map(pore_label_map)
    pore_medial_surface = generate_pore_medial_surface(pore_distance_map)
    pore_medial_surface_label_map, _ = generate_pore_medial_surface_label_map(pore_medial_surface)
    pore_medial_surface_expanded_label_map = generate_pore_medial_surface_expanded_label_map(
        pore_medial_surface_label_map, pore_label_map, smooth_filter_sigma, num_processes
    )

    Results = recordtype("Results", [("im", None), ("dt", None), ("peaks", None), ("regions", None)])
    Results.regions = pore_medial_surface_expanded_label_map

    print("### generate_pore_network_label_map:", time.time() - start_time, "seconds")

    return Results


def generate_pore_distance_map(pore_label_map):
    if pore_label_map.shape[0] == 1:
        pore_distance_map = distance_transform_edt(pore_label_map)
    else:
        pore_distance_map = pyedt.edt(pore_label_map)
    return pore_distance_map


def generate_pore_medial_surface(pore_distance_map):
    pore_distance_map = filter_distance_map_node_array(pore_distance_map)
    pore_medial_surface = np.full(pore_distance_map.shape, 0.0)
    subarray_shape = np.array([3, 3, 3])

    start_time = time.time()

    # Getting the local maxima on the distance map array
    localPeaks = get_pore_local_peaks(pore_distance_map, np.array([3, 3, 3]))

    pore_distance_map, pore_medial_surface = remove_overlapped_maximal_spheres(
        pore_distance_map, pore_medial_surface, localPeaks
    )

    print("### generate_pore_medial_surface", time.time() - start_time, "seconds")

    return pore_medial_surface


def generate_pore_medial_surface_label_map(pore_medial_surface):
    """
    Labels the medial surface using the maximal sphere hierarchy algorithm:
    https://journals.aps.org/pre/abstract/10.1103/PhysRevE.96.013312

    :param pore_medial_surface: medial surface generated from generate_pore_medial_surface
    :return: labeled pore medial surface
    """

    start_time = time.time()

    maximal_sphere_hierarchy = build_maximal_sphere_hierarchy(pore_medial_surface, PoreMaximalSphere)
    pore_medial_surface_label_map = np.full(pore_medial_surface.shape, 0)
    set_labels_from_maximal_spheres_hierarchy(pore_medial_surface_label_map, maximal_sphere_hierarchy)

    print("### generate_pore_medial_surface_label_map", time.time() - start_time, "seconds")

    return pore_medial_surface_label_map, maximal_sphere_hierarchy


def generate_pore_medial_surface_expanded_label_map(
    pore_medial_surface_label_map, pore_label_map, smooth_filter_sigma, num_processes
):
    """
    Expands the result of the labeled pore medial surface to the whole pore space

    :param pore_medial_surface_label_map
    :param pore_label_map
    :param smooth_filter_sigma
    :return: expanded labeled pore medial surface
    """

    start_time = time.time()

    pore_medial_surface_expanded_label_map = pore_medial_surface_label_map.copy()
    pore_medial_surface_expanded_label_map = expand_all_labels(pore_medial_surface_expanded_label_map, pore_label_map)
    pore_medial_surface_expanded_label_map = smooth_labels(
        pore_medial_surface_expanded_label_map, smooth_filter_sigma, num_processes
    )

    print("### generate_pore_medial_surface_expanded_label_map", time.time() - start_time, "seconds")

    return pore_medial_surface_expanded_label_map


def filter_distance_map_node_array(distanceMapNodeArray, distance=2):
    distanceMapNodeArray[distanceMapNodeArray < distance] = 0
    return distanceMapNodeArray


def build_maximal_sphere_hierarchy(medial_surface_array, maximal_sphere_class):
    """
    Builds the maximal sphere hierarchy
    https://journals.aps.org/pre/abstract/10.1103/PhysRevE.96.013312

    :param medial_surface_array
    :param maximal_sphere_class
    :return: the hierarchy of the medial surface points, used later to determine the labeled medial surface
    """
    start_time = time.time()

    maximal_spheres = get_sorted_maximal_spheres_by_radius(medial_surface_array, maximal_sphere_class)
    maximal_spheres_groups = get_grouped_maximal_spheres_by_radius(maximal_spheres)

    label = 1
    for radius, maximal_spheres_group in maximal_spheres_groups.items():
        # print(f"{len(maximal_spheres_group)} spheres for radius {radius}")

        while maximal_spheres_group:
            maximal_spheres_group = get_sorted_maximal_spheres_by_rank(maximal_spheres_group)
            maximal_sphere = maximal_spheres_group[0]
            if maximal_sphere.rank == -1:
                maximal_sphere.rank = 0
                maximal_sphere.label = label
                label += 1
            for coordinate in get_local_sorted_maximal_spheres_by_radius(
                medial_surface_array, maximal_sphere.coordinates, maximal_sphere.radius
            ):
                candidate_child_maximal_sphere = maximal_spheres[coordinate]
                if is_parent(candidate_child_maximal_sphere, maximal_sphere):
                    candidate_child_maximal_sphere.parent = maximal_sphere
                    candidate_child_maximal_sphere.rank = maximal_sphere.rank + 1
                    candidate_child_maximal_sphere.label = maximal_sphere.label
                    maximal_sphere.children.append(candidate_child_maximal_sphere)
            maximal_spheres_group.remove(maximal_sphere)

    print("### build_maximal_sphere_hierarchy", time.time() - start_time, "seconds")

    return maximal_spheres


def expand_all_labels(label_map, mask):
    """
    Expands all labels from the label map, until there are no more voxels to fill
    :param label_map:
    :param mask:
    :return: expanded label map
    """
    start_time = time.time()

    expand_distance = int(np.ceil(max(label_map.shape) / 20))
    i = 0
    while np.count_nonzero(label_map[mask == 1] == 0) > 0:
        # print(f"expand iteration {i}")
        label_map = expand_labels(label_map, distance=expand_distance)
        i += 1
    label_map[mask == 0] = 0

    print("### expand_all_labels:", time.time() - start_time, "seconds")

    return label_map


def smooth_labels(label_map, smooth_filter_sigma, num_processes=8):
    """
    Apply a smoothing filter to all the labels
    :param label_map
    :param smooth_filter_sigma: the number of standard deviations used by the smoothing gaussian function
    :param num_processes: the number of processes to use
    :return: smoothed label map
    """

    def split_list_in_groups(lst, num_groups):
        split_indices = np.array_split(np.arange(len(lst)), num_groups)
        return [[lst[i] for i in indices] for indices in split_indices if len(indices)]

    start_time = time.time()

    if smooth_filter_sigma > 0:
        labels = np.unique(label_map[label_map != 0])
        labels_groups = split_list_in_groups(labels, num_processes)

        with Pool(num_processes) as pool:
            args = [(label_map, label_group, smooth_filter_sigma) for label_group in labels_groups]
            results = pool.map(apply_filter_on_label_group, args)

        label_map = np.max(results, axis=0)

    print("### smooth_labels:", time.time() - start_time, "seconds")

    return label_map


def apply_filter_on_label_group(args):
    label_map, label_group, sigma = args
    for label in label_group:
        label_map = apply_filter_on_label(label_map, label, sigma)
    label_map[~np.isin(label_map, label_group)] = 0
    return label_map


@njit
def get_pore_local_peaks(distance_map_node_array, subarray_shape):
    """
    Algorithm to find local peaks in subarray intervals inside a distance map array
    :param distance_map_node_array
    :param subarray_shape
    :return: a dictionary of sorted by descending local peaks, with the key as the peak coordinate
    """

    def get_second_element(sublist):
        return sublist[1]

    depth, rows, cols = distance_map_node_array.shape
    subarray_depth, subarray_rows, subarray_cols = subarray_shape

    max_values_list = []

    for d in range(0, depth, subarray_depth):
        for i in range(0, rows, subarray_rows):
            for j in range(0, cols, subarray_cols):
                subarray = distance_map_node_array[d : d + subarray_depth, i : i + subarray_rows, j : j + subarray_cols]
                max_value = np.max(subarray)
                if max_value != 0:
                    max_indices = np.where(subarray == max_value)
                    max_coord_subarray = list(zip(*max_indices))[0]
                    max_coord = (d + max_coord_subarray[0], i + max_coord_subarray[1], j + max_coord_subarray[2])
                    max_values_list.append((max_coord, max_value))

    max_values_list = sorted(max_values_list, key=get_second_element, reverse=True)

    return max_values_list


def remove_overlapped_maximal_spheres(pore_distance_map, pore_medial_surface, local_peaks):
    """
    Algorithm to remove all the unwanted voxels as the medial surface is built. This function is called several times
    until there are no more voxels to be removed. The voxel removal rules are described by:
    https://journals.aps.org/pre/abstract/10.1103/PhysRevE.96.013312

    :param pore_distance_map
    :param pore_medial_surface
    :param local_peaks
    :return: the pore distance map, with some removed voxels
    """
    start_time = time.time()

    for coordinate, value in local_peaks:
        if pore_distance_map[coordinate] == 0:
            continue

        border = int(np.ceil(value + 1))

        x_slice = slice(max(0, coordinate[0] - border), min(pore_distance_map.shape[0], coordinate[0] + border))
        y_slice = slice(max(0, coordinate[1] - border), min(pore_distance_map.shape[1], coordinate[1] + border))
        z_slice = slice(max(0, coordinate[2] - border), min(pore_distance_map.shape[2], coordinate[2] + border))

        # Creating a meshgrid of coordinates
        x, y, z = np.ogrid[x_slice, y_slice, z_slice]

        # Calculating the distance from each point to the coordinate
        distance_to_coordinate = np.sqrt((x - coordinate[0]) ** 2 + (y - coordinate[1]) ** 2 + (z - coordinate[2]) ** 2)

        # Setting to zero points of maximum spheres fully overlapped by the larger maximum sphere
        points_inside_maximal_sphere = (
            distance_to_coordinate + pore_distance_map[x_slice, y_slice, z_slice]
            < value + 0.5  # @TODO + 0.5 is necessary, despite the paper not adding it
        )
        pore_distance_map[x_slice, y_slice, z_slice][points_inside_maximal_sphere] = 0

        # Setting to zero points nearby the center of the maximum sphere
        points_close_center_maximal_sphere = distance_to_coordinate < 0.3 * (
            (pore_distance_map[x_slice, y_slice, z_slice] + value) / 2
        )
        pore_distance_map[x_slice, y_slice, z_slice][points_close_center_maximal_sphere] = 0

        pore_medial_surface[coordinate] = value

    print("### remove_overlapped_maximal_spheres:", time.time() - start_time, "seconds")

    return pore_distance_map, pore_medial_surface


def get_sorted_maximal_spheres_by_radius(medial_surface_array, maximal_sphere_class):
    """
    :param medial_surface_array
    :param maximal_sphere_class: the type of maximal sphere: pore or throat
    :return: a dict of all the maximal spheres in a given medial surface, where the coordinate the dict key
    """
    start_time = time.time()

    # Get non-zero indices and values
    nonzero_indices = np.transpose(np.nonzero(medial_surface_array))
    nonzero_radii = medial_surface_array[tuple(nonzero_indices.T)]

    # Use argpartition for a partial sort
    k = len(nonzero_radii)
    partition_indices = np.argpartition(nonzero_radii, -k)[-k:]

    # Sort in descending order of values
    sorted_indices = partition_indices[np.argsort(nonzero_radii[partition_indices])[::-1]]
    sorted_nonzero_indices = nonzero_indices[sorted_indices]
    sorted_nonzero_radii = nonzero_radii[sorted_indices]

    # Create a dictionary of MaximalSphere objects
    sorted_maximal_spheres = {
        tuple(coordinates): maximal_sphere_class(tuple(coordinates), radius)
        for coordinates, radius in zip(sorted_nonzero_indices, sorted_nonzero_radii)
    }

    print("### get_sorted_maximal_spheres_by_radius:", time.time() - start_time, "seconds")

    return sorted_maximal_spheres


def get_local_sorted_maximal_spheres_by_radius(medial_surface_array, subarray_center, size):
    """
    Similar as get_sorted_maximal_spheres_by_radius function, but just acts locally, in a cube inside the medial surface
    :param medial_surface_array:
    :param subarray_center
    :param size
    :return:
    """
    size = 2 * int(np.round(size)) + 1
    x, y, z = subarray_center

    # Calculate the bounds for subarray extraction
    start_x, end_x = max(0, x - size), min(medial_surface_array.shape[0], x + size + 1)
    start_y, end_y = max(0, y - size), min(medial_surface_array.shape[1], y + size + 1)
    start_z, end_z = max(0, z - size), min(medial_surface_array.shape[2], z + size + 1)

    # Extract the subarray and original coordinates
    subarray = medial_surface_array[start_x:end_x, start_y:end_y, start_z:end_z]
    original_coordinates = (start_x, start_y, start_z)

    # Calculate coordinates in relation to the original array
    x_offset, y_offset, z_offset = original_coordinates
    coordinates = np.column_stack(np.where(subarray != 0)) + np.array([x_offset, y_offset, z_offset])
    values = subarray[subarray != 0]

    # Sort coordinates by values in descending order
    sorted_coordinates = [
        tuple(coord) for coord, _ in sorted(zip(coordinates, values), key=lambda x: x[1], reverse=True)
    ]

    return sorted_coordinates


def get_grouped_maximal_spheres_by_radius(sorted_maximal_spheres):
    """
    Groups the maximal spheres by their radius
    :param sorted_maximal_spheres
    :return: a dict of grouped maximal spheres by radius, with radius as key
    """
    start_time = time.time()

    grouped_maximal_spheres = {}
    for _, maximal_sphere in sorted_maximal_spheres.items():
        radius = maximal_sphere.radius
        if radius not in grouped_maximal_spheres:
            grouped_maximal_spheres[radius] = []
        grouped_maximal_spheres[radius].append(maximal_sphere)

    print("### get_grouped_maximal_spheres_by_radius:", time.time() - start_time, "seconds")

    return grouped_maximal_spheres


def get_sorted_maximal_spheres_by_rank(maximal_spheres):
    """
    Sorts the maximal spheres by their rank
    :param maximal_spheres
    :return: dict of maximal spheres sorted by rank
    """
    sorted_maximal_spheres = sorted(maximal_spheres, key=lambda sphere: sphere.rank)
    return sorted_maximal_spheres


def is_parent(child, parent_candidate):
    """
    Algorithm to determine if a maximal sphere is parent of another. This defines the maximal sphere hierarchy and the
    resulting segmentation
    :param child: child maximal sphere
    :param parent_candidate: the maximal sphere parent candidate
    :return: True if the parent candidate is a parent, False otherwise
    """

    def get_relative_distance(maximal_sphere_1, maximal_sphere_2):
        distance = math.hypot(*[c - p for c, p in zip(maximal_sphere_1.coordinates, maximal_sphere_2.coordinates)])
        return distance / (maximal_sphere_1.radius + maximal_sphere_2.radius)

    relative_distance = get_relative_distance(child, parent_candidate)

    if child.rank == -1 and parent_candidate.radius > child.radius and relative_distance < 1:
        return True

    if (
        child != parent_candidate
        and parent_candidate.radius > child.radius
        and (child.parent and relative_distance < 1 and relative_distance < get_relative_distance(child, child.parent))
    ):
        child.parent.children.remove(child)
        return True

    return False


def set_labels_from_maximal_spheres_hierarchy(label_map, maximal_sphere_hierarchy):
    """
    Populates a label map with all the points from a maximal sphere hierarchy, by their defined labels
    :param label_map
    :param maximal_sphere_hierarchy
    :return: labeled array following the maximal sphere hierarchy
    """
    for _, maximal_sphere in maximal_sphere_hierarchy.items():
        label_map[maximal_sphere.coordinates] = maximal_sphere.label


def apply_filter_on_label(label_map, label, sigma):
    """
    Applies a filter (gaussian) on a specific label
    :param label_map
    :param label: the target label
    :param sigma: the gaussian function standard deviation (the larger the value, the smoother the result)
    :return: label map with the target label smoothed
    """
    label_mask = label_map == label
    margin = 2 * sigma

    # Find the indices of the label mask
    label_mask_indices = np.where(label_mask)

    if any(len(subarray) == 0 for subarray in label_mask_indices):
        return label_map

    # Get the minimum and maximum indices along each dimension
    min_indices = np.maximum(np.min(label_mask_indices, axis=1) - margin, 0)
    max_indices = np.minimum(np.max(label_mask_indices, axis=1) + margin + 1, np.array(label_mask.shape))

    # Extract the label_mask_subarray around the mask with the safety margin
    label_mask_subarray = label_mask[
        min_indices[0] : max_indices[0], min_indices[1] : max_indices[1], min_indices[2] : max_indices[2]
    ]

    # Apply the filter to the label_mask_subarray
    label_mask_subarray = gaussian(label_mask_subarray, sigma=sigma)

    label_map_subarray = label_map[
        min_indices[0] : max_indices[0], min_indices[1] : max_indices[1], min_indices[2] : max_indices[2]
    ]

    label_map_subarray[np.logical_and(label_map_subarray != 0, label_mask_subarray > 0.1)] = label

    # Update the original array with the filtered label_mask_subarray
    label_map[
        min_indices[0] : max_indices[0], min_indices[1] : max_indices[1], min_indices[2] : max_indices[2]
    ] = label_map_subarray

    return label_map


class MaximalSphere:
    def __init__(self, coordinates, radius):
        self.coordinates = coordinates
        self.radius = radius
        self.rank = -1
        self.parent = None
        self.label = -1
        self.children = []


class PoreMaximalSphere(MaximalSphere):
    def __init__(self, coordinates, radius):
        super().__init__(coordinates, radius)


class ThroatMaximalSphere(MaximalSphere):
    def __init__(self, coordinates, radius):
        super().__init__(coordinates, radius)
