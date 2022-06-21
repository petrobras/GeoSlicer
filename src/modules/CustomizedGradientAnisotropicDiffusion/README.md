## Gradient Anisotropic Diffusion

_GeoSlicer_ module to apply gradient anisotropic diffusion filtering on images, as described in the steps bellow:

1. Select the _Input volume_ to be filtered.

2. Set the _Conductance_ parameter. Conductance controls the sensitivity of the conductance term. As a general rule, the lower the value, the more strongly the filter preserves edges. A high value will cause diffusion (smoothing) across edges. Note that the number of iterations controls how much smoothing is done within regions bounded by edges.
   
3. Set the _Iterations_ parameter. The more iterations, the more smoothing. Each iteration takes the same amount of time. If it takes 10 seconds for one iteration, then it will take 100 seconds for 10 iterations. Note that the conductance controls how much each iteration smooths across edges.

4. Set the _Time step_ parameter. The time step depends on the dimensionality of the image. In Slicer the images are 3D and the default (.0625) time step will provide a stable solution.

5. Set the _Output volume name_.

6. Click the _Apply_ button and wait for completion. The filtered output volume will be located in the same directory as the _Input volume_.