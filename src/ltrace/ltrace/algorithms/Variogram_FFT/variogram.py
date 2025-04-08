import numpy as np
from scipy.optimize import curve_fit
from skgstat import models


class VariogramFFT:
    def __init__(self, data, spacing):
        self.data = data
        self.spacing = spacing

        self.range = None
        self.sill = None
        self.nugget = None

    def calculate_feature(self):
        return self._calculate_feature(self.data, self.spacing)

    @staticmethod
    def _calculate_feature(data, spacing):
        cov_fun, axes = VariogramFFT.compute_autocovariance_function(data, spacing)

        corr_fun = cov_fun / cov_fun.max()

        corr_fun = np.asarray(corr_fun)

        correlation_threshold = 0.5
        positions_HighCorrelations = np.nonzero(corr_fun > correlation_threshold)
        positions_HighCorrelations = np.asarray(positions_HighCorrelations)

        covariance_matrix = np.cov(positions_HighCorrelations)
        feature_CorrLenght = np.sqrt(np.diag(covariance_matrix)).mean()

        return feature_CorrLenght

    def calculate(self, use_nugget=True):
        y_axes, x_axes = VariogramFFT.compute_axes_variogram_FFT(self.data, self.spacing)
        number_of_dimensions = len(self.data.shape)
        self.range = [0] * number_of_dimensions
        self.sill = [0] * number_of_dimensions
        self.nugget = [0] * number_of_dimensions
        fit = [None] * number_of_dimensions
        for dim in np.arange(number_of_dimensions):
            try:
                x_values = x_axes[dim]
                y_values = y_axes[dim]
                y_max = np.nanmax(y_values)
                x_max = np.nanmax(x_values)
                if use_nugget:
                    bounds = (0, [x_max, y_max, y_max])
                else:
                    bounds = (0, [x_max, y_max])
                p0 = bounds[1]
                cof, cov = curve_fit(models.spherical, x_values, y_values, method="trf", p0=p0, bounds=bounds)
                self.range[dim] = cof[0]
                self.sill[dim] = cof[1]
                if use_nugget:
                    self.nugget[dim] = cof[2]

                fit[dim] = models.spherical(x_values, self.range[dim], self.sill[dim], self.nugget[dim])
            except Exception:
                import traceback

                traceback.print_exc()
                fit[dim] = None

        return x_axes, y_axes, fit

    def get_sill(self, axis_index):
        return self.sill[axis_index]

    def get_range(self, axis_index):
        return self.range[axis_index]

    def get_nugget(self, axis_index):
        return self.nugget[axis_index]

    @staticmethod
    def compute_autocovariance_function(data, spacing):
        """
        AUTO-COVARIANCE FUNCTION
        Computes the auto-covariance function in the FFT domain of a given data in a array up to three dimensions

        Parameters
        ----------
        data : array_like
            Data where the auto-covariance will be computed
        spacing : float or nparray or list
            spacing/pixel size related to the data. If it is the same for all dimensions, use a single float.
            If it is different, use a list/array of N spacing, N being the dimension of the data

        Returns
        -------
        cov_fun: array_like
            Covariance function with same size of the input data
        axes :  list of array_like
            Axis/coordinates of cov_fun
        """

        data_FFT = np.fft.fftn(data - data.mean())
        cov_fun = np.fft.ifftn(data_FFT * np.conjugate(data_FFT))
        cov_fun = np.real(cov_fun) / data.size
        cov_fun = np.fft.fftshift(cov_fun)

        if isinstance(spacing, float):
            spacing = spacing * np.ones((3,))

        axes = []
        for dim in np.arange(len(data.shape)):
            axis_array = np.fft.ifftshift(np.fft.fftfreq(data.shape[dim], 1 / (spacing[dim] * data.shape[dim])))
            axes.append(axis_array)

        return cov_fun, axes

    @staticmethod
    def compute_NDvariogram_FFT(data, spacing):
        """
            VARIOGRAM COMPUTED IN FFT DOMAIN
            Computes the variogram based on the auto-covariance function in the FFT domain of a given data in a array up to three dimensions

            Parameters
            ----------
            data : array_like
                Data where the variogram  will be computed
        spacing : float or nparray or list
                spacing/pixel size related to the data. If it is the same for all dimensions, use a single float.
                If it is different, use a list/array of N spacing, N being the dimension of the data

            Returns
            -------
            variogram: array_like
                Variogram  with same size of the input data
            axes : list of array_like
                Axis/coordinates of variogram
        """

        cov_fun, axes = VariogramFFT.compute_autocovariance_function(data, spacing)
        variogram = data.var() - cov_fun

        return variogram, axes

    @staticmethod
    def compute_axes_variogram_FFT(data, spacing):
        """
        VARIOGRAM ALONG AXES COMPUTED IN FFT DOMAIN
        Computes the variogram along the orthogonal axes (Z ,Y, Z). It is based on the auto-covariance
        function in the FFT domain of a given data in a array up to three dimensions

        Parameters
        ----------
        data : array_like
            Data where the variogram  will be computed
        spacing : float or nparray or list
            spacing/pixel size related to the data. If it is the same for all dimensions, use a single float.
            If it is different, use a list/array of N spacing, N being the dimension of the data

        Returns
        -------
        variogram: array_like
            Variogram
        axes :  list of array_like
            Axis/coordinates of variogram with same size
        """
        for i, dim in enumerate(data.shape):
            if (dim % 2) == 0:
                data = np.delete(data, dim - 1, i)

        variogram, axes_ = VariogramFFT.compute_NDvariogram_FFT(data, spacing)

        # In theory, at least in matlab, the minimum/maximum of the variogram/covariagram should be at the position [0,0,0], then the commented lines would have worked.
        # However, here, the minimum/maximum are not located in [0,0,0], but in [-1,-1,-1]. It might be something different in numpy.fft/fftshift or, in some other function we are shifting an array causing this issue.
        # In this commit, I implemented a pragmatical solution, I find the position of the min and use it to extract the variogram_axes.

        # variogram = np.fft.fftshift(variogram)

        conditon = variogram == variogram.min()
        variogram_min_position = np.where(conditon)

        variogram_axes = []
        axes = []
        base_index = []

        for dim in range(variogram.ndim):
            base_index.append(int(np.rint(variogram_min_position[dim])))

        for dim in range(variogram.ndim):
            # index = [0] * variogram.ndim
            # index[dim] = slice(0, int(np.rint(variogram.shape[dim] / 2)))
            index = base_index.copy()
            index[dim] = slice(int(np.rint(variogram_min_position[dim])), -1)
            variogram_axes.append(variogram[tuple(index)])
            axes_fftshift = np.fft.fftshift(axes_[dim])
            # axes.append(axes_fftshift[0 : int(np.rint(variogram.shape[dim] / 2))])
            axes.append(axes_fftshift[0 : int(variogram.shape[dim] / 2)])

        return variogram_axes, axes
