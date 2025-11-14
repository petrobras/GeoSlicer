## Polynomial Shading Correction

### Introduction

Tomography images frequently present variations in intensity values that are not characteristic of the sample, but rather of the
equipment that collected them. These variations are called artifacts, and there are several types of them. The *Polynomial Shading
Correction* module corrects the artifact known as beam hardening, among others. It is also known as background correction.

| ![Figura 1](../../assets/images/PolynomialShadingCorrection1.png) |
|:------------------------------------------------------------------------------------------------------------------------:|
| Figure 1: Left: beam hardening artifact present. Right: image corrected after applying shading correction. |

### Method

The entire procedure described below is performed slice by slice, in the axial plane of the sample.

For each slice, based on the parameter "Number of fitting points", a random sample of intensity values is taken at points belonging to the shading mask. These points are used to fit a second-degree polynomial function in two variables, which defines the background of the image:

$$ f(x,y) = a (x-b)^2+c(y-d)^2+e(x-b)+f(y-d)+g(x-b)(y-d) + h $$

The fitted function is then used to perform the correction on the slice, following the equation:

$$ s'(x,y) = \frac{s(x,y)}{f(x,y)}M $$
Where, $s'(x,y)$ is the corrected slice, $s(x,y)$ is the original slice, and $M$ is the average of all data in the shading mask (constant value).