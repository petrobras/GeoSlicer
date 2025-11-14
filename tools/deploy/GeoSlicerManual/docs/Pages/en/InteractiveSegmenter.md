## Interactive Segmenter

The **Interactive Segmenter** module provides a supervised segmentation tool for 3D images with a real-time preview. It allows users to annotate a small portion of an image and see the segmentation result update instantly in a parallel view, facilitating rapid and intuitive model training.

### Usage

The workflow is designed to be interactive, providing immediate feedback on the user's annotations.

#### Step 1: Select Input Image

1.  In the **Input** section, select the volume you want to segment using the **Input Image** selector.
2.  If the image is very large (e.g., larger than 700³ voxels), it is recommended to crop the image first for better performance. You can crop the image using the Crop module. The segmentation can be applied to the full, uncropped image later.

#### Step 2: Start Annotation

1.  Click the **Start Annotation** button.
2.  The screen layout will change to a side-by-side view. The left view is for annotation, and the right view will display the real-time segmentation preview.
3.  The module will start calculating a feature cache in the background. A progress bar will indicate the status. The annotation tools will be enabled once this process is complete.

| ![Layout](/assets/images/InteractiveSegmenter.png) |
|:---:|
| Figure 1: Side-by-side layout for annotation (left) and preview (right). |

#### Step 3: Annotate the Image

1.  Use the simplified **Segment Editor** tools in the **Annotation** section to create segments and draw annotations on the image in the **left view**. The primary tools available are `Paint`, `Draw`, and `Erase`.
2.  As you annotate, a Random Forest model is trained in the background. The segmentation result will be updated in real-time in the **right view**.
3.  Create at least two segments and provide examples for each to get a meaningful result.

!!! note "Tip"
    Annotate various characteristics of the image for a better result. Include boundaries between the expected segments and other potentially ambiguous regions. Iterate by correcting any misclassified regions you see in the preview.

#### Step 4: Adjust Feature Set (Optional)

1.  In the **Annotation** section, you can select a **Feature Set** from the dropdown menu. These presets control the set of image features used for training the classifier, affecting the smoothness and detail of the segmentation result.
2.  The available presets are:
    *   **Sharp**: Prioritizes fine details.
    *   **Balanced**: A good starting point for most images.
    *   **Smooth**: Creates a smoother result, ignoring small variations.
    *   **Extra Smooth**: Even smoother results.
    *   **Complete**: Uses all available features.
3.  Changing the preset will trigger a retraining of the model, and the preview will update accordingly.

#### Step 5: Apply to Full Image

1.  Once you are satisfied with the preview, go to the **Output** section.
2.  (Optional) If you want to apply the segmentation to a different image (e.g., the original, uncropped volume), select it in the **Inference Image** selector. If no image is selected, the original input image will be used.
3.  Click the **Apply to Full Image** button. The trained model will be applied to the entire selected volume.
4.  A progress bar will show the status of the full segmentation. When complete, the side-by-side layout will be closed, and a new segmentation node will be added to the scene.

To stop the interactive session at any time, click the **Cancel** button. Your annotations will be saved in a segmentation node, and you can resume the session later by starting the module again with the same input image.

### Method

The Interactive Segmenter uses a **Random Forest** classifier, a machine learning algorithm that builds multiple decision trees to make a robust prediction for each voxel. The classifier is trained on a set of image features calculated from the input volume.

#### Features

The following features are calculated from the input image to train the model. The user can choose which features to use through the **Feature Set** presets.

*   **Raw Image**: The original voxel intensity.
*   **Gaussian Filter**: A smoothed version of the image. The module calculates this with four different `sigma` values (1, 2, 4, and 8), creating features that capture information at different scales.
*   **Window Variance**: The local variance of voxel intensities within a 3D window. This is useful for texture discrimination. The module calculates this with three different window sizes (5x5x5, 9x9x9, and 13x13x13).

#### Feature Presets

The presets combine these features to achieve different results:

*   **Sharp**: Raw Image, Gaussian (sigma=1, 2), Window Variance (5x5x5).
*   **Balanced**: Raw Image, Gaussian (sigma=1, 2, 4), Window Variance (5x5x5, 9x9x9).
*   **Smooth**: Gaussian (sigma=1, 2, 4, 8), Window Variance (5x5x5, 9x9x9).
*   **Extra Smooth**: Gaussian (sigma=2, 4, 8), Window Variance (5x5x5, 9x9x9).
*   **Complete**: All calculated features.

### Related Modules

For more advanced segmentation tasks, consider the [AI Segmenter](/Volumes/Segmentation/Segmentation.md#ai-segmenter) module. It also uses a Random Forest classifier but offers more feature options and different training methods, though it does not provide a real-time preview.
