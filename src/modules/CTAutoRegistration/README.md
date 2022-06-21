## CT Auto Registration

_GeoSlicer_ module to automatically register 3D CT images, as described in the steps bellow:

1. Select the _Fixed volume_, and the _Moving volume_. Transformations will be applied to the moving volume to match the fixed volume, and the result will be saved in a new transformed volume, preserving the fixed and moving volumes.

2. Set the _Sample radius_, the radius of the sample in millimeters. This radius will be used to create a mask to identify the relevant data to be registered.
   
3. Set the _Sampling fraction_, the fraction of voxels of the fixed volume that will be used for registration. The number has to be larger than zero and less or equal to one. Higher values increase the computation time but may give more accurate results.

4. Set the _Minimum step length_, a value greater or equal to 10<sup>-8</sup>. Each step in the optimization takes steps at least this big. When none are possible, registration is complete. Smaller values allows the optimizer to make smaller adjustments, but the registration time may increase.

5. Set the _Number of iterations_. It determines the maximum number of iterations to try before stopping the optimization. When using a lower value (500-1000) then the registration is forced to terminate earlier but there is a higher risk of stopping before an optimal solution is reached.

6. Set a downsampling factor. This parameter directly affects the algorithm efficiency. High values (~1) might demand a high execution time to finish the registration. Intermediate values, such as 0.3, have been shown as the optimum value to obtain a good result without an extensive computational cost. 

7. Selected at least one of the _Registration phases_. Each registration phase will be used to initialize the next phase.

8. Click the _Register_ button and wait for completion. The registered volume (transformed) can be accessed from the _Data_ tab, under the same directory as the moving volume. The transform node and the label map masks created are also available to the user for inspection, but can be deleted.