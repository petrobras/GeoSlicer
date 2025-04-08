import logging
from math import ceil

import numpy as np
import slicer
import vtk
from numpy import dtype


def pad_width(dimlen, dtargetlen):
    if (dimlen % dtargetlen) == 0:
        return (0, 0)

    pad = dtargetlen - (dimlen % dtargetlen)

    pad_before = pad // 2
    pad_after = pad - pad_before

    return pad_before, pad_after


def center_pad(image, shape):
    xpad = pad_width(image.shape[0], shape[0])
    ypad = pad_width(image.shape[1], shape[1])
    return np.pad(image, (xpad, ypad, (0, 0)), mode="symmetric"), xpad, ypad


def tf_pad_dims(image_dim, stride, filtersize):
    h2 = int(np.ceil(image_dim / stride))
    if image_dim % stride == 0:
        pad = max(filtersize - stride, 0)
    else:
        pad = max(filtersize - (image_dim % stride), 0)
    pad_before = int(np.floor(pad / 2))
    pad_after = pad - pad_before

    return pad_before, pad_after


def crop(im, shape):
    # Check if shape was given as a fraction
    shape = np.array(shape)
    if shape[0] < 1:
        shape = np.array(im.shape) * shape
    center = np.array(im.shape) / 2
    s_im = []
    for dim in range(im.ndim):
        r = shape[dim] / 2
        lower_im = np.amax((center[dim] - r, 0))
        upper_im = np.amin((center[dim] + r, im.shape[dim]))
        s_im.append(slice(int(lower_im), int(upper_im)))
    return im[tuple(s_im)]


def crop_to_selection(data, selection, offset=0, copy=False):
    x_max = min(np.max(selection[:, 0]) + offset, data.shape[0])
    y_max = min(np.max(selection[:, 1]) + offset, data.shape[1])
    z_max = min(np.max(selection[:, 2]) + offset, data.shape[2])

    x_min = max(np.min(selection[:, 0]) - offset, 0)
    y_min = max(np.min(selection[:, 1]) - offset, 0)
    z_min = max(np.min(selection[:, 2]) - offset, 0)

    return np.array(data[x_min:x_max, y_min:y_max, z_min:z_max], copy=copy), (x_min, y_min, z_min)


def mask_with_bounds(data, mask, bounds, offset=0):
    x_max = ceil(min(np.max(bounds[:, 0]) + offset, data.shape[0]))
    y_max = ceil(min(np.max(bounds[:, 1]) + offset, data.shape[1]))
    z_max = ceil(min(np.max(bounds[:, 2]) + offset, data.shape[2]))

    x_min = ceil(max(np.min(bounds[:, 0]) - offset, 0))
    y_min = ceil(max(np.min(bounds[:, 1]) - offset, 0))
    z_min = ceil(max(np.min(bounds[:, 2]) - offset, 0))

    data[0:x_min, :, :] = 0
    data[x_max:-1, :, :] = 0

    data[:, 0:y_min, :] = 0
    data[:, y_max:-1, :] = 0

    data[:, :, 0:z_min] = 0
    data[:, :, z_max:-1] = 0

    data[x_min:x_max, y_min:y_max, z_min:z_max] *= mask


def transformPoints(transformationMatrix, points, returnInt=False):
    """
    Fast matrix method to transform between RAS and IJK points or vice versa.
    :param transformationMatrix: from IJK to RAS or RAS to IJK (from GetIJKToRASMatrix or GetRASToIJKMatrix methods)
    :param points: points in RAS or IJK coordinates
    :param returnInt: use True if you are transforming to IJK coordinates (array coordinates must be integers)
    :return: points in RAS or IJK coordinates
    """
    points = np.c_[points, np.ones(len(points))]
    transformationMatrixArray = np.zeros(16)
    transformationMatrix.DeepCopy(transformationMatrixArray, transformationMatrix)
    pointsTransformed = np.dot(transformationMatrixArray.reshape(-1, 4), points.T).T[:, :-1]
    if returnInt:
        pointsTransformed = getRoundedInteger(pointsTransformed)
    return pointsTransformed


def transformRect(transformMatrix: vtk.vtkMatrix4x4, rasRectPoints: np.ndarray, dtype=np.int32):
    operatorArray = np.zeros(16)
    transformMatrix.DeepCopy(operatorArray, transformMatrix)
    return np.dot(operatorArray.reshape(-1, 4), rasRectPoints.T).T.astype(dtype)


def volume_ras_to_ijk(ras, volume_node, as_int=True, inverse=False):
    """
    Transforms RAS coordinates associated with a volume node to their
    corresponding IJK coordinates (indexable as integers by default).

    :param ras: array of ras points
    :param volume_node: volume node associated with the given points
    :param as_int: whether to round transformed values to integers
    :param inverse: whether to convert from IJK to RAS
    """
    ras = np.asarray(ras)
    ndim = ras.ndim
    ras = np.atleast_2d(ras)

    ras1 = np.c_[ras, np.ones((ras.shape[0], 1))]
    ras_to_ijk_vtk = vtk.vtkMatrix4x4()
    volume_node.GetRASToIJKMatrix(ras_to_ijk_vtk)
    if inverse:
        ras_to_ijk_vtk.Invert()
    ras_to_ijk = slicer.util.arrayFromVTKMatrix(ras_to_ijk_vtk)
    ijk1 = (ras_to_ijk @ ras1.T).T
    ijk = ijk1[:, :3]
    if as_int:
        ijk = np.round(ijk).astype(int)
    if ndim == 1:
        ijk = ijk[0]
    return ijk


def volume_ijk_to_ras(ijk, volume_node):
    """
    Transforms IJK coordinates associated with a volume node to their
    corresponding RAS coordinates (indexable as integers by default).

    :param ijk: array of ijk points
    :param volume_node: volume node associated with the given points
    """
    return volume_ras_to_ijk(ijk, volume_node, as_int=False, inverse=True)


def getRoundedInteger(value):
    """
    :param value: Pint Quantity or a number
    """
    return np.round(value).astype(int)


def resample_segmentation(segmentation_node, factor=1, source_node=None):
    """
    Resamples the segmentation labelmap representation. Useful when the segmentation resolution is very high and a fast use of
    the segmentation tools is needed.

    :param segmentation_node: the segmentation node to be resampled
    :param factor: 0 < value <= 1
    :param source_node: a reference node to get the geometry from
    """
    geometry_widget = slicer.qMRMLSegmentationGeometryWidget()
    geometry_widget.editEnabled = True
    geometry_widget.setSegmentationNode(segmentation_node)
    if source_node is None:
        source_node = segmentation_node
    geometry_widget.setSourceNode(source_node)
    geometry_widget.setOversamplingFactor(factor)
    geometry_widget.resampleLabelmapsInSegmentationNode()
    geometry_widget.setReferenceImageGeometryForSegmentationNode()


def rescale_to(array, dtype_string):
    dtype_class = dtype(dtype_string)
    min = np.iinfo(dtype_class).min
    max = np.iinfo(dtype_class).max
    return np.interp(array, (array.min(), array.max()), [min, max]).astype(dtype_class)


def clip_to(array, dtype_string):
    dtype_class = dtype(dtype_string)
    min = np.iinfo(dtype_class).min
    max = np.iinfo(dtype_class).max
    return np.clip(array, min, max).astype(dtype_class)


def resample_if_needed(
    input_volume, reference_volume, output_volume=None, interpolation="linear", diff_threshold=1e-02
):
    """
    Resamples an input volume based on a reference volume. The resample will only occur if the node spatial descriptors
    are outside a difference threshold relative to the reference volume.

    :param input_volume: input volume to be resampled

    :param reference_volume: reference volume where the resample is based

    :param output_volume: the output volume to store de resample result. if None is provided, the output volume is the
                          input volume

    :param interpolation: the sampling algorithm:
                              - "linear"
                              - "nn" (nearest neighbor): this is selected automatically if the input is a labelmap
                              - "ws" (WindowedSync)
                              - "bs" (BSpline)

    :param diff_threshold: the relative difference between the descriptors values of the input and reference volumes to
                           consider applying the resample

    :return: True if resample was performed, False otherwise
    """

    def get_transform_matrix_array(volume):
        transform_matrix = vtk.vtkMatrix4x4()
        volume.GetIJKToRASMatrix(transform_matrix)
        transform_matrix_array = slicer.util.arrayFromVTKMatrix(transform_matrix)
        return transform_matrix_array

    wrong_interpolation_type = False
    if interpolation != "nn":
        if output_volume:
            if output_volume.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
                wrong_interpolation_type = True
        else:
            if input_volume.IsA(slicer.vtkMRMLLabelMapVolumeNode.__name__):
                wrong_interpolation_type = True

    if wrong_interpolation_type:
        interpolation = "nn"
        logging.warning(
            f'Interpolation type "{interpolation}" not compatible with labelmap output. Automatically changing to "nn" (nearest neighbor).'
        )

    resample_needed = False

    # If spacings are too different, resample
    if not np.allclose(input_volume.GetSpacing(), reference_volume.GetSpacing(), rtol=diff_threshold):
        resample_needed = True

    # If origins are too different, resample
    if not resample_needed:
        if not np.allclose(input_volume.GetOrigin(), reference_volume.GetOrigin(), rtol=diff_threshold):
            resample_needed = True

    # If direction matrices are too different, resample
    if not resample_needed:
        input_volume_transform_matrix = get_transform_matrix_array(input_volume)
        reference_volume_transform_matrix = get_transform_matrix_array(reference_volume)
        if not np.allclose(input_volume_transform_matrix, reference_volume_transform_matrix, rtol=diff_threshold):
            resample_needed = True

    if resample_needed:
        logging.info(f"Resampling {input_volume.GetName()}.")
        output_volume_id = output_volume.GetID() if output_volume else input_volume.GetID()
        parameters = {
            "inputVolume": input_volume.GetID(),
            "outputVolume": output_volume_id,
            "referenceVolume": reference_volume.GetID(),
            "interpolationType": interpolation,
        }
        slicer.cli.runSync(slicer.modules.resamplescalarvectordwivolume, None, parameters)
    else:
        # Clipping to the same shape if necessary
        input_array = slicer.util.arrayFromVolume(input_volume)
        reference_array = slicer.util.arrayFromVolume(reference_volume)
        if input_array.shape != reference_array.shape:
            logging.info(f"Clipping {input_volume.GetName()}.")
            output_array = pad_or_clip_array(input_array, reference_array)
            if not output_volume:
                output_volume = input_volume
            slicer.util.updateVolumeFromArray(output_volume, output_array)
            resample_needed = True

    return resample_needed


def pad_or_clip_array(input_array, reference_array):
    """
    For each axis of the input array, pads or clips it, to the shape of the reference array.

    :param input_array: input array to be altered
    :param reference_array: the reference array where the shape is to be followed
    :return: the input array with the same shape as the reference array
    """
    shape_difference = np.array(reference_array.shape) - np.array(input_array.shape)

    if np.all(shape_difference == 0):
        return input_array

    result_array = input_array.copy()

    for axis, diff in enumerate(shape_difference):
        if diff < 0:
            result_array = slice_3d_array(result_array, axis, 0, diff)
        else:
            pad_width = [(0, 0)] * 3
            pad_width[axis] = (0, diff)
            result_array = np.pad(result_array, pad_width, mode="constant")

    return result_array


def slice_3d_array(array, axis, start, end):
    """
    Slices a 3D array at a specific axis.

    :param array: input array
    :param axis: the axis to be sliced
    :param start: the starting index
    :param end: the ending index
    :return: the sliced array
    """
    if axis < 0 or axis > 2:
        raise ValueError("Axis must be 0, 1, or 2 for a 3D array.")

    if axis == 0:
        return array[start:end, :, :]
    elif axis == 1:
        return array[:, start:end, :]
    elif axis == 2:
        return array[:, :, start:end]
