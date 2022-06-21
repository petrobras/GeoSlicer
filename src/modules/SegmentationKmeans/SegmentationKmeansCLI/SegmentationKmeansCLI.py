#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

# IMPORTANT never forget to start your CLI with those lines above

from __future__ import print_function

# These imports should go first to guarantee the transversing of wrapped classes by instantiation time
# Refer to github.com/Slicer/Slicer/issues/6484
import vtk, slicer, slicer.util, mrml

import csv
from dask.distributed import Client, LocalCluster
from numba import njit
import numpy as np
from scipy.cluster.vq import whiten
from scipy.interpolate import griddata
import sklearn.cluster
from time import time

from ltrace.slicer.cli_utils import writeDataInto, readFrom, progressUpdate
import microtom


@njit
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


@njit
def gradient(img):
    img = img.astype(np.float64)
    grad = np.zeros(img.shape)

    for i in range(1, img.shape[0] - 1):
        for j in range(1, img.shape[1] - 1):
            for k in range(1, img.shape[2] - 1):
                dx = (img[i + 1][j][k] - img[i - 1][j][k]) / 2.0
                dy = (img[i][j + 1][k] - img[i][j - 1][k]) / 2.0
                dz = (img[i][j][k + 1] - img[i][j][k - 1]) / 2.0
                grad[i][j][k] = np.sqrt(dx * dx + dy * dy + dz * dz)

    return grad


@njit
def process_segmentation_points(input_image, points, radii, n_attrib, min_z, i_job):
    """
    Function that calculate the attributes (based on gradients) of an image in the given points
    ----------
    input_image : chunk of the image
    points : the points in which will calculate attributes
    radii : radii to do the calculation
    n_attrib : number of attributes
    min_z : minimum value of z coordinate of the chunk
    i_job : job index.
    Returns
    -------
    attrib : numpy.array
        Array with the attributes of the chunk of image
    """
    max_radii = np.max(radii)
    points = points + np.array([max_radii - min_z, max_radii, max_radii], dtype=np.int64)

    n_radii = len(radii)
    n_points = len(points)

    data_gradient = gradient(input_image)

    attrib = np.zeros((n_points, n_attrib * n_radii))
    i_radius = 0

    for radius in radii:
        structural_element = structural_element_3d(2 * radius - 1)
        radius_minus_one = radius - 1

        for i in range(n_points):
            low_x = points[i, 0] - radius_minus_one
            low_y = points[i, 1] - radius_minus_one
            low_z = points[i, 2] - radius_minus_one
            high_x = points[i, 0] + radius
            high_y = points[i, 1] + radius
            high_z = points[i, 2] + radius

            cut_image = input_image[
                low_x:high_x,
                low_y:high_y,
                low_z:high_z,
            ]
            cut_gradient = data_gradient[
                low_x:high_x,
                low_y:high_y,
                low_z:high_z,
            ]

            attrib[i, (i_radius * n_attrib) : ((i_radius + 1) * (n_attrib))] = [
                np.mean(cut_image),
                np.std(cut_image),
                np.mean(cut_gradient),
                np.std(cut_gradient),
            ]
        i_radius = i_radius + 1

    return attrib


def determine_attributes_from_points(
    img,
    n_points,
    radii=np.array([3, 5, 9, 17, 33]),
    n_parallel_jobs=25,
    save_attrib_to=None,
    save_points_to=None,
    random_seed=12345,
):
    """
    Determine attributes of a given image based on the radii that are used to calculate the gradient
    ----------
    img : array(float)
        Array of an image in grayscale
    n_points : int
        Size of the image
    radii : array(int)
        Radii in which the gradient will be calculated
    n_parallel_jobs : int
        Number of parallel threads used for computation
    save_attrib_to : str
        Used to save the attributes in a file at the end
    save_points_to : str
        Used to save the points in a file at the end
    random_seed : int
        Random seed used in RNG of numpy
    Returns
    -------
    attrib : numpy.array
        Array with the attributes of the image
    points : numpy.array
        Array with the points used
    """
    input_image = np.array(img / img.max(), dtype=np.float64)

    # Determine the points
    np.random.seed(random_seed)

    # sorteia pontos aleatoriamente no volume da imagem
    points_x = np.random.uniform(low=0.0, high=1.0, size=[n_points]) * input_image.shape[2]
    points_y = np.random.uniform(low=0.0, high=1.0, size=[n_points]) * input_image.shape[1]
    points_z = np.random.uniform(low=0.0, high=1.0, size=[n_points]) * input_image.shape[0]
    points_z.sort()
    points = np.array((points_z, points_y, points_x), dtype=np.int64).T

    max_radius = radii.max()
    n_radii = len(radii)
    n_attrib = 4
    attrib = np.zeros((n_points, n_attrib * n_radii))

    # Preenchimento: copia uma slice da imagem (com largura max_radius) em cada direção, invertendo o sentido
    # max_radius=2: |1|2|3|4|5| => |2|1|+|1|2|3|4|5|+|5|4|
    input_image = np.concatenate(
        (input_image[:(max_radius), :, :][::-1, :, :], input_image, input_image[-(max_radius):, :, :][::-1, :, :]),
        axis=0,
    )
    input_image = np.concatenate(
        (input_image[:, :(max_radius), :][:, ::-1, :], input_image, input_image[:, -(max_radius):, :][:, ::-1, :]),
        axis=1,
    )
    input_image = np.concatenate(
        (input_image[:, :, :(max_radius)][:, :, ::-1], input_image, input_image[:, :, -(max_radius):][:, :, ::-1]),
        axis=2,
    )
    print("Input image is ready.")

    client, cluster = connectCluster(n_parallel_jobs)

    # Divide os pontos em chunks separados em z
    futures = []
    size_batch = int(n_points / n_parallel_jobs)
    for i_job in range(n_parallel_jobs):
        cur_points = points[(i_job * size_batch) : ((i_job + 1) * size_batch)]
        min_z = int(points_z[(i_job * size_batch) : ((i_job + 1) * size_batch)].min())
        max_z = int(points_z[(i_job * size_batch) : ((i_job + 1) * size_batch)].max() + 2 * max_radius + 1)
        cut_image = input_image[min_z:max_z, :, :]

        cut_image_scatter = client.scatter(cut_image)
        cur_points_scatter = client.scatter(cur_points)
        future = client.submit(
            process_segmentation_points, cut_image_scatter, cur_points_scatter, radii, n_attrib, min_z, i_job
        )
        futures.append(future)
        print(i_job, input_image.shape, cur_points.shape, min_z, max_z)

    print("Input parameters are ready. Runnning parallel jobs.")

    # Faz a segmentação paralela
    results = [future.result() for future in futures]
    disconnectCluster(client, cluster)

    print("Jobs run.")
    attrib = np.zeros((n_points, n_attrib * n_radii))
    for i_job in range(n_parallel_jobs):
        attrib[(i_job * size_batch) : ((i_job + 1) * size_batch), : (n_radii * n_attrib)] = results[i_job]

    return attrib, points


def connectCluster(workers):
    cluster = LocalCluster(n_workers=workers, processes=True, threads_per_worker=1)

    client = Client(cluster)
    return client, cluster


def disconnectCluster(client, cluster):
    client.close()
    cluster.close()


def main(args):
    st = time()

    # Read as slicer node (copy)
    master_volume_node = readFrom(args.input_volume, mrml.vtkMRMLScalarVolumeNode)
    # Access numpy view (reference)
    master_volume_array = slicer.util.arrayFromVolume(master_volume_node)

    # Resample array by spacing passed in the interface
    spacing = np.array(list(map(int, list(csv.reader([args.spacing]))[0])))
    array = master_volume_array[:: spacing[0], :: spacing[1], :: spacing[2]]
    del master_volume_array

    n_points = array.size // 2
    radii = np.array(list(map(int, list(csv.reader([args.radii]))[0])))
    print("Determining attributes from points")
    progressUpdate(value=30 / 100.0)
    attrib, points = determine_attributes_from_points(array, n_points, radii, n_parallel_jobs=int(args.threads))

    array_lenght = len(array)
    array_shape = array.shape
    del array  # deleta o array para liberar espaço na memória para o output

    n_phases = int(args.classes)
    size_pot = len(points)

    progressUpdate(value=60 / 100.0)
    print("Normalizing")
    attrib_norm = whiten(attrib)
    del attrib
    print("Kmeans")
    kmeans_result = sklearn.cluster.KMeans(n_clusters=int(n_phases), random_state=0).fit(attrib_norm)
    print("Labels")
    label = kmeans_result.predict(attrib_norm)
    del attrib_norm

    print("Formating output")
    progressUpdate(value=90 / 100.0)
    output = np.zeros(array_shape)
    mesh = np.meshgrid(
        *[np.linspace(0, 1, shape) * (shape - 1) for shape in array_shape],
        indexing="ij",
    )
    output = griddata(points, label.astype(float), tuple(mesh), method="nearest")
    output = (output + 1).astype(np.uint8)
    output = output.reshape(array_shape)

    del points, label

    # Get output node ID
    output_node_id = args.output_volume
    if output_node_id is None:
        raise ValueError("Missing output volume node")

    # Write output data manually instead of using
    # writeDataInto(output_node_id, output, mrml.vtkMRMLLabelMapVolumeNode)
    # Because of the transformations in spacing
    sn_out = slicer.vtkMRMLNRRDStorageNode()
    sn_out.SetFileName(output_node_id)
    nodeOut = mrml.vtkMRMLLabelMapVolumeNode()

    ## Do the transformations
    nodeOut.Copy(master_volume_node)
    volumeIJKToRASMatrix = vtk.vtkMatrix4x4()
    master_volume_node.GetIJKToRASMatrix(volumeIJKToRASMatrix)
    nodeOut.SetIJKToRASMatrix(volumeIJKToRASMatrix)
    nodeOut.SetOrigin(master_volume_node.GetOrigin())
    spacing_input = master_volume_node.GetSpacing() * spacing[::-1]
    nodeOut.SetSpacing(spacing_input)
    nodeOut.SetAndObserveImageData(None)

    ## And send the array to Volume
    slicer.util.updateVolumeFromArray(nodeOut, output)
    nodeOut.Modified()
    sn_out.WriteData(nodeOut)
    del output

    progressUpdate(value=100 / 100.0)
    et = time()
    print(f"Elapsed Time: {et-st}s")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument(
        "-i", "--input_volume", type=str, dest="input_volume", required=True, help="Input Scalar volume"
    )
    parser.add_argument(
        "-o", "--output_volume", type=str, dest="output_volume", default=None, help="Output LabelMap volume"
    )
    parser.add_argument("-s", "--spacing", type=str, help="Spacing of resample")
    parser.add_argument("-r", "--radii", type=str, help="Radii values")
    parser.add_argument("-c", "--classes", type=str, help="Classes quantity")
    parser.add_argument("-t", "--threads", type=str, help="Number of parallel threads")

    # This argument is automatically provided by Slicer channels, just capture it when using argparse
    parser.add_argument(
        "--returnparameterfile", type=str, default=None, help="File destination to store an execution outputs"
    )

    args = parser.parse_args()
    print(args.threads)

    if args.input_volume is None:
        raise ValueError("Missing input volume node")

    main(args)

    print("Done")
