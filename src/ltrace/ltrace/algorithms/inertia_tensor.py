"""
function to calculate sets of inertia tensors
"""

from __future__ import absolute_import, division, print_function, unicode_literals
import numpy as np


__all__ = ("inertia_tensors", "reduced_inertia_tensors", "iterative_inertia_tensors_3D")
__author__ = "Duncan Campbell"


def _process_args(x, weights):
    """
    process arguments for inertia tensor functions
    """

    if len(np.shape(x)) == 2:
        x = x[np.newaxis, :, :]

    x = np.atleast_1d(x)

    n1, n2, ndim = np.shape(x)

    if weights is None:
        weights = np.ones((n1, n2))
    elif np.shape(weights) == (n2,):
        weights = weights[np.newaxis, :]

    if np.shape(weights) != (n1, n2, ndim):
        # copy the weights ndim times along a new axis
        # in order to make them the same shape as x
        weights = np.repeat(weights[:, :, np.newaxis], ndim, axis=2)

    return x, weights


def principal_axes_3D(I):
    """
    Return the principle axes and half-lengths of an ellipsoid defined by I

    Returns
    -------
    A, B, C : numpy.arrays
        arrays of the primary, intermediate, and minor axis lengths

    Av, Bv, Cv : numpy.arrays
        arrays of primary, intermediate, and minor eigenvectors
    """

    # note that eigh() returns the axes in ascending order
    evals, evecs = np.linalg.eigh(I)

    evecs = evecs[:, :, ::-1]

    Av = evecs[:, :, 0]
    Bv = evecs[:, :, 1]
    Cv = evecs[:, :, 2]

    evals = np.sqrt(evals[:, ::-1])

    A = evals[:, 0]
    B = evals[:, 1]
    C = evals[:, 2]

    return A, B, C, Av, Bv, Cv


def inertia_tensors(x, weights=None):
    r"""
    Calculate the inertia tensors for n1 sets, of n2 points, of dimension ndim.

    Parameters
    ----------
    x :  ndarray
        Numpy array of shape (n1, n2, ndim) storing n1 sets of n2 points
        of dimension ndim.  If an array of shape (n2, ndim) points is passed,
        n1 is assumed to be equal to 1.

    weights :  ndarray
        Numpy array of shape (n1, n2) storing n1 sets of n2 weights.
        Default sets weights argument to np.ones((n1,n2)).

    Returns
    -------
    I : numpy.ndarray
        an array of shape (n1, ndim, ndim) storing the n1 inertia tensors

    Examples
    --------
    """
    x, weights = _process_args(x, weights)
    n1, n2, ndim = np.shape(x)

    I = np.einsum("...ij,...ik->...jk", x, x * weights)
    m = np.sum(weights, axis=1)
    return I / (np.ones((n1, ndim, ndim)) * m[:, np.newaxis])


def reduced_inertia_tensors(x, weights=None):
    r"""
    Calculate reduced inertia tensors for n1 sets of n2 points of dimension ndim.

    Parameters
    ----------
    x :  ndarray
        Numpy array of shape (n1, n2, ndim) storing n1 sets of n2 points
        of dimension ndim.  If an array of shape (n2, ndim) points is passed,
        n1 is assumed to be equal to 1.

    weights :  ndarray
        Numpy array of shape (n1, n2) storing n1 sets of n2 weights.
        Default sets weights argument to np.ones((n1,n2)).

    Returns
    -------
    I : numpy.ndarray
        an array of shape (n1, ndim, ndim) storing the n1 inertia tensors

    Examples
    --------
    """

    x, weights = _process_args(x, weights)
    n1, n2, ndim = np.shape(x)

    r_squared = np.sum(x**2, -1)

    # ignore points at r=0
    mask = r_squared == 0.0
    weights[mask] = 0.0
    r_squared[mask] = 1.0

    I = np.einsum("...ij,...ik->...jk", x / (r_squared[:, :, np.newaxis]), x * weights)
    m = np.sum(weights, axis=1)
    return I / (np.ones((n1, ndim, ndim)) * m[:, np.newaxis])
