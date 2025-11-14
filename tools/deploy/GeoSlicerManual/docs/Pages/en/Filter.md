## Gradient Anisotropic Diffusion

In many applications, it is assumed that transitions from a light to a dark region (characterized by a high gradient) are of interest. While other filters, such as median and Gaussian, often blur boundaries, making pore delimitation more confusing, anisotropic diffusion filters tend to avoid this type of confusion. The conductance term is a function of the image gradient magnitude at each point, reducing the diffusion strength at edges.

|                                         ![Figura 1](../../assets/images/GradientAnisotropicDiffusion2.png)                                         |
|:------------------------------------------------------------------------------------------------------------------------:|
| Left: Original volume, uncorrected. Right: After correction with anisotropic gradient diffusion filter. |

The numerical implementation of this equation available in _GeoSlicer_ is similar to that described in the Perona-Malik paper, but uses a more robust technique for gradient magnitude estimation and is generalized to N-dimensions.

The module parameters for calculating anisotropic gradient diffusion are:

- **Conductance** (_Conductance_): Controls the sensitivity of the conductance term. As a general rule, the lower the value, the more strongly the filter will preserve edges. A high value will cause diffusion (smoothing) of the edges. Note that the number of iterations controls how much smoothing will occur within regions delimited by edges.

- **Iterations** (_Iterations_): More iterations lead to greater smoothing. Each iteration takes the same amount of time. If one iteration takes 10 seconds, 10 iterations take 100 seconds.

- **Time step** (_Time step_): The time step depends on the image dimensionality. For three-dimensional images, the default value of 0.0625 provides a stable solution. In practice, altering this parameter causes few changes to the image.

---

## Curvature Anisotropic Diffusion

Performs anisotropic diffusion on an image using a _Modified Curvature Diffusion Equation_ (MCDE).

MCDE does not exhibit the edge enhancement properties of classic anisotropic diffusion, which under certain conditions can undergo "negative" diffusion, increasing edge contrast. Curvature anisotropic diffusion always undergoes positive diffusion, with the conductance term only varying the strength of this diffusion.

Qualitatively, MCDE compares well with other non-linear diffusion techniques. It is less sensitive to contrast than classic Perona-Malik type diffusion and preserves finer, more detailed structures in images. There is a potential speed disadvantage when using this function instead of the *Gradient Anisotropic Diffusion*. Each iteration of the solution takes approximately twice as long. Fewer iterations, however, may be necessary to achieve an acceptable solution.

The parameters required for the curvature anisotropic diffusion calculation are the same as those for the anisotropic gradient method.

---

## Gaussian Blur Image Filter

Applies a Gaussian blur filter to the volume; the only parameter is _Sigma_, representing the width of the Gaussian in mm units.

---

## Median Image Filter

Applies a median filter to the volume; the _Neighborhood size_ parameter defines the neighborhood size in voxels in each of the directions.

---

## Euclidean Distance Transform

Calculates the Euclidean distance transform of a binary image. The output image contains, for each voxel, the distance to the nearest non-zero voxel in the input image.

### Usage
1. Select the input binary image. Scalar images also work, but only non-zero voxels are considered as foreground.
2. If the input has more than one label, select the desired label value to be considered as foreground. It is possible to select multiple segments.
3. If the input is a scalar or just have one label, the selection of label value is hidden.
3. Choose a prefix for the output image name.

---

## Simple Filters

This module, loaded from the original 3D Slicer, presents a diverse set of filters for calculating binary and grayscale morphology, noise removal, thresholding, image intensity manipulation, region growing, Fourier transform, etc. For a more detailed explanation of each of the options available in this module, consult the [specific](https://slicer.readthedocs.io/en/latest/user_guide/modules/simplefilters.html) documentation.

---

## Polynomial Shading Correction

Tomography images often exhibit variations in intensity values that are not characteristic of the sample, but rather of the equipment that collected them. These variations are called artifacts, and there are several types of them. The *Polynomial Shading Correction* module corrects the artifact known as _beam hardening_, among others. It is also known as _background_ correction.

|                                         ![Figura 1](../../assets/images/PolynomialShadingCorrection1.png)                                         |
|:------------------------------------------------------------------------------------------------------------------------:|
| Left: _Beam hardening_ artifact present. Right: Corrected image after applying _shading correction_. |

The entire procedure described below is performed slice by slice, in the axial (z-axis) plane of the sample.

For each slice, based on the "Number of fitting points" parameter, a random sample is taken from intensity values at points belonging to the shading mask. These points are used to fit a second-degree polynomial function in two variables, which defines the image background:

$$ f(x,y) = a (x-b)^2+c(y-d)^2+e(x-b)+f(y-d)+g(x-b)(y-d) + h $$

The fitted function is then used to perform the correction on the slice, following the equation:

$$ s'(x,y) = \frac{s(x,y)}{f(x,y)}M $$
Where, $s'(x,y)$ is the corrected slice, $s(x,y)$ is the original, and $M$ is the average of all data in the shading mask (constant value).

The _Shading Correction_ module workflow is divided into three steps: initialization, sampling mask definition, and processing.

#### Initialization

1.  **Input image:** Select the input image you want to correct.
2.  **Keep intermediate image:** Check this option if you wish to keep the pre-normalized image generated during the initialization step. This intermediate image facilitates the thresholding step.
3.  Click the **Initialize** button. This will pre-normalize the input image and prepare the segment editor for creating the sampling mask.

#### Threshold

1.  After initialization, a segment editor interface with the **Threshold** effect will be displayed to create a mask that covers the image areas affected by shading. This mask will be used to sample points for polynomial fitting.
2.  After adjusting the threshold, click **Apply** in the Threshold effect panel.

!!!tip
	Consider the mineral in which the _beam hardening_ effect is most clearly appearing. For example: If this is the case for calcite, simply click + drag with the mouse near a region with this mineral; a yellow circle should appear, and you should see the segmentation coloring near the region, depending on the circle's radius.

!!!tip
	For a finer and more sensitive segmentation adjustment, hover your mouse over one of the selection boxes with the maximum/minimum values and use the mouse wheel to increase or decrease the upper/lower limit.
	
	![fine_tunning](../../assets/images/ShadingFineTunning.png)

#### Parameter Selection

1.  **Slice group size:** Define the number of slices that will share the same fitted polynomial function.
2.  **Number of fitting points:** Define the number of points to be sampled from the mask for function fitting.
3.  **Output image name:** Enter a name for the corrected output image.

#### Apply

1.  **Apply:** Click to start the correction process on the input image.
2.  **Apply to full volume:** If your input image is a virtual image (_lazy node_), this button will be visible. Clicking it will open the **Polynomial Shading Correction Big Image** module, which is optimized for processing large images. The parameters defined in this module will be automatically transferred to the big image module.