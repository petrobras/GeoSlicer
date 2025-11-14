## Smart Foreground

The *Smart foreground* effect to segment the useful area of the sample in an image or volume. The step-by-step usage is divided into two stages:

1.  **Operation**: considers useful all areas of the image/volume that do not correspond to the edges.
2.  **Fragmentation (optional)**: eventual fissures between sample fragments are also no longer considered useful area. Available only for 2D images (thin sections) and recommended only for plane-polarized light (PP) thin sections.

### Operation

{{ video("segment_editor_smart_foreground_public.webm", caption="Video: Smart Foreground. Thin section adapted from [Luo *et al.*, 2022](https://onlinelibrary.wiley.com/doi/10.1155/2022/8328764) ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).") }}

1.  Define the input image and output segmentation according to the [*Segment Editor* usage tutorial](/ThinSection/Segmentation/Segmentation.md/#manual-segmentation). Creating segmentation/segments is not necessary if you prefer to edit existing segments.
2.  Select the *Smart foreground* effect.
3.  Select the segment to which the operation will be applied.
4.  Under *Operation*, select one of the operations:
    *   *Fill inside*: fills the segment over the useful area of the sample.
    *   *Erase outside*: excludes already segmented areas over the non-useful area of the sample.
5.  If you wish to apply fragmentation (if available), proceed with the steps below. Otherwise, ensure that the *Fragments* section (below *Operation*) is unavailable or that the *Split* option is unchecked, click *Apply* and wait for the process to finish.

### Fragmentation

6.  Under *Fragments*, check the *Split* option.
7.  Select one of the options:
    *   *Keep all*: keeps all fragments.
    *   *Filter the largest*: keeps only the fragments with the largest area. Enter the number of fragments to preserve.
8.  If you use the **public version of GeoSlicer**, an *Annotations* field should be visible, and the following steps should be executed. Otherwise, skip this step.
    *   Add two new segments to the output segmentation. Alternatively, you can create a new segmentation with two segments.
    *   Select one of the new segments created. Use marking effects such as [Draw](/ThinSection/Segmentation/Segmentation.md#draw), [Paint](/ThinSection/Segmentation/Segmentation.md#paint), or [Scissors](/ThinSection/Segmentation/Segmentation.md#scissors) to mark small samples of the rock texture.
    *   Select the other new segment. Now mark small samples of the pore resin in the image.
    *   Return to the *Smart foreground* effect and re-select the segment to which the operation will be applied.
    *   Under *Annotations*, select the segmentation that contains the marked segments.
    *   Under *Texture samples* and *Resin samples*, select the segments that mark, respectively, the texture and the resin.
9.  Click *Apply* and wait for the process to finish.