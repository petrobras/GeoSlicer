import numpy as np
import skimage
from skimage import draw
import logging


# Return points of a circunference centered at the origin
# of the coordinates system
def return_coordinates(radius):
    rr, cc = draw.circle_perimeter(
        r=0,
        c=0,
        radius=radius,
        shape=None,
        method="andres",
    )
    return rr, cc


# The method draw.circle_perimeter generates duplicated points. This function
# return unique points
def return_unique_coordinates(rr, cc):
    coordinates = np.array([rr, cc]).T
    values, index = np.unique(coordinates, axis=0, return_index=True)
    uniques = coordinates[np.sort(index)]
    rr = uniques[:, 0]
    cc = uniques[:, 1]
    return rr, cc


def return_sorted_coordinates(radius):
    rr, cc = return_unique_coordinates(*return_coordinates(radius))

    coordinates = np.array((rr, cc)).T
    quad_1_cond = (coordinates[:, 0] <= 0) & (coordinates[:, 1] >= 0)
    quad_2_cond = (coordinates[:, 0] <= 0) & (coordinates[:, 1] < 0)
    quad_3_cond = (coordinates[:, 0] > 0) & (coordinates[:, 1] < 0)
    quad_4_cond = (coordinates[:, 0] > 0) & (coordinates[:, 1] >= 0)

    quad_1_coords = coordinates[quad_1_cond]
    quad_1_ordered = quad_1_coords[(-quad_1_coords[:, 0]).argsort()]
    quad_1_ordered = quad_1_ordered[(-quad_1_ordered[:, 1]).argsort(kind="mergesort")]

    quad_2_coords = coordinates[quad_2_cond]
    quad_2_ordered = quad_2_coords[(quad_2_coords[:, 0]).argsort()]
    quad_2_ordered = quad_2_ordered[(-quad_2_ordered[:, 1]).argsort(kind="mergesort")]

    quad_3_coords = coordinates[quad_3_cond]
    quad_3_ordered = quad_3_coords[(quad_3_coords[:, 0]).argsort()]
    quad_3_ordered = quad_3_ordered[(quad_3_ordered[:, 1]).argsort(kind="mergesort")]

    quad_4_coords = coordinates[quad_4_cond]
    quad_4_ordered = quad_4_coords[(-quad_4_coords[:, 0]).argsort()]
    quad_4_ordered = quad_4_ordered[(quad_4_ordered[:, 1]).argsort(kind="mergesort")]

    sorted_coordenates = np.concatenate(
        (
            quad_1_ordered,
            quad_2_ordered,
            quad_3_ordered,
            quad_4_ordered,
        )
    )

    return sorted_coordenates


def get_unwrap(image, radius, radius_shift_y=None, radius_shift_x=None):
    if radius_shift_y is None:
        radius_shift_y = radius
    if radius_shift_x is None:
        radius_shift_x = radius
    coords = return_sorted_coordinates(radius) + (radius_shift_y, radius_shift_x)
    unwrap = np.zeros((image.shape[0], coords.shape[0]))

    unwrap[:, :] = image[:, coords[:, 0], coords[:, 1]]
    # for i in range(image.shape[0]):
    #    unwrap[i, :] = image[i, ...][coords[:, 0], coords[:, 1]]
    return unwrap


def get_wrap(image, radius, radius_shift_y=None, radius_shift_x=None):
    if radius_shift_y is None:
        radius_shift_y = radius
    if radius_shift_x is None:
        radius_shift_x = radius
    coords = return_sorted_coordinates(radius) + (radius_shift_y, radius_shift_x)
    wrapped = np.zeros((image.shape[0], radius * 2 + 2, radius * 2 + 2))
    wrapped[:, coords[:, 0], coords[:, 1]] = image[:, 0 : len(coords)]
    # for i in range(image.shape[0]):
    #    wrapped[i, ...][coords[:, 0], coords[:, 1]] = image[i, :]
    return wrapped


def reshape_3d_imagelog(img, outputshape):
    """
    Reshapes a 3D image log into a 3D shape that must be (height, width, width).
    Remember that the last two dimensions must be equal.
    """
    if len(outputshape) != 3:
        logging.info(f"outputshape given is {len(outputshape)}, but it must be 3")
        return
    if outputshape[1] != outputshape[2]:
        logging.info(f"outputshape given is {outputshape}, but it must be (height, width, width)")
        return
    # radius = radius_shift = outputshape[-1] // 2 - 1
    radius = outputshape[-1] // 2 - 1
    height = outputshape[0]
    coords = return_sorted_coordinates(radius)  # + radius_shift
    imglog3d = img
    unwrapradius = imglog3d.shape[-1] // 2 - 1
    imglog2d = get_unwrap(imglog3d, unwrapradius)

    output_shape = (height, coords.shape[0])
    imglog2d = skimage.transform.resize(imglog2d, output_shape=output_shape, order=0, anti_aliasing=False)
    imglog3d = get_wrap(imglog2d, outputshape[-1] // 2 - 1, outputshape[-1] // 2 - 1)
    return imglog3d


def get_unwrapped_cond_array(warray, radius_shift_y=None, radius_shift_x=None):
    imglog3d = warray[0, 0, ...]
    unwrapradius = imglog3d.shape[-1] // 2 - 1
    if radius_shift_y is None:
        radius_shift_y = unwrapradius
    if radius_shift_x is None:
        radius_shift_x = unwrapradius
    imglog2d = get_unwrap(imglog3d, unwrapradius, radius_shift_y=radius_shift_y, radius_shift_x=radius_shift_x)
    out = np.zeros(
        (
            warray.shape[0],
            warray.shape[1],
        )
        + imglog2d.shape
    )
    for idx in range(out.shape[0]):
        for channel in range(out.shape[1]):
            out[idx][channel] = get_unwrap(
                warray[idx, channel, ...], unwrapradius, radius_shift_y=radius_shift_y, radius_shift_x=radius_shift_x
            )
    return out


def get_wrapped_cond_array(uarray, radius, radius_shift_y=None, radius_shift_x=None):
    if radius_shift_y is None:
        radius_shift_y = radius
    if radius_shift_x is None:
        radius_shift_x = radius

    out = np.zeros(
        (
            uarray.shape[0],
            uarray.shape[1],
            uarray.shape[2],
            uarray.shape[2],
            uarray.shape[2],
        )
    )
    for idx in range(out.shape[0]):
        for channel in range(out.shape[1]):
            out[idx, channel] = get_wrap(
                uarray[idx, channel], radius, radius_shift_y=radius_shift_y, radius_shift_x=radius_shift_x
            )
    return out


def create_image_log_mask(image_shape, radius, radius_shift_y=None, radius_shift_x=None):
    """
    Creates a cylinder mask in the image log voxels positions
    """
    if radius_shift_y is None:
        radius_shift_y = radius
    if radius_shift_x is None:
        radius_shift_x = radius
    coords = return_sorted_coordinates(radius) + (radius_shift_y, radius_shift_x)
    limits_circunference = [radius + radius_shift_y + 2, radius + radius_shift_x + 2]
    limits_shape = [image_shape[1], image_shape[2]]
    coords = coords[(coords[:, 0] >= 0) & (coords[:, 1] >= 0)]
    coords = coords[(coords[:, 0] < limits_circunference[0]) & (coords[:, 1] < limits_circunference[1])]
    coords = coords[(coords[:, 0] < limits_shape[0]) & (coords[:, 1] < limits_shape[1])]

    mask = np.zeros(image_shape)
    mask[:, coords[:, 0], coords[:, 1]] = 1
    # for i in range(image_shape_z):
    #    mask[i, ...][coords[:, 0], coords[:, 1]] = 1
    return mask
