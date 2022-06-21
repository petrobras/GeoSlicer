"""
Directional Variogram 3D
"""
import numpy as np
from scipy.spatial.distance import pdist
from skgstat import Variogram, DirectionalVariogram, MetricSpace


class GeneralizedVariogram(DirectionalVariogram):
    """GeneralizedVariogram Class

    Calculates a variogram of the separating distances in the given
    3D coordinates and relates them to one of the semi-variance measures of the
    given dependent values.

    The direcitonal version of a Variogram will only form paris of points
    that share a specified spatial relationship.

    """

    def __init__(
        self,
        coordinates=None,
        values=None,
        estimator="matheron",
        model="spherical",
        dist_func="euclidean",
        bin_func="even",
        normalize=False,
        fit_method="trf",
        fit_sigma=None,
        directional_model="cone",
        azimuth=0,
        dip=0,
        tolerance=360,
        bandwidth="q33",
        use_nugget=False,
        maxlag=None,
        n_lags=10,
        verbose=False,
        **kwargs
    ):

        # Before we do anything else, make kwargs available
        self._kwargs = self._validate_kwargs(**kwargs)

        # OBS: Call __init__ of baseclass?
        # No, because the sequence at which the arguments get initialized
        # does matter. There is way too much transitive dependence, thus
        # it was easiest to copy the init over.

        self._direction_mask_cache = None

        if not isinstance(coordinates, MetricSpace):
            coordinates = np.asarray(coordinates)
            coordinates = MetricSpace(coordinates.copy(), dist_func)
        else:
            assert (
                self.dist_func == coordinates.dist_metric
            ), "Distance metric of variogram differs from distance metric of coordinates"
            assert coordinates.max_dist is None

        # Set coordinates
        self._X = coordinates

        # pairwise difference
        self._diff = None

        # set verbosity
        self.verbose = verbose

        # set values
        self._values = None
        # calc_diff = False here, because it will be calculated by fit() later
        self.set_values(values=values, calc_diff=False)

        # distance matrix
        self._dist = None

        # set distance calculation function
        self._dist_func_name = None
        self.set_dist_function(func=dist_func)

        # Angles and euclidean distances used for direction mask calculation
        self._dips = None
        self._azimuths = None
        self._euclidean_dist = None

        # lags and max lag
        self.n_lags = n_lags
        self._maxlag = None
        self.maxlag = maxlag

        # estimator can be function or a string
        self._estimator = None
        self.set_estimator(estimator_name=estimator)

        # model can be function or a string
        self._model = None
        self.set_model(model_name=model)

        # direction (azimuth and dip)
        self._azimuth = None
        self.azimuth = azimuth
        self._dip = None
        self.dip = dip

        # direction tolerance
        self._tolerance = None
        self.tolerance = tolerance

        # tolerance bandwidth
        self._bandwidth = None
        self.bandwidth = bandwidth

        # set the directional model
        self._directional_model = None
        self.set_directional_model(model_name=directional_model)

        # the binning settings
        self._bin_func = None
        self._groups = None
        self._bins = None
        self.set_bin_func(bin_func=bin_func)

        # specify if the lag should be given absolute or relative to the maxlag
        self._normalized = normalize

        # set the fitting method and sigma array
        self.fit_method = fit_method
        self._fit_sigma = None
        self.fit_sigma = fit_sigma

        # set if nugget effect shall be used
        self.use_nugget = use_nugget

        # set attributes to be filled during calculation
        self.cov = None
        self.cof = None

        # settings, not reachable by init (not yet)
        self._cache_experimental = False

        # do the preprocessing and fitting upon initialization
        # Note that fit() calls preprocessing
        self.fit(force=True)

        # finally check if any of the uncertainty propagation kwargs are set
        self._experimental_conf_interval = None
        self._model_conf_interval = None
        if "obs_sigma" in self._kwargs:
            self._propagate_obs_sigma()

    def _calc_direction_mask_data(self, force=False):
        """
        Calculate directional mask data. WARNING: logic differs from original
        scikit-geostat version, as azimuth is measured from y axis (not x).
        For this, the angles between the vector between the two points, and north
        (y axis) (azimuth), as well as the angle between the xy plane to the
        negative z axis (dip) are calculated.
        The result is stored in self._azimuths and self._dips and contain informations
        for each point pair vector in radians.

        Parameters
        ----------
        force : bool
            If True, a new calculation of all angles is forced, even if they
            are already in the cache.

        Notes
        -----
        The masked data is in radias, while azimuth is given in degrees.
        For the Vector between a point pair A,B :math:`\overrightarrow{AB}=u` and the
        x-axis, represented by vector :math:`\overrightarrow{e} = [1,0]`, the angle
        :math:`\Theta` is calculated like:

        .. math::
            cos(\Theta) = \frac{u \circ e}{|e| \cdot |[1,0]|}
        """
        # check if already calculated
        if self._azimuths is not None and self._dips is not None and not force:
            return

        if self.coordinates.ndim == 1:
            _x = np.vstack(zip(self.coordinates, np.zeros(len(self.coordinates))))
        if self.coordinates.ndim == 2:
            if self.coordinates.shape[1] < 3:
                missing_columns = 3 - self.coordinates.shape[1]
                zeros = np.zeros((self.coordinates.shape[0], missing_columns))
                _x = np.c_[self.coordinates, zeros]
            else:
                _x = self.coordinates
        else:
            raise NotImplementedError("N-dimensional coordinates cannot be handled")

        self._euclidean_dist = pdist(_x, "euclidean")  # always euclidean
        coord_diffs = np.empty((self._euclidean_dist.shape[0], 3), self._euclidean_dist.dtype)
        for i in range(3):
            coord_diffs[:, i] = pdist(_x[:, i, None], np.subtract)

        # OBS.: unusual axis order because azimuth is measured from y axis
        # self._azimuths = np.pi + np.arctan2(coord_diffs[:, 0], coord_diffs[:, 1]) # # azimuths in [0, 2*pi]
        self._azimuths = np.arctan2(coord_diffs[:, 0], coord_diffs[:, 1])  # azimuths in [-pi, pi]
        self._dips = np.arcsin(-coord_diffs[:, 2] / self._euclidean_dist)  # dips in [-pi/2, pi/2]

    @property
    def azimuth(self):
        """Direction azimuth

        Main direction for the selection of points in the formation of point
        pairs. y axis is defined to be 0° and then the azimuth is set clockwise
        up to 360°.

        Parameters
        ----------
        angle : float
            New azimuth angle in **degree**.

        Raises
        ------
        ValueError : in case angle < -180° or angle > 180

        """
        return self._azimuth

    @azimuth.setter
    def azimuth(self, angle):
        if angle < -180 or angle > 180:
            raise ValueError("The azimuth is an angle in degree and has to " "meet -180 <= angle <= 180")
        else:
            self._azimuth = angle

        # reset groups and mask cache on azimuth change
        self._direction_mask_cache = None
        self._groups = None

    @property
    def dip(self):
        """Direction dip

        Main direction for the selection of points in the formation of point
        pairs. x-y plane is defined to be 0° and then the dip is counted downwards
        to negative z up to 90°, valuing -90° at positive z axis.

        Parameters
        ----------
        angle : float
            New azimuth angle in **degree**.

        Raises
        ------
        ValueError : in case angle < -90° or angle > 90°

        """
        return self._dip

    @dip.setter
    def dip(self, angle):
        if angle < -90 or angle > 90:
            raise ValueError("The dip is an angle in degree and has to " "meet -90 <= angle <= 90")
        else:
            self._dip = angle

        # reset groups and mask cache on dip change
        self._direction_mask_cache = None
        self._groups = None

    def set_directional_model(self, model_name):
        # handle predefined models
        if isinstance(model_name, str):
            if model_name.lower() == "cone":
                self._directional_model = self._cone
            else:
                raise ValueError("%s is not a valid model." % model_name)

        # handle callable
        elif callable(model_name):
            self._directional_model = model_name
        else:
            raise ValueError(
                "The directional model has to be identified by a "
                "model name, or it has to be the search area "
                "itself"
            )

        # reset the groups as the directional model changed
        self._groups = None

    def _direction_mask(self, force=False):
        """Directional Mask

        Array aligned to self.distance masking all point pairs which shall be
        ignored for binning and grouping. The one dimensional array contains
        all row-wise point pair combinations from the upper or lower triangle
        of the distance matrix in case either of both is directional.

        Returns
        -------
        mask : numpy.array
            Array aligned to self.distance giving for each point pair
            combination a boolean value whether the point are directional or
            not.

        """
        if force or self._direction_mask_cache is None:
            self._direction_mask_cache = self._directional_model(self._azimuths, self._dips, self._euclidean_dist)
        return self._direction_mask_cache

    def _cone(self, azimuths, dips, dists):
        azimuth = np.radians(self.azimuth)
        dip = np.radians(self.dip)
        tolerance = np.radians(self.tolerance)
        angle_diffs = np.arccos(np.cos(dips) * np.cos(dip) * np.cos(azimuths - azimuth) + np.sin(dips) * np.sin(dip))
        # a vector and its opposite lie in the same direction: accept both of them
        accepted = (angle_diffs <= tolerance / 2) | (np.pi - angle_diffs <= tolerance / 2)
        return accepted

    @property
    def maxlag(self):
        """
        Maximum lag distance to be considered in this Variogram instance.
        You can limit the distance at which point pairs are calcualted.
        There are two possible ways how to do that, in absoulte lag units,
        which is a float. Secondly, a string can be set: ``'mean'`` and
        ``'median'`` for the mean or median value of the distance matrix.

        Notes
        -----
        This setting is largely flexible, but all options except the
        absolute limit in lag units need the full distance matrix to be
        calculated. Hence, it does **not** speed up the calculation
        of large distance matrices, just the estimation of the variogram.
        Thus, if you pre-calcualte the distance matrix using
        :class:`MetricSpace <skgstat.MetricSpace>`, only absoulte
        limits can be used.

        """
        return self._maxlag

    @maxlag.setter
    def maxlag(self, value):
        # reset fitting
        self.cof, self.cov = None, None

        # remove bins, groups, and bin count
        self._bins = None
        self._groups = None
        self._bin_count = None

        # set new maxlag
        if value is None:
            self._maxlag = None
        elif isinstance(value, str):
            if value == "median":
                self._maxlag = np.median(self.distance)
            elif value == "mean":
                self._maxlag = np.mean(self.distance)
        else:
            self._maxlag = value
