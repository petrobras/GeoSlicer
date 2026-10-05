"""Which feature kernels a session uses, and what to call them in the UI."""

import numpy as np
from dataclasses import dataclass
from scipy.ndimage import gaussian_filter

import ltrace.algorithms.feature_extraction as fe
from ltrace.interactive.ipc import FEATURE_NAMES, FeatureIndex


# Base (1x) kernel sizes, tuned for typical microCT. The session feature scale
# multiplier (1/2/4) scales these for coarser-textured images.
BASE_GAUSSIAN_SIGMAS = {
    FeatureIndex.GAUSSIAN_A: 1,
    FeatureIndex.GAUSSIAN_B: 2,
    FeatureIndex.GAUSSIAN_C: 4,
    FeatureIndex.GAUSSIAN_D: 8,
}

BASE_WINVAR_SIZES = {
    FeatureIndex.WINVAR_A: 5,
    FeatureIndex.WINVAR_B: 9,
    FeatureIndex.WINVAR_C: 13,
}


def _odd(value):
    """Nearest odd integer >= 3 (window-variance boxes must be odd-sized)."""
    n = max(3, int(round(value)))
    return n if n % 2 else n + 1


@dataclass
class FeatureScale:
    """The kernel layout for one session, derived once from the scale multiplier and
    passed to every feature function, so no two of them can disagree on a kernel size."""

    multiplier: int
    gaussian_sigmas: dict  # FeatureIndex -> sigma
    winvar_sizes: dict  # FeatureIndex -> odd window size
    gaussian_pyramid_level: dict  # large gaussian FeatureIndex -> pyramid level it is approximated on
    pyramid_levels: int  # mean-pyramid depth; raised for large scales
    definitions: dict  # FeatureIndex -> calc_func(array) for the 3D/inference precompute

    @classmethod
    def from_multiplier(cls, multiplier):
        gaussian_sigmas = {f: s * multiplier for f, s in BASE_GAUSSIAN_SIGMAS.items()}
        winvar_sizes = {f: _odd(w * multiplier) for f, w in BASE_WINVAR_SIZES.items()}

        # Each large gaussian goes on the pyramid level whose 2x2-mean decimation leaves
        # only a small residual blur; the smallest stays on the exact sampled path.
        smallest_gaussian = min(gaussian_sigmas, key=gaussian_sigmas.get)
        gaussian_pyramid_level = {
            f: max(1, int(np.floor(np.log2(s)))) for f, s in gaussian_sigmas.items() if f != smallest_gaussian
        }
        pyramid_levels = max([3, *gaussian_pyramid_level.values()])

        definitions = {
            FeatureIndex.SOURCE: lambda arr: arr,
            **{f: (lambda arr, s=s: gaussian_filter(arr, sigma=s)) for f, s in gaussian_sigmas.items()},
            **{f: (lambda arr, w=w: fe.win_var_3d(arr, w)) for f, w in winvar_sizes.items()},
        }
        return cls(multiplier, gaussian_sigmas, winvar_sizes, gaussian_pyramid_level, pyramid_levels, definitions)

    def halo(self, feature_enum):
        """Voxels a slab must overlap its neighbors by for this filter to see the same
        neighborhood it would over the whole volume."""
        if feature_enum in self.gaussian_sigmas:
            return int(4 * self.gaussian_sigmas[feature_enum] + 0.5)  # scipy's truncate=4
        if feature_enum in self.winvar_sizes:
            return self.winvar_sizes[feature_enum] // 2
        return 0

    def margin(self, feature_indices):
        """Sample pixels of context covering the support of every selected filter."""
        margin = 1
        for index in feature_indices:
            feature = FeatureIndex(index)
            if feature in self.gaussian_sigmas:
                # cv2.GaussianBlur derives its kernel radius as 4*sigma for float inputs
                margin = max(margin, 4 * self.gaussian_sigmas[feature] + 1)
            elif feature in self.winvar_sizes:
                margin = max(margin, self.winvar_sizes[feature] // 2 + 1)
        return margin


def feature_display_name(feature, scale=1):
    """Human-readable feature name with kernel sizes scaled by `scale`, for the UI."""
    if feature in BASE_GAUSSIAN_SIGMAS:
        return f"Gaussian Filter (sigma={BASE_GAUSSIAN_SIGMAS[feature] * scale})"
    if feature in BASE_WINVAR_SIZES:
        return f"Window Variance (size {_odd(BASE_WINVAR_SIZES[feature] * scale)})"
    return FEATURE_NAMES[feature]


def feature_base_names(feature_indices, scale):
    """One display name per selected feature, in sorted order, for the debug report."""
    return [feature_display_name(FeatureIndex(index), scale.multiplier) for index in sorted(feature_indices)]
