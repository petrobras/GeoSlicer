from collections import Counter, namedtuple
from ltrace.slicer.cli_utils import readFrom
from numba import jit, prange
from scipy.spatial.distance import pdist
from skimage.measure import regionprops, find_contours, marching_cubes
from skimage.measure import label as sklabel
from skimage.segmentation import relabel_sequential
from ltrace.algorithms.measurements import LabelStatistics2D, exportSegmentsAsDataFrame
from ltrace.slicer.volume_operator import VolumeOperator, SegmentOperator
import json
import math
import numpy as np
import pandas as pd
import slicer


Arguments = namedtuple("Arguments", ["labelVolume", "params"])


class Rectangle:
    def __init__(self, x1, y1, x2, y2):
        if x1 > x2 or y1 > y2:
            raise ValueError("Coordinates are invalid")
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

    def intersects(self, other):
        r1x = self.x1
        r1w = self.x2 - self.x1
        r2x = other.x1
        r2w = other.x2 - other.x1
        r1y = self.y1
        r1h = self.y2 - self.y1
        r2y = self.y1
        r2h = self.y2 - self.y1

        return r1x + r1w >= r2x and r1x <= r2x + r2w and r1y + r1h >= r2y and r1y <= r2y + r2h


class ThroatAnalysis:
    def __init__(self, labelVolume, params, progress_update_callback=None):
        self.__boundary_labeled_array = None
        self.__throat_report_df = None
        args = Arguments(labelVolume=labelVolume, params=params)
        self.__progress_update_callback = (
            progress_update_callback if progress_update_callback is not None else lambda x: None
        )
        self.run(args)

    @property
    def boundary_labeled_array(self):
        return self.__boundary_labeled_array

    @property
    def throat_report_df(self):
        return self.__throat_report_df

    def run(self, args):
        if isinstance(args.params, str):
            params = json.loads(args.params)
        elif isinstance(args.params, dict):
            params = args.params
        else:
            raise NotImplementedError(f"Parameters input type {type(args.params)} not implemented.")

        image = slicer.util.arrayFromVolume(args.labelVolume).astype(np.uint8)
        shape = np.array(image.shape)

        if image.ndim != 3:
            error_message = (
                "Unexpected array from Label Map Volume Node. Please insert a Label Map Volume node with 2D image."
            )
            raise RuntimeError(error_message)

        if image.shape[0] == 1:
            image = image[0]
        else:
            raise NotImplementedError("The input's image data has unexpected shape.")

        boundaries_array = find_boundaries(image)

        boundaries_label_image = sklabel(boundaries_array)

        props = regionprops(boundaries_label_image)

        throat_region_props = []
        for boundary_region in props:
            # Check regions between the boundary region
            y1, x1, y2, x2 = boundary_region.bbox
            section = image[y1:y2, x1:x2]

            label_section = sklabel(section, background=0)
            boundaries_regions_props = regionprops(label_section)
            regions_quantity = len(boundaries_regions_props)
            if regions_quantity >= 1 and regions_quantity <= 2:
                throat_region_props.append(boundary_region)
            elif regions_quantity > 2:
                valid_regions = []
                rws = 3  # Rectangle window size

                # Check which regions has its central part intersecting the boundary region
                for region_1 in boundaries_regions_props:
                    y1, x1, y2, x2 = region_1.bbox
                    width = x2 - x1
                    height = y2 - y1

                    x1_mb = int(x1 + (width / 2) - rws)
                    y1_mb = int(y1 + (height / 2) - rws)
                    x2_mb = int(x1 + (width / 2) + rws)
                    y2_mb = int(y1 + (height / 2) + rws)

                    section_region_image = boundary_region.image[y1_mb:y2_mb, x1_mb:x2_mb]

                    unique_values = np.unique(section_region_image)

                    if len(unique_values) == 1 and unique_values[0] == 0:
                        continue

                    valid_regions.append(region_1)

                # Filter identified pore-near-boundary regions that might represent the same throat
                regions_to_remove = set()
                for region_1 in valid_regions:
                    y1_region_1, x1_region_1, y2_region_1, x2_region_1 = region_1.bbox
                    width_region_1 = x2_region_1 - x1_region_1
                    height_region_1 = y2_region_1 - y1_region_1

                    x1_region_1_mb = int(x1_region_1 + (width_region_1 / 2) - rws)
                    y1_region_1_mb = int(y1_region_1 + (height_region_1 / 2) - rws)
                    x2_region_1_mb = int(x1_region_1 + (width_region_1 / 2) + rws)
                    y2_region_1_mb = int(y1_region_1 + (height_region_1 / 2) + rws)
                    rect_region_1 = Rectangle(x1_region_1_mb, y1_region_1_mb, x2_region_1_mb, y2_region_1_mb)

                    for region_2_idx, region_2 in enumerate(valid_regions):
                        if region_2 is region_1:
                            continue

                        y1_region_2, x1_region_2, y2_region_2, x2_region_2 = region_2.bbox
                        width_region_2 = x2_region_2 - x1_region_2
                        height_region_2 = y2_region_2 - y1_region_2

                        x1_region_2_mb = int(x1_region_2 + (width_region_2 / 2) - rws)
                        y1_region_2_mb = int(y1_region_2 + (height_region_2 / 2) - rws)
                        x2_region_2_mb = int(x1_region_2 + (width_region_2 / 2) + rws)
                        y2_region_2_mb = int(y1_region_2 + (height_region_2 / 2) + rws)

                        rect_region_2 = Rectangle(x1_region_2_mb, y1_region_2_mb, x2_region_2_mb, y2_region_2_mb)
                        if not rect_region_1.intersects(rect_region_2):
                            continue
                        else:
                            # Check which box is 'insider' the the boundary image
                            rect_region_1_density = get_image_boundary_density(boundary_region.image, rect_region_1)
                            rect_region_2_density = get_image_boundary_density(boundary_region.image, rect_region_2)
                            if rect_region_1_density > rect_region_2_density:
                                regions_to_remove.add(region_2_idx)
                                continue

                            elif rect_region_1_density == rect_region_2_density:
                                # Select which one has the highest feret value
                                region_1_feret = feret_diameter_max(region_1)
                                region_2_feret = feret_diameter_max(region_2)
                                if region_1_feret > region_2_feret:
                                    regions_to_remove.add(region_2_idx)
                                    continue

                regions_to_remove = sorted(regions_to_remove)
                for region_idx in reversed(list(regions_to_remove)):
                    valid_regions.pop(region_idx)

                throat_region_props.extend(valid_regions)

        #  Relabel array to avoid 'empty' label cases
        boundaries_label_image = relabel_sequential(boundaries_label_image, offset=1)[0]

        params["args"] = args
        self.__throat_report_df, boundaries_array_relabeled = self.__generate_statistics(boundaries_label_image, params)
        self.__boundary_labeled_array = boundaries_array_relabeled.reshape(shape).astype(np.uint32)

    def __generate_statistics(self, boundaries_array, params):
        """Generate statistics from the boundary array and a relabeled array that matchs the report.

        Args:
            boundaries_array (np.array): the boundary 2D array.
            params (dict): configuration parameters dict.

        Returns:
            pd.DataFrame: the throats identification and statitics report as DataFrame
            np.array: the re-labeled boundary 2D array.
        """
        regions = boundaries_array
        args = params["args"]
        direction_vector = params.get("direction", None)
        spacing = params.get("spacing", None)

        operator = LabelStatistics2D(regions, spacing, direction_vector, 0, is_pore=True)

        volume_operator = VolumeOperator(args.labelVolume, dtype=np.uint16)  # uint16 to accept 2^16 labels at least.
        df, nlabels = exportSegmentsAsDataFrame(
            regions,
            SegmentOperator(operator, volume_operator.ijkToRasOperator),
            stepcb=lambda i, total: self.__progress_update_callback(i / total),
        )
        df = df.set_axis(operator.ATTRIBUTES, axis=1)
        df = df.sort_values(by=["label"], ascending=True)

        if df.shape[1] > 1 and df.shape[0] > 0:
            df = df.dropna(axis=1, how="all")  # Remove unused columns
            df = df.dropna(axis=0, how="any")  # Remove unused columns

            # Relabel array due to report handling
            indices = np.array(df.label, copy=True, dtype=int)
            relabel_map = np.zeros(nlabels + 1)
            relabel_map[indices] = np.arange(1, len(df) + 1)
            df.label = np.arange(1, len(df) + 1)
            regions = relabel_map[regions].astype(np.uint16)

        # Generate report data frame
        report_df = pd.DataFrame()
        report_df["Label"] = df.label
        report_df["ID"] = self.__generate_ids(
            boundaries_label_image=regions, input_label_image=volume_operator._array[0]
        )
        if direction_vector is not None and len(direction_vector) > 0:
            report_df["Orientation (deg)"] = df["angle_ref_to_max_feret"].map("{:,.3f}".format)
        else:
            report_df["Orientation (deg)"] = df["angle"].map("{:,.3f}".format)

        report_df["Length (mm)"] = df["max_feret"]

        return report_df, regions

    def __generate_ids(self, boundaries_label_image, input_label_image):
        """Retrieve each throat ID by reading the region around of the throat from the original label image.

        Args:
            boundaries_label_image (np.array): the boundaries label map
            input_label_image (np.array): the original label map

        Returns:
            list: a throat ID list ordered by label in ascending order.
        """
        id_list = []
        label_list = []
        props = regionprops(boundaries_label_image)
        for throat_region in props:
            throat_id = create_throat_id(throat_region, input_label_image)
            if throat_id is None:
                continue

            id_list.append(throat_id)
            label_list.append(throat_region.label)

        id_list = rename_duplicated_ids(id_list)
        df = pd.DataFrame({"id": id_list, "label": label_list})

        df = df.sort_values(by=["label"], ascending=True)
        return df["id"].tolist()


@jit(nopython=True)
def find_boundaries(image):
    """Create a binary 2D array indicating where there is a boundary 'line' between two different pores regions

    Args:
        image (np.array): the image's array.

    Returns:
        np.array: the 2d numpy array.
    """
    result_arr = np.zeros(image.shape)
    x, y = image.shape

    window_size = 2
    for i in prange(x - math.ceil(window_size / 2)):
        for j in prange(y - math.ceil(window_size / 2)):
            input_view = image[i : i + window_size, j : j + window_size]
            unique_elements = np.unique(input_view)
            unique_elements = unique_elements[unique_elements != 0]

            if len(unique_elements) > 1:
                result_arr[i : i + window_size, j : j + window_size] = np.sum(unique_elements)

    for i in prange(len(result_arr)):
        for j in prange(len(result_arr[i])):
            if image[i, j] == 0:
                result_arr[i, j] = 0

    return result_arr


def feret_diameter_max(region):
    """Get feret value from RegionProperties object, based on skimage.RegionProperties feret_diameter_max method.
       (reference: https://github.com/scikit-image/scikit-image/blob/a4681561fa3b4614db1d81a494924a9890c4538b/skimage/measure/_regionprops.py#L440)
       This method was created because the property is available only for newer skimage library version.

    Args:
        region (RegionProperties): the RegionProperties object.

    Returns:
        float: the RegionProperties max diameter's feret.
    """
    identity_convex_hull = np.pad(region.convex_image, 2, mode="constant", constant_values=0)
    if region._ndim == 2:
        coordinates = np.vstack(find_contours(identity_convex_hull, 0.5, fully_connected="high"))
    elif region._ndim == 3:
        coordinates, _, _, _ = marching_cubes(identity_convex_hull, level=0.5)
    distances = pdist(coordinates, "sqeuclidean")
    return math.sqrt(np.max(distances))


def get_image_boundary_density(boundary_image_array, section_rect):
    x1, y1, x2, y2 = section_rect.x1, section_rect.y1, section_rect.x2, section_rect.y2
    arr = boundary_image_array[y1:y2, x1:x2]
    unique, counts = np.unique(arr, return_counts=True)
    counts_dict = dict(zip(unique, counts))
    return counts_dict.get(1, 0)


def rename_duplicated_ids(id_list):
    """Append characters to the repeated ID's from the list.
       ex: input list: (1-2, 1-2, 1-3) -> output list: (1-2a, 1-2b, 1-3)

    Args:
        id_list (list): the throats identification list

    Returns:
        list: relabeled throats identification list
    """
    id_count_dict = {a: list(range(1, b + 1)) if b > 1 else "" for a, b in Counter(id_list).items()}
    new_id_list = [f"{i}{str(chr(96 + id_count_dict[i].pop(0)))}" if len(id_count_dict[i]) else i for i in id_list]
    return new_id_list


def create_throat_id(region, image):
    """Create a string identification for the specific throat region, based on the
       pores label value placed near its boundary.

    Args:
        region (RegionProperties): the Throat's RegionProperties object.
        image (np.array): The original image's array

    Returns:
        str: the throat identification string.
    """
    y1, x1, y2, x2 = region.bbox
    section_image = image[y1:y2, x1:x2]
    pores, counts = np.unique(section_image, return_counts=True)
    pores_counts_tuple_list = zip(pores, counts)

    # Sort list by pore frequency in image by descending order
    pores_counts_tuple_list = sorted(pores_counts_tuple_list, key=lambda tuple: tuple[1], reverse=True)

    pores = []
    for pore_count_tuple in pores_counts_tuple_list:
        pore = pore_count_tuple[0]
        if pore == 0:
            continue

        pores.append(pore)

        if len(pores) >= 2:
            break

    if len(pores) != 2:
        return None

    pores.sort()
    return f"{pores[0]}-{pores[1]}"
