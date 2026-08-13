# Crop

The **Crop** module allows for efficient cropping of one or multiple volumes simultaneously using a customizable Region of Interest (ROI). It supports Scalar, Vector, and LabelMap volumes, ensuring that all related data can be processed with a consistent spatial boundary.

## How to use

1.  **Input Section**:
    *   Select an image from the **Image** dropdown and click **Add**.
    *   You can add multiple images to the list; they will all be cropped using the same ROI configuration.
    *   Use the radio buttons in the **Visible** column to choose which volume to use as a reference in the slice views.
2.  **Adjusting the Crop Region**:
    *   **Interactive**: A temporary ROI is automatically created. You can drag its edges, faces, or corners directly in the slice views.
    *   **Manual Entry**: Set precise **Center** and **Dimensions** using IJK coordinates in the Parameters section.
    *   **History**: Click the **...** buttons next to Center or Dimensions to select from the last 10 configurations used.
    *   **Copy from ROI**: Use the **Copy from** dropdown to duplicate the boundaries of an existing ROI in the scene.
3.  **Options**:
    *   **Copy attributes and references**: If checked, the cropped volumes will inherit metadata, attributes, and references (such as spatial orientation and custom metadata) from the original volumes.
    *   **Keep ROI after crop**: By default, the temporary ROI is removed after cropping. Check this to keep it as a permanent node in your scene.
4.  **Execution**:
    *   Click **Crop All** to process all volumes in the list.
    *   Click **Cancel** to clear the list and hide the temporary ROI.

## Tips

*   **Symmetric Resize**: Hold the **Alt** key while dragging ROI anchors to resize symmetrically around the current center.
*   **Visual Feedback**: The module automatically fits the slice viewers to the selected reference volume to make ROI adjustment easier.
*   **Batch Processing**: All volumes in the table are processed sequentially, and the results are automatically added to the same hierarchy as their source volumes.
