## Possible Workflows
### Data Import and Processing:

#### **Image Log Data:**
1. Import: Image Log Import or *[Geolog Integration](/Multiscale/GeologIntegration/GeologEnv.md)*
2. Inpaint: *[Image Log Infilling](/Multiscale/ImageLogPreProcessing/ImageLogPreProcessing.md#image-log-inpaint)*
3. Spiral Filter
4. Crop: *[Image Log Cropping](/Multiscale/ImageLogPreProcessing/ImageLogPreProcessing.md#image-log-crop)*
5. Segmentation
6. Image log export

#### **MicroCT Data:**
1. Import: *[Volumes Loader](/Multiscale/ImportTools/ImportTools.md#microct-import)*
2. Crop
3. Filter: Filter options for noise removal in microCT images, facilitating the segmentation step.
4. Segmentation
5. Transforms
6. Volumes export

#### **CoreCT Data:**
1. Import
2. Crop
3. Segmentation

### Simulating with *[Multiscale](/Multiscale/MultiscaleImageGeneration/Multiscale.md)*

#### **Infilling image logs with missing or incomplete data:**
1. Import well image: Image Log importer or Geolog Integration.
2. Segmentation: Separate into layers with data and without data.
3. Multiscale: Same image as TI and HD, uncheck empty space segment.
4. Simulation. Result should only fill the empty space.
5. Export data after simulation: Image Log Export (csv, DLIS or LAS) or Geolog Integration.

#### **Simulating a volume from an Image Log**
1. Import well image (HD): Image Log importer or Geolog Integration.
2. Import Training Image (TI): Volumes Loader or multicore.
3. Segmentation: Image segmentation is mandatory for discrete simulation. For continuous data, segmentation allows controlling regions included in the simulation.
4. Multiscale: 3D volume as TI and well image as HD.
5. Simulation: Check the "Wrap cylinder" option. Check the "Continuous Data" option.
6. Export data after simulation: Volumes export (TIF, RAW and other data). It is possible to export simulation results as TIF directly from the [Multiscale Image Generation](/Multiscale/MultiscaleImageGeneration/Multiscale.md) module.