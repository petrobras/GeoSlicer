# First Steps

As a first step, we will cover a simple segmentation workflow that can be performed with both thin section images and micro CT images.

To begin, open GeoSlicer and choose a project type on the home screen. The chosen environment must be compatible with the type of image you will use as an example. Choose **_Volumes_** for micro CT images and **_Thin Section_** for thin section images.

## 1. Open Image

The first step is to open the image you want to segment. When you select an environment from the initial menu, the module that will appear on the left side is the **_Loader_** for that environment.

- For micro CT, see this step in Load MicroCT (TODO).
- For thin sections, see this step in Load ThinSection (TODO).

## 2. Segment Image

After opening the image, the next step is to segment it. Segmentation is the process of dividing the image into regions of interest. The following image shows an example of segmenting a thin section into two regions: pore and non-pore. This segmentation can be done in the **_Segmentation -> Manual Segmentation_** module; see Manual Segmentation (TODO) for more details.

In this step, you can choose to create a second segmentation to represent the region of interest, i.e., the area you actually want to analyze. This step is usually performed when there is some dirt or an irrelevant region in the image.

## 3. Analyze Image

Once the segmentation is done, you can quantify the segmented regions and perform analyses such as pore size distribution.
For this, we will focus on the region of interest that you segmented as Pore. Use the **_Segment Inspector_** to inspect the image.

The **_Segment Inspector_** works similarly for both image types. It partitions the region of interest according to the user's chosen configuration. In this case, as we will analyze the porous region, it will partition the segmentation by identifying throats and separating pores. As a final result, in addition to the partitioned image, you get a table with various statistics about the pores (suffix '_Report').

## 4. Export Results

Finally, you can export the analysis results. Besides simply saving the project in GeoSlicer's format, you can export the analysis results in various formats, such as CSV, NetCDF, and RAW. This allows you to share these results or even load them into other software. For this, use the **_Exporter_** module. Test all formats to learn how each one behaves.