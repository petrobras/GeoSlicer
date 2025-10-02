import logging
import math
from collections import namedtuple
from multiprocessing import Process, Queue, Value
from queue import Empty
from threading import Thread
from typing import List, Callable

import cv2
import numba as nb
import numpy as np
import pandas as pd
import psutil
import pyedt
import scipy as sp
import slicer.util
import vtk
from ltrace.algorithms.find_objects import find_objects
from numba.typed import List as nb_list
from scipy import ndimage
from scipy.spatial import ConvexHull
from scipy.spatial.distance import pdist
from scipy.special import ellipe
from skimage import measure
from skimage.feature import peak_local_max
from skimage.segmentation import watershed

from ltrace.transforms import transformPoints

from sklearn.decomposition import PCA


from sys import platform

if platform == "win32":
    atan2 = math.atan2
else:
    atan2 = np.arctan2


PORE_SIZE_INTERVALS = [0.062, 0.125, 0.25, 0.5, 1, 4, 32, np.inf]

PORE_SIZE_CATEGORIES = [
    "Microporo",
    "Mesoporo muito pequeno",
    "Mesoporo pequeno",
    "Mesoporo médio",
    "Mesoporo grande",
    "Mesoporo muito grande",
    "Megaporo pequeno",
    "Megaporo grande",
]

GRAIN_SIZE_INTERVALS = [0.004, 0.008, 0.016, 0.031, 0.062, 0.125, 0.25, 0.5, 1.0, 2.0, 4.0, 64.0, 256.0, np.inf]

GRAIN_SIZE_CATEGORIES = [
    "Argila",
    "Silte muito fino",
    "Silte fino",
    "Silte médio",
    "Silte grosso",
    "Areia muito fina",
    "Areia fina",
    "Areia média",
    "Areia grossa",
    "Areia muito grossa",
    "Grânulo",
    "Seixo",
    "Bloco ou Calhau",
    "Matacão",
]

CLASS_LABEL_SUFFIX = ["[label]", "[ID]", "[CID]"]

GENERIC_PROPERTIES = [
    "area (m²)",
    "insc diam (mm)",
    "azimuth (°)",
    "Circularity",
    "Perimeter over Area (1/mm)",
]


def get_pore_size_class_label_field(fields):
    for suffix in ["_label", *CLASS_LABEL_SUFFIX]:
        field = "pore_size_class" + suffix
        try:
            return fields.index(field)
        except ValueError:
            continue

    raise ValueError()


@nb.jit(nopython=True)
def remove_less_than(min_reference: int, from_: np.ndarray, placeholder=0):
    for i in range(len(from_)):
        if from_[i] < min_reference:
            from_[i] = placeholder


@nb.jit(nopython=True)
def replace_with(lookup_table, on_: np.ndarray):
    new_ = np.zeros(on_.shape, dtype=np.int32)
    data = on_.ravel()
    dest = new_.ravel()
    for i in range(len(data)):
        dest[i] = int(lookup_table[data[i]])
    return new_


@nb.jit(nopython=True)
def masking1d(voxelArray: np.ndarray, targets: list, placeholder=1):
    mask = np.zeros(voxelArray.shape, dtype=np.uint8)
    for t in targets:
        for i in range(len(voxelArray)):
            if voxelArray[i] == t:
                mask[i] = placeholder
    return mask


def normalize_labels(values, counts):
    void_label_index = None
    for i in range(len(values)):
        if values[i] == 0:
            void_label_index = i
            break

    if void_label_index is not None:
        void_label = values.pop(void_label_index)
        void_counts = counts.pop(void_label_index)

    sorted_indexing = sorted(zip(values, counts), key=lambda pair: pair[1], reverse=True)

    num_with_void = len(sorted_indexing) + 1

    lookup = nb_list(i for i in range(num_with_void))

    for i, (lb, count) in zip(range(1, num_with_void), sorted_indexing):
        lookup[lb] = i

    return lookup


def sharding(voxelArray: np.ndarray, sigma: float, neighborhood: float, volume_threshold: int = 100):
    is2D = voxelArray.ndim == 2

    kernel = np.ones((3, 3)) if is2D else np.ones((3, 3, 3))

    # Finding sure foreground area
    dt = pyedt.edt(voxelArray, closed_border=True, force_method="cpu")

    dt = ndimage.gaussian_filter(input=dt, sigma=sigma)

    localMax = peak_local_max(image=dt, min_distance=neighborhood, exclude_border=0, indices=False)

    # perform a connected component analysis on the local peaks,
    # using 8-connectivity, then appy the Watershed algorithm
    markers = ndimage.label(localMax, structure=kernel)[0]

    shards = watershed(-dt, markers, mask=voxelArray)

    values, counts = np.unique(shards, return_counts=True)

    lookup = normalize_labels(list(values), list(counts))

    for i, value in enumerate(lookup):
        if counts[i] < volume_threshold:
            lookup[i] = 0

    normalized_shards = replace_with(lookup, on_=shards)
    normalized_labels = [lb for lb in lookup if lb != 0]

    return normalized_shards, normalized_labels


def surfaceArea(points, shards, label):
    return memopt_mesh_area(points, shards, label)


def sizeClassification(size, intervals):
    for i, classSize in enumerate(intervals):
        if size <= classSize:
            return i

    raise ValueError(f"This pore size is not comparable. Expected a number, received {type(size)} [{size}]")


def mergeLabelsIntoMask(labelmap, labels_):
    mask = np.zeros(labelmap.shape, dtype=bool)
    for label in labels_:
        mask |= labelmap == label
    return mask


def findPeaks(values: np.ndarray, default=None):
    if len(values) == 0:
        return default

    if np.issubdtype(values.dtype, np.integer):
        # offset = abs(np.min(values))
        # bins = np.bincount(values + offset)
        # largerBin = np.argmax(bins) - offset
        largerBin = sp.stats.mode(values, axis=None).mode[0]
    else:
        hist, edges = np.histogram(values, bins="auto")
        largerBin = edges[np.argmax(hist)]

    return largerBin


def extendPeak(targetArray, limit, side):
    if side == "upper":
        return findPeaks(targetArray[targetArray > limit], default=limit)
    return findPeaks(targetArray[targetArray < limit], default=limit)


def saturatedPorosity(
    dry_voxel_array: np.ndarray,
    saturated_voxel_array: np.ndarray,
    norm_values: tuple = (0, 1),
    step_callback=None,
):
    layers = {}

    water = np.float32(norm_values[1])
    air = np.float32(norm_values[0])

    outputVoxelArray = (saturated_voxel_array.astype(np.float32) - dry_voxel_array) / (water - air)

    np.clip(outputVoxelArray, a_min=0.0, a_max=1.0, out=outputVoxelArray)

    layers["Macroporosity Voxels"] = len(np.where(outputVoxelArray == 1)[0])
    layers["Solid Voxels"] = len(np.where(outputVoxelArray == 0)[0])
    layers["Microporosity Voxels"] = len(np.where((0 < outputVoxelArray) & (outputVoxelArray < 1))[0])
    step_callback(10)

    return outputVoxelArray, outputVoxelArray.sum(), layers


def microporosity(
    textureVoxelArray: np.ndarray,
    labelmapVoxelArray: np.ndarray,
    labels,
    backgroundPorosity,
    stepCallback=None,
    microporosityLowerLimit: np.float32 = None,
    microporosityUpperLimit: np.float32 = None,
):
    poreLowerThreshold = None
    refSolidUpperThreshold = None

    progress = 0

    if "Macroporosity" in labels:
        porousMediumMask = labelmapVoxelArray == labels["Macroporosity"][0]
        poreLowerThreshold = (
            microporosityLowerLimit if microporosityLowerLimit else findPeaks(textureVoxelArray[porousMediumMask])
        )

        progress += len(labels["Macroporosity"])
        stepCallback(progress)

    if "Reference Solid" in labels:
        if microporosityUpperLimit is None:
            refSolidMask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Reference Solid"])
            refSolidUpperThreshold = findPeaks(textureVoxelArray[refSolidMask])
        else:
            refSolidUpperThreshold = microporosityUpperLimit
        progress += len(labels["Reference Solid"])
        stepCallback(progress)
    elif "Solid" in labels:
        if microporosityUpperLimit is None:
            refSolidMask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Solid"])
            refSolidUpperThreshold = findPeaks(textureVoxelArray[refSolidMask])
        else:
            refSolidUpperThreshold = microporosityUpperLimit
        progress += len(labels["Solid"])
        stepCallback(progress)

    microMediumMask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Microporosity"])

    if poreLowerThreshold is None and refSolidUpperThreshold is None:
        microMedium = textureVoxelArray[microMediumMask]

    if poreLowerThreshold is None:
        poreLowerThreshold = extendPeak(textureVoxelArray, np.min(microMedium), "lower")
        porousMediumMask = textureVoxelArray <= poreLowerThreshold

    if refSolidUpperThreshold is None:
        refSolidUpperThreshold = extendPeak(textureVoxelArray, np.max(microMedium), "upper")

    delta = refSolidUpperThreshold - poreLowerThreshold
    outputVoxelArray = (
        porousMediumMask + microMediumMask * np.clip((refSolidUpperThreshold - textureVoxelArray) / delta, 0, 1)
    ).astype(np.float32)

    progress += len(labels["Microporosity"])
    stepCallback(progress)

    _dtype = np.uint64 if outputVoxelArray.size >= np.iinfo(np.uint32).max else np.uint32

    label_values, label_count = np.unique(labelmapVoxelArray, return_counts=True)

    if "Ignore" in labels:
        for v in labels["Ignore"]:
            label_count = label_count[label_values != v]
            label_values = label_values[label_values != v]

    info = {"Image Size (voxels)": np.sum(label_count, dtype=_dtype)}
    coverage = {}
    for name, values in labels.items():
        sumup = 0
        for v in values:
            sumup += np.sum(label_count[(label_values == v).nonzero()], dtype=_dtype)

        coverage[f"{name} Segment Coverage (vx)"] = sumup
        coverage[f"{name} Segment Coverage (%)"] = sumup / info["Image Size (voxels)"] * 100

    info.update(
        {
            "Porous Threshold": poreLowerThreshold,
            "Solid Threshold": refSolidUpperThreshold,
            **coverage,
            "Weighted Microporosity (%)": 100
            * np.sum(outputVoxelArray[microMediumMask], dtype=np.float32)
            / info["Image Size (voxels)"],
            "Weighted Total Porosity (%)": 100
            * np.sum(outputVoxelArray, dtype=np.float32)
            / info["Image Size (voxels)"],
        }
    )

    return outputVoxelArray, info


MicroporosityData = namedtuple(
    "MicroporosityData", ["macroporosity_mask", "solid_mask", "microporosity_mask", "lower_limit", "upper_limit"]
)


def GetMicroporosityUpperAndLowerLimits(textureVoxelArray, labelmapVoxelArray, labels):
    if "Macroporosity" in labels:
        macroporosity_mask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Macroporosity"])
        macroPorosityPeak = findPeaks(textureVoxelArray[macroporosity_mask])
    else:
        macroporosity_mask = None
        macroPorosityPeak = None

    if "Reference Solid" in labels:
        solid_mask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Reference Solid"])
        solidPeak = findPeaks(textureVoxelArray[solid_mask])
    else:
        solid_mask = None
        solidPeak = None

    if "Microporosity" in labels:
        microporosity_mask = mergeLabelsIntoMask(labelmapVoxelArray, labels["Microporosity"])
        if not solidPeak or not macroPorosityPeak:
            micropores = textureVoxelArray[microporosity_mask]

        b = solidPeak or extendPeak(textureVoxelArray, np.max(micropores), "upper")
        a = macroPorosityPeak or extendPeak(textureVoxelArray, np.min(micropores), "lower")
    else:
        microporosity_mask = None
        b = None
        a = None

    microposotity_data = MicroporosityData(
        macroporosity_mask=macroporosity_mask,
        solid_mask=solid_mask,
        microporosity_mask=microporosity_mask,
        lower_limit=min(a, b),
        upper_limit=max(a, b),
    )

    return microposotity_data


@nb.jit(nopython=True)
def clip(A, amin, amax):
    for i in range(A.shape[0]):
        for j in range(A.shape[1]):
            if A[i, j] > amax:
                A[i, j] = amax
            elif A[i, j] < amin:
                A[i, j] = amin


def textureProperties(
    scalarVolume: np.ndarray, labelmap: np.ndarray, labels: List[dict], spacing=None, stepCallback=None
):
    upperLimits = []
    lowerLimits = []
    solidVoxelCounts = []
    macroVoxelCounts = []
    microVoxelCounts = []
    maxMicroValues = []
    minMicroValues = []

    microLabels = []

    if spacing is None:
        spacing = [1] * scalarVolume.ndim
    pixel_volume = np.prod(spacing)

    for index, label in enumerate(labels):
        # if the label is zero, we are examining the 'background'
        # so simply ignore it

        if label["property"] == "Ignore":
            continue

        values = scalarVolume[labelmap == label["value"]]
        voxelCount = len(values)

        if label["property"] == "Macroporosity":
            lowerLimits.append(np.mean(values) - np.std(values))
            macroVoxelCounts.append(voxelCount)
        elif label["property"] == "Microporosity":
            microLabels.append(label)
            minMicroValues.append(np.min(values))
            maxMicroValues.append(np.max(values))
        else:  # everything else is solid, can I say that?
            upperLimits.append(np.mean(values) - np.std(values))
            solidVoxelCounts.append(voxelCount)

        if stepCallback:
            stepCallback(index)

    if len(microLabels) > 0:
        upperLimit = min(upperLimits) if len(upperLimits) > 0 else np.median(maxMicroValues)
        lowerLimit = max(lowerLimits) if len(lowerLimits) > 0 else np.median(minMicroValues)

        # swap
        if upperLimit < lowerLimit:
            upperLimit, lowerLimit = lowerLimit, upperLimit

        def _porosity_estimation(sample, lower_limit, upper_limit):
            lower_region = np.count_nonzero(sample <= lower_limit)

            region = sample[(lower_limit < sample) & (sample < upper_limit)]
            total_region = np.sum((upper_limit - region) / (upper_limit - lower_limit))

            return lower_region + total_region

        for label in microLabels:
            values = labelmap[labelmap == label["value"]]
            microVoxelCounts.append(_porosity_estimation(values, lowerLimit, upperLimit))

    solidCountTotal = sum(solidVoxelCounts)
    macroCountTotal = sum(macroVoxelCounts)
    microCountTotal = sum(microVoxelCounts)

    total = solidCountTotal + macroCountTotal + microCountTotal

    resSolid = (solidCountTotal / total) * pixel_volume
    resMacro = (macroCountTotal / total) * pixel_volume
    resMicro = (microCountTotal / total) * pixel_volume

    if stepCallback:
        stepCallback(index + 1)

    return resSolid, resMacro, resMicro, total


def object_consumer(operator, queue, results, visited):
    while True:
        item = queue.get()

        if item is None:
            break

        row, objects = item

        with visited.get_lock():
            visited.value += len(objects)

        for label in objects:
            stats = operator(label, objects[label])
            if stats is None:
                continue
            results.put((row, stats))
    results.put(None)


def _executor_task(func: Callable, tasks: Queue, sender: Queue):
    processed = 0
    valid_results = []
    while True:
        row, artifacts = tasks.get(block=True)
        if row == -1:
            break

        for label, artifact in artifacts.items():
            stats = func(label, artifact)
            if stats is not None:
                valid_results.append(stats)

        processed += len(artifacts)
        if len(valid_results) >= 32:
            sender.put_nowait((processed, valid_results))
            processed = 0
            valid_results = []

    if len(valid_results) > 0:
        sender.put_nowait((processed, valid_results))

    sender.put_nowait((-1, []))


def _separator_task(im: np.ndarray, tasks: Queue, pool_size: int):
    n_artifacts = 0
    for found_segments_batch in find_objects(im):
        n_artifacts += len(found_segments_batch[1])  # (current_row, artifacts)
        tasks.put_nowait(found_segments_batch)

    # Send closing message
    for _ in range(pool_size):
        tasks.put_nowait((-1, None))


def calculate_statistics_on_segments(im: np.ndarray, operator: object, callback=None):
    from timeit import default_timer as timer

    tstart = timer()
    cpu_available = 1

    tasks = Queue()
    broker = Queue()

    for _ in range(cpu_available):
        proc = Process(target=_executor_task, args=(operator, tasks, broker))
        proc.start()

    producer = Thread(target=_separator_task, args=(im, tasks, cpu_available))
    producer.start()

    n_artifacts = np.max(im)

    _1s = 1000

    done = 0
    processed = 0
    results = []
    while done < cpu_available:
        try:
            n, stats_collected = broker.get(
                block=True, timeout=10 * _1s
            )  # freezed forever, the main thread must never be!

            if n == -1:
                done += 1
                continue

            # Update final table
            results.extend(stats_collected)

            # Update progress bar
            processed += n
            callback(processed, n_artifacts)

        except Empty:
            done += 1
            break

    table_df = pd.DataFrame(results)

    tend = timer()
    print(
        f"ELAPSED TIME = {tend - tstart}s",
    )
    return table_df, n_artifacts


def exportSegmentsAsDataFrame(im, operator, stepcb=None):
    from timeit import default_timer as timer

    tstart = timer()
    main_axis_size = im.shape[0]
    queue = Queue()
    results = Queue()
    visited = Value("I", 0)

    n_consumers = max(1, psutil.cpu_count(logical=False) - 1)
    procs = []
    for _ in range(n_consumers):
        p = Process(target=object_consumer, args=(operator, queue, results, visited))
        p.start()
        procs.append(p)
    for item in find_objects(im):
        queue.put(item)
    for _ in range(n_consumers):
        queue.put(None)

    table = []
    finished_procs = 0

    max_row = 0
    while finished_procs < n_consumers or not results.empty():
        item = results.get()
        if item is None:
            finished_procs += 1
            continue

        row, stats = item
        table.append(stats)

        # Don't let progress bar go back
        max_row = max(max_row, row)
        stepcb(max_row, main_axis_size)

    table_df = pd.DataFrame(table)

    tend = timer()
    print(
        f"ELAPSED TIME = {tend - tstart}s",
    )

    return table_df, visited.value


class ScalarStatiscs:
    def __init__(self, im):
        self.im = im

    def __call__(self, label, slices):
        fragment = self.im[slices]

        return dict(mean=np.mean(fragment), median=np.median(fragment), stddev=np.std(fragment))


def getFeretMinMax(hull, vertices):
    distances = pdist(vertices)
    return np.max(distances)


class LabelStatistics3D:
    ATTRIBUTES = (
        "label",
        "voxelCount",
        "volume",
        "max_feret",
        "aspect_ratio",
        "elongation",
        "flatness",
        "ellipsoid_area",
        "ellipsoid_volume",
        "ellipsoid_area_over_ellipsoid_volume",
        "sphere_diameter_from_volume",
        "pore_size_class",
    )

    def __init__(self, im, spacing, is_pore, size_filter=None, seed=None):
        self.im = im
        self.spacing = np.array(spacing, copy=True)
        self.voxel_size = np.prod(self.spacing)
        self.is_pore = is_pore
        self.size_filter = size_filter
        self.rng = np.random.default_rng(seed or 251972032)
        self._space = max(self.spacing)

    def surfaceArea(self, crop):
        # Use marching cubes to obtain the surface mesh of these ellipsoids
        verts, faces, normals, values = measure.marching_cubes(crop, 0)
        return measure.mesh_surface_area(verts, faces)

    def __call__(self, label, pointsInRAS):
        voxelCount = len(pointsInRAS)
        volume_mm = voxelCount * self.voxel_size

        try:
            # uniformly pick samples from a numpy array pointsInRAS
            chull = ConvexHull(pointsInRAS)

            if voxelCount > 100000:
                options = np.arange(voxelCount)
                samples = self.rng.choice(options, size=int(0.3 * voxelCount), replace=False)
                samples = np.concatenate((samples, chull.vertices))
                samples = pointsInRAS[samples]
            else:
                samples = pointsInRAS

            feretMax = getFeretMinMax(chull, pointsInRAS[chull.vertices])  # TODO optimize this

            # Perform PCA
            pca = PCA(n_components=3)
            pca.fit(pointsInRAS)

            # The eigenvalues of the covariance matrix are the variances along the axes
            axes_len = np.sort(np.sqrt(pca.explained_variance_))

            # moments_of_inertia = compute_inertia_tensor(samples)
            # Pm = np.linalg.eigvalsh(moments_of_inertia)

            if np.any(axes_len <= 1e-9):
                raise ValueError(f"Division by zero will happen. Principal moments {Pm}")

            # Reference: https://mathematica.stackexchange.com/questions/135779/aspect-ratio-of-a-convex-hull
            #            https://forum.image.sc/t/3d-shape-plugin/24880/5

            aspect_ratio = axes_len[0] / axes_len[2]
            elongation = axes_len[2] / axes_len[1]
            flatness = axes_len[1] / axes_len[0]

            # The square roots of the eigenvalues are the lengths of the axes of the ellipsoid
            semi_axes = axes_len * 0.5
            ellipsoid_surface = chull.area  # ellipsoidArea(*semiAxis[::-1])
            ellipsoid_volume = (4 / 3) * np.pi * np.prod(semi_axes)
            ellipsoid_area_over_ellipsoid_volume = ellipsoid_surface / ellipsoid_volume

            sphere_diameter_from_volume = (6 * volume_mm / np.pi) ** (1 / 3)

            intervals = PORE_SIZE_INTERVALS if self.is_pore else GRAIN_SIZE_INTERVALS
            pore_size_class = sizeClassification(feretMax, intervals)

        except (sp.spatial.qhull.QhullError, TypeError, ValueError) as e:
            return None

        return (
            label,
            voxelCount,
            volume_mm,
            feretMax,
            aspect_ratio,
            elongation,
            flatness,
            ellipsoid_surface,
            ellipsoid_volume,
            ellipsoid_area_over_ellipsoid_volume,
            sphere_diameter_from_volume,
            pore_size_class,
        )


def correct_direction(a1, a2):
    if a1 < a2:
        return np.pi - (a2 - a1)
    return a1 - a2


def calculateAnglesFromReferenceDirection(direction, major_angle, minor_angle):
    normalized_orientation_line = [np.array(v) for v in direction]
    angle_line_between_reference = get_angle_between(normalized_orientation_line, [[0, 0], [0, 1]])
    return (
        correct_direction(major_angle, angle_line_between_reference),
        correct_direction(minor_angle, angle_line_between_reference),
    )


def mock(a, b, c):
    return np.nan, np.nan


def blobers(points: np.ndarray, r=1.5) -> np.ndarray:
    """Use a KDTree to find the nearest neighbors of each point in the array.
    Then remove all points with less than 3 neighbors.
    """
    tree = sp.spatial.cKDTree(points)
    neighbors = tree.query_ball_point(points, r=r)
    return np.array([p for p, n in zip(points, neighbors) if len(n) >= 3])


# def blobers(points: np.ndarray) -> np.ndarray:
#     """ Use a KDTree to find the nearest neighbors of each point in the array.
#         Then remove all points with less than 3 neighbors.
#     """
#     dist = sp.spatial.distance.pdist(points, metric="euclidean")
#     M = sp.spatial.distance.squareform(dist)
#     mask = np.zeros(points.shape[0], dtype=bool)
#     for i, row in enumerate(M):
#         if np.count_nonzero(row < 1.5) >= 3:
#             mask[i] = True
#     return points[mask]


class LabelStatistics2D:
    ATTRIBUTES = (
        "label",
        "voxelCount",
        "area",
        "angle",
        "max_feret",
        "min_feret",
        "angle_ref_to_max_feret",
        "angle_ref_to_min_feret",
        "aspect_ratio",
        "elongation",
        "eccentricity",
        "ellipse_perimeter",
        "ellipse_area",
        "ellipse_perimeter_over_ellipse_area",
        "perimeter",
        "perimeter_over_area",
        "gamma",
        "pore_size_class",
    )

    def __init__(self, im, spacing, direction, is_pore, size_filter=0):
        self.im = im
        self.spacing = np.array(spacing, copy=True)
        self.voxel_size = np.prod(self.spacing)
        self.direction = direction
        self.is_pore = is_pore
        self.size_filter = size_filter
        self.radius = min(self.spacing) * 1.75

        if self.direction and len(self.direction) > 0:
            self.__anglesFromReferenceDirection = calculateAnglesFromReferenceDirection
        else:
            self.__anglesFromReferenceDirection = mock

    def __call__(self, label, pointsInRasBorder):
        # deprecated API
        return self.calculate(label, pointsInRasBorder)

    def calculate(self, label, pointsInRasBorder):
        pointsInRasBorder = blobers(pointsInRasBorder, r=self.radius)
        if pointsInRasBorder.shape[0] < 3:
            return None

        return self.strict_calculate(label, pointsInRasBorder)

    def strict_calculate(self, label, pointsInRasBorder):
        voxelCount = len(pointsInRasBorder)
        area_mm = voxelCount * self.voxel_size

        try:
            chull = ConvexHull(pointsInRasBorder)
            perimeter = chull.area  # yes, for 2D, the area is the perimeter

            diameter, major_angle, min_feret, minor_angle, _ = rotating_calipers(pointsInRasBorder[chull.vertices])
            eccen = np.sqrt(1 - min_feret / diameter)
            elong = np.sqrt(diameter / min_feret)

            angle_ref_to_max_feret, angle_ref_to_min_feret = self.__anglesFromReferenceDirection(
                self.direction, major_angle, minor_angle
            )

            aspect_ratio = min_feret / diameter
            ellipse_perimeter = ellipsePerimeter(diameter / 2, eccen)
            ellipse_area = ellipseArea(diameter, min_feret)

            gamma = perimeter / (2 * np.sqrt(np.pi * area_mm))

            intervals = PORE_SIZE_INTERVALS if self.is_pore else GRAIN_SIZE_INTERVALS
            pore_size_class = sizeClassification(diameter, intervals)

        except (sp.spatial.qhull.QhullError, TypeError, ValueError) as e:
            return None

        return (
            label,
            voxelCount,
            area_mm,
            as_semi_circle_degrees_from_arctan(major_angle),
            diameter,
            min_feret,
            as_semi_circle_degrees_from_arctan(angle_ref_to_max_feret),
            as_semi_circle_degrees_from_arctan(angle_ref_to_min_feret),
            aspect_ratio,
            elong,
            eccen,
            ellipse_perimeter,
            ellipse_area,
            ellipse_perimeter / ellipse_area,
            perimeter,
            perimeter / area_mm,
            gamma,
            pore_size_class,
        )


def ellipsoidArea(a, b, c):
    p = 1.6075
    a_ = a**p
    b_ = b**p
    c_ = c**p
    return 4 * np.pi * ((a_ * b_ + a_ * c_ + b_ * c_) / 3) ** (1 / p)


def ellipsePerimeter(semi_a, ecc):
    return 4 * semi_a * ellipe(ecc**2)


def ellipseArea(a, b):
    return np.pi * a * b


def dred(points):
    m = set([tuple(p) for p in points])
    N, d = points.shape
    result = []
    for p in points:
        for i in range(d):
            shift = np.zeros(d)
            shift[i] = 1

            if tuple(p - shift) not in m or tuple(p + shift) not in m:
                result.append(p)
                break

    return np.array(result, dtype=points.dtype)


def rotate(points, degrees, origin=(0, 0)):
    angle = np.deg2rad(degrees)
    R = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    o = np.atleast_2d(origin)
    p = np.atleast_2d(points)
    return np.squeeze((R @ (p.T - o.T) + o.T).T)


Coord = namedtuple("Coord", ["x", "y"])


def rotating_calipers(points):
    centroid = points.mean(axis=0)
    measurements = []

    for i in range(0, 360):
        r_points = rotate(points, degrees=i / 2.0, origin=centroid)
        x = r_points[:, 0]
        a = points[np.argmin(x)]
        b = points[np.argmax(x)]
        # distance between a and b
        width = np.linalg.norm(a - b)
        mid = (a + b) / 2.0
        relative_point = a - mid
        measurements.append((width, Coord(x=relative_point[0], y=relative_point[1])))

    measurements.sort(key=lambda v: v[0])

    feret_min, coord_min = measurements[0]
    feret_max, coord_max = measurements[-1]

    theta_min = atan2(coord_min.y, -coord_min.x)  # use negative to simulate geoslicer visualization

    theta_max = atan2(coord_max.y, -coord_max.x)  # use negative to simulate geoslicer visualization

    return feret_max, theta_max, feret_min, theta_min, centroid


def get_angle(x, y):
    theta_rad = atan2(x, y)
    return as_semi_circle_degrees_from_arctan(theta_rad)


def as_semi_circle_degrees_from_arctan(theta_rad):
    ## https://stackoverflow.com/questions/1311049/how-to-map-atan2-to-degrees-0-360
    theta_deg = theta_rad * 180 / np.pi
    if theta_rad < 0:  # handle discontinuity
        theta_deg = theta_deg + 180

    # theta_deg = (270 + (180 - theta_deg)) if theta_deg > 90 else 90 - theta_deg
    theta_deg = (theta_deg + 180) % 360 if 90 < theta_deg < 270 else theta_deg
    return theta_deg


def eigsorted(cov):
    vals, vecs = np.linalg.eigh(cov)
    order = vals.argsort()[::-1]
    return vals[order], vecs[:, order]


def ellipsoid(points):
    centroid = np.mean(points, axis=1)
    normalized_points = (points.T - centroid).T
    cov = np.cov(normalized_points)
    vals, vectors = eigsorted(cov)

    axis_length = [float(4 * np.sqrt(v)) for v in vals]
    # angle = angle - 90 if angle > 90 else angle + 90
    return centroid, vectors, axis_length, float(eccentricity(vals)), float(elongation(vals))


def get_axis_line(centroid, angle, radius):
    xc, yc = centroid
    xtop = xc + math.cos(math.radians(angle)) * radius
    ytop = yc + math.sin(math.radians(angle)) * radius
    xbot = xc + math.cos(math.radians(angle + 180)) * radius
    ybot = yc + math.sin(math.radians(angle + 180)) * radius
    return ((xbot, ybot), (xtop, ytop))


def unit_vector(vector):
    """Returns the unit vector of the vector."""
    return vector / np.linalg.norm(vector)


def zero_origin(vector):
    a, b = vector
    return np.array(np.subtract(b, a), dtype=float)


def get_angle_between(v1, v2):
    """Returns the angle in radians between vectors 'v1' and 'v2'::

    angle_between((1, 0, 0), (0, 1, 0))
    1.5707963267948966
    angle_between((1, 0, 0), (1, 0, 0))
    0.0
    angle_between((1, 0, 0), (-1, 0, 0))
    3.141592653589793
    """
    v1_u = unit_vector(zero_origin(v1))
    v2_u = unit_vector(zero_origin(v2))
    return np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))


# def major_axis_length(inertia_tensor_eigvals):
#     l1 = inertia_tensor_eigvals[0]
#     return 4 * np.sqrt(l1)
#
#
# def minor_axis_length(inertia_tensor_eigvals):
#     l2 = inertia_tensor_eigvals[-1]
#     return 4 * np.sqrt(l2)


def eccentricity(inertia_tensor_eigvals):
    minor = min(inertia_tensor_eigvals) / 2  # semi axis
    major = max(inertia_tensor_eigvals) / 2  # semi axis
    if major == 0:
        return 0
    return np.sqrt(1 - minor / major)


def elongation(inertia_tensor_eigvals):
    minor, major = min(inertia_tensor_eigvals), max(inertia_tensor_eigvals)
    if minor == 0:
        return 0
    return np.sqrt(major / minor)


def memopt_mesh_area(indexes, data, label):
    x_max = min(np.max(indexes[:, 0]) + 100, data.shape[0])
    y_max = min(np.max(indexes[:, 1]) + 100, data.shape[1])
    z_max = min(np.max(indexes[:, 2]) + 100, data.shape[2])

    x_min = max(np.min(indexes[:, 0]) - 100, 0)
    y_min = max(np.min(indexes[:, 1]) - 100, 0)
    z_min = max(np.min(indexes[:, 2]) - 100, 0)

    crop = np.array(data[x_min:x_max, y_min:y_max, z_min:z_max], copy=True)

    crop[crop != label] = 0

    # Use marching cubes to obtain the surface mesh of these ellipsoids
    verts, faces, normals, values = measure.marching_cubes(crop, 0)

    area = measure.mesh_surface_area(verts, faces)

    return area


def randomize_colors(im, keep_vals=[0]):
    r"""
    Takes a greyscale image and randomly shuffles the greyscale values, so that
    all voxels labeled X will be labelled Y, and all voxels labeled Y will be
    labeled Z, where X, Y, Z and so on are randomly selected from the values
    in the input image.
    This function is useful for improving the visibility of images with
    neighboring regions that are only incrementally different from each other,
    such as that returned by `scipy.ndimage.label`.
    Parameters
    ----------
    im : array_like
        An ND image of greyscale values.
    keep_vals : array_like
        Indicate which voxel values should NOT be altered.  The default is
        `[0]` which is useful for leaving the background of the image
        untouched.
    Returns
    -------
    image : ND-array
        An image the same size and type as ``im`` but with the greyscale values
        reassigned.  The unique values in both the input and output images will
        be identical.
    Notes
    -----
    If the greyscale values in the input image are not contiguous then the
    neither will they be in the output.
    Examples
    --------

    import scipy as sp
    sp.random.seed(0)
    im = sp.random.randint(low=0, high=5, size=[4, 4])
    print(im)

    $ [[4 0 3 3]
     [3 1 3 2]
     [4 0 0 4]
     [2 1 0 1]]

    im_rand = randomize_colors(im)
    print(im_rand)

     [[2 0 4 4]
     [4 1 4 3]
     [2 0 0 2]
     [3 1 0 1]]
    As can be seen, the 2's have become 3, 3's have become 4, and 4's have
    become 2.  1's remained 1 by random accident.  0's remain zeros by default,
    but this can be controlled using the `keep_vals` argument.
    """
    im_flat = im.flatten()
    keep_vals = sp.array(keep_vals)
    swap_vals = ~sp.in1d(im_flat, keep_vals)
    im_vals = sp.unique(im_flat[swap_vals])
    new_vals = sp.random.permutation(im_vals)
    im_map = sp.zeros(
        shape=[
            sp.amax(im_vals) + 1,
        ],
        dtype=int,
    )
    im_map[im_vals] = new_vals
    im_new = im_map[im_flat]
    im_new = sp.reshape(im_new, newshape=sp.shape(im))
    return im_new


def sidewall_sample_instance_properties(instance_mask, spacing):
    """
    Calculates the sidewall sample instance properties.

    :param instance_mask: the binary 2D array containing the instance to be evaluated
    :param spacing: the spacing from the related volume
    :return: a dictionary containing the properties of the sidewall sample instance
    """

    # Starts with -1 for the properties, and populates each one of them if successful
    properties = {"diam (cm)": -1, "circularity": -1, "solidity": -1, "azimuth (°)": -1}

    try:
        contours, _ = cv2.findContours(instance_mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        mark_contour = contours[0]
        mark_area_in_pixels = cv2.contourArea(mark_contour)
        pixel_area = spacing[0] * spacing[2]
        mark_area_in_millimeters = mark_area_in_pixels * pixel_area
        diameter_in_centimeters = 2 * math.sqrt(mark_area_in_millimeters / math.pi) / 10
        properties["diam (cm)"] = np.round(diameter_in_centimeters, 2)
    except:
        pass

    try:
        circularity = 4 * np.pi * mark_area_in_pixels / cv2.arcLength(mark_contour, True) ** 2
        properties["circularity"] = np.round(circularity, 2)
    except:
        pass

    try:
        hull = cv2.convexHull(mark_contour)
        hull_area = cv2.contourArea(hull)
        solidity = mark_area_in_pixels / hull_area
        properties["solidity"] = np.round(solidity, 2)
    except:
        pass

    try:
        moments = cv2.moments(mark_contour)
        center_x = int(np.round(moments["m10"] / moments["m00"]))
        azimuth_in_degrees = 360 * center_x / (instance_mask.shape[1] - 1)
        properties["azimuth (°)"] = int(np.round(azimuth_in_degrees))
    except:
        pass

    return properties


def generic_instance_properties(instance_mask, selected_measurements, spacing, shape=None, offset=None):
    """
    Calculates the instance generic properties.

    :param instance_mask: the binary 2D array containing the instance to be evaluated
    :param selected_measurements: binary array that controls which measurement to calculate
    :param spacing: the spacing from the related volume
    :return: a dictionary containing the generic properties of the instance
    """

    if shape is None:
        shape = instance_mask.shape

    if offset is None:
        offset = (0, 0)
    properties = {}
    for index in range(len(selected_measurements)):
        if selected_measurements[index]:
            properties[GENERIC_PROPERTIES[index]] = -1

    contours, _ = cv2.findContours(instance_mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    markAreaInPixels = np.count_nonzero(instance_mask)

    if markAreaInPixels <= 0:
        raise ValueError("Detected Label with invalid area.")

    if GENERIC_PROPERTIES[0] in properties.keys():
        try:
            pixelArea = spacing[0] * spacing[1]
            markAreaInMillimeters = markAreaInPixels * pixelArea
            markAreaInMeters = markAreaInMillimeters / (10**6)
            properties["area (m²)"] = np.round(markAreaInMeters, 8)
        except Exception as e:
            properties["area (m²)"] = np.nan
            logging.warning("Area calculation failed.")

    if GENERIC_PROPERTIES[1] in properties.keys():
        try:
            if any(instance_mask[:, 0] & instance_mask[:, -1]):
                concatenated_mask = np.concatenate([instance_mask, instance_mask], axis=1)
                padded_mask = np.pad(concatenated_mask, pad_width=1, mode="constant", constant_values=0)
            else:
                padded_mask = np.pad(instance_mask, pad_width=1, mode="constant", constant_values=0)
            dt = ndimage.distance_transform_edt(padded_mask, sampling=spacing)
            max_radius = instance_mask.shape[1] * spacing[1] / 2
            radius = np.max(dt, initial=0, where=dt < max_radius)
            diameter = 2 * radius
            properties["insc diam (mm)"] = diameter
        except Exception as e:
            properties["insc diam (mm)"] = np.nan
            logging.warning("Diameter calculation failed.")

    if GENERIC_PROPERTIES[2] in properties.keys():
        try:
            markContour = max(contours, key=cv2.contourArea)
            moments = cv2.moments(markContour)
            center_x = int(np.round(moments["m10"] / moments["m00"])) + offset[1]
            azimuth_in_degrees = 360 * center_x / (shape[1] - 1)
            properties["azimuth (°)"] = int(np.round(azimuth_in_degrees))
        except Exception as e:
            properties["azimuth (°)"] = np.nan
            logging.warning("Azimuth calculation failed.")

    if GENERIC_PROPERTIES[3] in properties.keys():
        try:
            countourPerimeter = cv2.arcLength(contours[0], True)
            countourArea = cv2.contourArea(contours[0])
            properties[GENERIC_PROPERTIES[3]] = 4 * np.pi * countourArea / countourPerimeter**2
        except Exception as e:
            properties[GENERIC_PROPERTIES[3]] = np.nan
            logging.warning("Circularity calculation failed.")

    if GENERIC_PROPERTIES[4] in properties.keys():
        try:
            rescaledContour = contours[0]
            rescaledContour[:, :, 0] = rescaledContour[:, :, 0] * spacing[0]
            rescaledContour[:, :, 1] = rescaledContour[:, :, 1] * spacing[1]

            rescaledPerimeter = cv2.arcLength(rescaledContour, True)
            rescaledArea = cv2.contourArea(rescaledContour)
            properties[GENERIC_PROPERTIES[4]] = rescaledPerimeter / rescaledArea
        except Exception as e:
            properties[GENERIC_PROPERTIES[4]] = np.nan
            logging.warning("Perimeter over Area calculation failed.")

    return properties


def crop_to_content(image, padding=0):
    """
    Crops the image to the minimum bounding box containing the non-zero pixels.

    :param image: the input image
    :return: the cropped image
    """
    instanceMaskIndices = np.nonzero(image)
    origin = [instanceMaskIndices[0].min(), instanceMaskIndices[1].min()]
    offset = (origin[0] - padding, origin[1] - padding)
    indices = (instanceMaskIndices[0] - offset[0], instanceMaskIndices[1] - offset[1])
    top = [indices[0].max() + padding + 1, indices[1].max() + padding + 1]
    instanceMask = np.zeros(top, dtype=np.uint8)
    instanceMask[indices] = 1
    return instanceMask, indices, offset


def instancesPropertiesDataFrame(labelMap, selectedMeasurements=[1, 1, 1]):
    propertiesList = []
    array = slicer.util.arrayFromVolume(labelMap)
    labels = np.unique(array)
    labels = np.delete(labels, np.where(labels == 0))

    if len(array.shape) != 3:
        raise ValueError("Invalid image type. Expected 2D image.")

    # Get the index of the minimum array shape value to determine the direction of the slicing
    min_index = np.argmin(array.shape)
    if min_index == 0:
        arraySliceCopy = array[0, :, :]
        inverted_2d_spacing = [labelMap.GetSpacing()[2], labelMap.GetSpacing()[1]]
    elif min_index == 1:
        arraySliceCopy = array[:, 0, :]
        inverted_2d_spacing = [labelMap.GetSpacing()[2], labelMap.GetSpacing()[0]]
    elif min_index == 2:
        arraySliceCopy = array[:, :, 0]
        inverted_2d_spacing = [labelMap.GetSpacing()[1], labelMap.GetSpacing()[0]]

    for label in labels:

        instanceMask, indices, offset = crop_to_content(arraySliceCopy == label, padding=3)

        if len(indices[0]) / (instanceMask.shape[0] * instanceMask.shape[1]) < 0.2:
            labeledMask, count = ndimage.label(instanceMask)
            if count > 1:
                labels = np.bincount(labeledMask.ravel())[1:]  # ignore background
                largestLabel = np.argmax(labels)
                instanceMask, _, suboffset = crop_to_content(labeledMask == largestLabel, padding=3)
                offset = (offset[0] + suboffset[0], offset[1] + suboffset[1])

        try:
            instanceProperties = generic_instance_properties(
                instanceMask, selectedMeasurements, inverted_2d_spacing, arraySliceCopy.shape, offset
            )
        except ValueError as err:
            # logging.debug(f"{err}\n{traceback.print_exc()}") # hide this error from the user for while; it's not critical; we must handle logging filters;
            continue

        instanceProperties["depth (m)"] = instance_depth(labelMap, label)
        instanceProperties["label"] = label
        propertiesList.append(instanceProperties)

    measurementColumns = [
        GENERIC_PROPERTIES[index] for index in range(len(selectedMeasurements)) if selectedMeasurements[index]
    ]
    propertiesDataFrame = pd.DataFrame(propertiesList, columns=["depth (m)", "label"] + measurementColumns)
    return propertiesDataFrame


def instances_depths(label_map_array, label_values, ijk_to_ras_matrix):
    """
    Calculates the instances depths, in kilometers.

    :param label_map_array: the label map array containing the instances labels
    :param label_values: the label values to calculate the depth
    :param ijk_to_ras_matrix: the ijk to ras matrix
    :return: the depths in kilometers (positive values)
    """
    centers_ijk = []
    problematic_labels = []
    for label_value in label_values:
        indexes = np.unique(np.where(label_map_array == label_value)[0])
        if len(indexes) == 0:
            problematic_labels.append(label_value)
            continue
        centers_ijk.append([0, 0, indexes[0]])
    centers_ras = transformPoints(ijk_to_ras_matrix, centers_ijk)
    return np.round(centers_ras[:, 2] / 1000, 2) * -1, problematic_labels


def instance_depth(label_map, label_value):
    """
    Calculates an instance depth, in kilometers.

    :param label_map: the label map node containing the instances labels
    :param label_value: the label value to calculate the depth
    :return: the depth in meters (positive values)
    """
    label_map_array = slicer.util.arrayFromVolume(label_map)
    ijk_to_ras_matrix = vtk.vtkMatrix4x4()
    label_map.GetIJKToRASMatrix(ijk_to_ras_matrix)
    indexes = np.unique(np.where(label_map_array == label_value)[0])
    center_ijk = [0, 0, indexes[0]]
    center_ras = transformPoints(ijk_to_ras_matrix, [center_ijk])
    return np.round(center_ras[0, 2] / 1000, 2) * -1


def compute_inertia_tensor(points: np.ndarray) -> np.ndarray:
    centroid = np.mean(points, axis=0)
    coords = points - centroid
    tensor = np.einsum("...ij,...ik->...jk", coords, coords)
    return tensor / len(coords)
