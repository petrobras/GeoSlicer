from collections import namedtuple
from ltrace.assets_utils import get_asset
from ltrace.image.core_box.core_box import CoreBox
from ltrace.slicer.helpers import concatenateImageArrayVertically, resizeRgbArray
from ltrace.units import safe_atof
from sklearn.cluster import MeanShift

import cv2
import math
import numpy as np
import pytesseract
import re
import os
import logging

CoreImageCategory = namedtuple("CoreImageCategory", ["name", "sufix"])

FullCoreImage = CoreImageCategory(name="Full Core Image", sufix="_serrado")
FullCoreUVImage = CoreImageCategory(name="Full Core UV Image", sufix="_uv_serrado")
CoreWithoutPlugImage = CoreImageCategory(name="Core without Plug Image", sufix="")


class CoreBoxesImageFile:
    CATEGORIES = [FullCoreImage, FullCoreUVImage, CoreWithoutPlugImage]
    TESSERACT_MODEL_NORMAL = 0
    TESSERACT_MODEL_FAST = 1
    BinarySegmenterModel = None

    def __init__(
        self,
        image_file,
        default_depth=None,
        load=False,
        core_boxes_depth_list=list(),
        start_depth=None,
        gpuEnabled=True,
    ):
        """Opens and loads information from a photo of boxes with cores inside.

        If core_boxes_depth_list is not None, use depths from this list.
        Else if default_depth and start_depth are not None, assume first core to be at start_depth and every core to have default_depth.
        Else use depths by reading OCR data from image.

        Args:
            image_file (str):
                Path to the photo's file.
            default_depth (float):
                Predefined depth for every core.
            load (boolean):
                True: loads and process photo at class constrction; False: Constructs object without reading photo.
            core_boxes_depth_list (CoreBoxDepth list):
                List with predefined depth for each core.
            start_depth (float):
                Predefined depth for the first core.
        """
        self.__gpuEnabled = gpuEnabled
        self.__file_path = image_file
        self.__category = None
        self.__core_id = None
        self.__first_box_number = None
        self.__last_box_number = None
        self.__total_box_number = None
        self.__core_box_list = list()
        self.__default_box_depth = default_depth
        self.__core_boxes_depth_list = core_boxes_depth_list
        self.__start_depth = start_depth
        self.__average_depth_per_pixel = None
        self.__parse_informations(image_file)
        if load:
            self.load_cores(image_file)

    @property
    def file_path(self):
        return self.__file_path

    @property
    def category(self):
        return self.__category

    @property
    def core_id(self):
        return self.__core_id

    @property
    def first_box_number(self):
        return self.__first_box_number

    @property
    def last_box_number(self):
        return self.__last_box_number

    @property
    def total_box_number(self):
        return self.__total_box_number

    @property
    def cores(self):
        return self.__core_box_list

    @property
    def start_depth(self):
        return self.__start_depth

    @property
    def average_depth_per_pixel(self):
        return self.__average_depth_per_pixel

    @property
    def total_height(self):
        first_core_box = self.__core_box_list[0]
        last_core_box = self.__core_box_list[-1]

        total_height = abs(last_core_box.start_depth + last_core_box.height - first_core_box.start_depth)
        return total_height

    @property
    def list(self):
        self.__core_box_list.sort(key=lambda core_box: core_box.box_number)
        # Sort in asceding order by box number
        return self.__core_box_list

    def __parse_informations(self, image_file):
        """Extract information from file's name pattern.

        Args:
            image_file (str): the image files path

        Raises:
            RuntimeError: When current file's name pattern doesn't match the expected file name.
        """
        file_name = os.path.basename(image_file)
        regex_pattern = "([0-9]+)cx([0-9]+)-([0-9]+)_([0-9]+)(_(\S+))?\.\S+"
        pattern = re.compile(regex_pattern)
        match = re.search(pattern, file_name)
        if match is None:
            message = f"Selected image file {file_name} doesn't have a valid pattern name."
            logging.warning(message)
            raise RuntimeError(message)

        groups = match.groups()
        try:
            self.__core_id = int(groups[0])
            self.__first_box_number = int(groups[1])
            self.__last_box_number = int(groups[2])
            self.__total_box_number = int(groups[3])

            category = groups[-1]

            if category is not None:
                category_lower = list(name.lower() for name in category.split("_"))
            else:
                category_lower = []
            if "uv".lower() in category_lower:
                self.__category = FullCoreUVImage
            elif "serrado".lower() in category_lower:
                self.__category = FullCoreImage
            else:
                self.__category = CoreWithoutPlugImage

        except RuntimeError:
            message = f"Something went wrong during image file {file_name} information parsing."
            logging.warning(message)
            raise RuntimeError(message)

    def __crop_core_background(self, core_image, mask):
        """Crop core's image to remove (most of) the background space.

        Args:
            core_image (np.ndarray): the core's image array.
            mask       (np.ndarray): core mask for the image (1 is core; 0 is background)

        Returns:
            np.ndarray: the new core's image array.
        """
        where = np.where(mask)
        y0 = where[0].min()
        y1 = where[0].max()
        x0 = where[1].min()
        x1 = where[1].max()

        # crop the image at the bounds
        cropped_image = core_image[y0:y1, x0:x1]
        return cropped_image

    def load_cores(self, image_file):
        """Handle the core photograph image processing.

        Args:
            image_file (str): the core image file path.
        """
        self.__core_box_list.clear()

        img = cv2.cvtColor(cv2.imread(str(image_file), 1), cv2.COLOR_BGR2RGB)
        cores = self.__extract_cores_info(img)
        core_images = cores["img"]
        core_depths = cores["depth"]
        scale_length_px = cores["scale_length_px"]

        for index, core in enumerate(core_images):
            box_number = self.__first_box_number + index

            # If there is a table with depth information for all core boxes, then use its information
            if (
                self.__core_boxes_depth_list is not None
                and len(self.__core_boxes_depth_list) > 0
                and box_number <= len(self.__core_boxes_depth_list)
            ):
                box_depth_info = self.__core_boxes_depth_list[box_number - 1]
                box_height = box_depth_info.height
                core_start_depth = box_depth_info.start
            elif self.__default_box_depth is not None and self.__start_depth is not None:
                box_height = self.__default_box_depth
                core_start_depth = self.__start_depth + box_height * index
            else:
                box_height = 1.0 * core.shape[0] / scale_length_px
                core_start_depth = core_depths[index]

            try:
                core_box = CoreBox(
                    image_array=core,
                    box_number=index,
                    core_id=self.__core_id,
                    category=self.__category,
                    height=box_height,
                    start_depth=core_start_depth,
                )
            except RuntimeError as error:
                logging.warning(error)
                continue

            self.__core_box_list.append(core_box)

    # this adjustment should be made globally, as it is being made at the CoreImage.__concatenate_core_boxes
    # def __check_depth(self):
    #     """Adjust core boxes height based on the biggest core's information.
    #     """
    #     if len(self.__core_box_list) <= 2:
    #         return

    #     max_height_pixel_size = 0
    #     depth_reference_max_height = 0
    #     for core_box in self.__core_box_list:
    #         core_box_height_pixel_size = core_box.array.shape[0]
    #         if core_box_height_pixel_size > max_height_pixel_size:
    #             max_height_pixel_size = core_box_height_pixel_size
    #             depth_reference_max_height =  core_box.height

    #     self.__average_depth_per_pixel = depth_reference_max_height/max_height_pixel_size

    #     for core_box in self.__core_box_list:
    #         expected_core_box_height = int(math.floor((1/self.__average_depth_per_pixel) * core_box.height))
    #         if expected_core_box_height != core_box.array.shape[0]:
    #             core_box.resize(height=expected_core_box_height, width=core_box.array.shape[1])

    def __change_background_color(self, core: np.ndarray, model, background_color=[0, 0, 0]):
        """Uses a trained model to distingish the images part thats relate to the core from the background (box, foam, etc).
           The background part in the input's image is changed to the input color.

        Args:
            core (np.ndarray): the core image as array
            model (_): the trained neural network's model.
            background_color (list, optional): The desired background color. Defaults to [0, 0, 0] (black).

        Returns:
            core (np.ndarray): the core image with background color changed.
            mask (np.ndarray): the core mask where 1 is the core, and 0 is the background
        """
        img_yuv = cv2.cvtColor(core, cv2.COLOR_RGB2YUV)

        # equalize the histogram of the Y channel
        img_yuv[:, :, 0] = cv2.equalizeHist(img_yuv[:, :, 0])

        # convert the YUV image back to RGB format
        equ = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2RGB)

        mask = model.predict(equ)
        mask = mask.reshape(np.shape(core)[:2])

        kernel = np.ones((15, 15), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        core[mask == 0] = background_color

        return core, mask

    def __extract_cores_info(self, img):
        """Handle core boxes photograph to extract the depth value and split each core into separated images

        Args:
            img (str): the core boxes' photograph file path

        Returns:
            dict list:
                "img"   - a list of core images
                "depth" - a list of the depths of each core
        """
        cores_info = {}
        cores_info["depth"] = self.__recognize_depth_values(img)

        cores_info["scale_length_px"] = self.__get_scale_bar_length(img)

        cores_info["img"] = []
        number_of_cores = len(cores_info["depth"])

        if CoreBoxesImageFile.BinarySegmenterModel is None:
            from ltrace.image.segmentation import TF_RGBImageArrayBinarySegmenter

            CoreBoxesImageFile.BinarySegmenterModel = TF_RGBImageArrayBinarySegmenter(
                get_asset("unet-binary-segop.h5"), gpuEnabled=self.__gpuEnabled
            )

        for core_cut in self.__split_cores(img, number_of_cores):
            _, mask = self.__change_background_color(core_cut, CoreBoxesImageFile.BinarySegmenterModel)
            cropped_core_cut = self.__crop_core_background(core_cut, mask)
            cores_info["img"].append(cropped_core_cut)

        return cores_info

    def __recognize_depth_values(self, photo_with_labels):
        """Reads depth values from the image
        1st step: preprocesses the image to hilight texts.
        2nd step: perform OCR in the entire preprocessed image to find where the text with depth is.
        3rd step: if the previous step fails, cut only the image where the text with depth is.
        4th step: perform OCR again, this time only in the area with the depth text.

        Args:
            photo_with_labels (BGR image): A photo of some core samples in its boxes

        Returns:
            float list: depth values. The order is the same as the one in the photo, from left to right.
        """
        processed_img = self.__preprocess_image_for_ocr(photo_with_labels, apply_blur=True)

        depth_ocr_data = self.__ocr_depths(
            processed_img, single_line_of_text=False, tesseract_model=self.TESSERACT_MODEL_FAST
        )
        depth_values = self.__get_depth_values_from_ocr(depth_ocr_data)

        if self.__check_depth_consistency(depth_values):
            return depth_values

        depth_rect_img = self.__cut_img_rect_with_depths(depth_ocr_data, photo_with_labels)
        processed_img = self.__preprocess_image_for_ocr(depth_rect_img, apply_blur=False)

        depth_ocr_data = self.__ocr_depths(
            processed_img, single_line_of_text=True, tesseract_model=self.TESSERACT_MODEL_NORMAL
        )
        depth_values = self.__get_depth_values_from_ocr(depth_ocr_data)

        if self.__check_depth_consistency(depth_values):
            return depth_values
        else:
            raise RuntimeError(f"The depth values in the {self.__file_path} photo could not be " "recognized.")

    def __split_cores(self, photo_with_labels, number_of_cores):
        photo = self.__crop_borders(photo_with_labels)
        return self.__cut_image_vertically(photo, number_of_cores)

    def __preprocess_image_for_ocr(self, photo, apply_blur):
        """Perform OCR of a core sample photo

        Args:
            photo (BGR image): A photo of some core samples in its boxes

        Returns:
            dictionary: A dictionary with the data read from the photo
        """
        # Apply some filters to the original photo
        img = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
        if apply_blur:
            img = cv2.medianBlur(img, 3)
        ret, img = cv2.threshold(img, 220, 255, cv2.THRESH_BINARY)
        img = 255 - img
        kernel = np.ones((2, 2), np.uint8)
        img = cv2.morphologyEx(img, cv2.MORPH_OPEN, kernel)

        return img

    def __ocr_core_photo(self, img, single_line_of_text, tesseract_model):
        """Perform optical character recognition using Tesseract

        Args:
            photo (BGR image): A photo with the depth values for the cores
            single_line_of_text (bool):
                True: it will be assumed that the image has only a line of text.
                False: the method will try to find the depths values anywhere inside the image.
            tesseract_model:
                TESSERACT_MODEL_FAST: The fast trained model, it's also the tesseract's default one
                    https://github.com/tesseract-ocr/tessdata_fast
                TESSERACT_MODEL_NORMAL: A improved but slower trained model
                    https://github.com/tesseract-ocr/tessdata
        """
        # Character whitelist:
        # T: avoids mistaking depths with title (title has annotations like "T-01")
        # cx/: avoid mistaking depths with boxes' description on the bottom of the image
        # 0123456789,: depth characters
        # .: The normal model has some difficulty recognizing commas, thinking some are dots instead.
        char_whitelist = "Tcx/ 0123456789,."

        if single_line_of_text:
            psm = 7
        else:
            psm = 12
        if tesseract_model == self.TESSERACT_MODEL_FAST:
            tesseract_model = "eng_fast"
            oem = 1
        else:
            tesseract_model = "eng"
            oem = 2
        return pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            lang=tesseract_model,
            config=f'-c tessedit_char_whitelist="{char_whitelist}" --psm {psm} --oem {oem}',
        )

    def __ocr_replace_dot_with_comma(self, photo_raw_ocr):
        """Replace every dot in the depth OCR text with comma.

        Args:
            depth_ocr_data (dict): OCR data of the depth values in core photo similar to tesseract's dict

        Returns:
            dict: Same OCR data but with commas instead of dots.
        """
        for i, text in enumerate(photo_raw_ocr["text"]):
            photo_raw_ocr["text"][i] = text.replace(".", ",")
        return photo_raw_ocr

    def __get_vertical_clusters_from_ocr(self, ocr_dict):
        """Organize the recognized texts into clusters according to its vertical position.

        Args:
            ocr_dict (dictionary): A dictionary with the OCR data read from the image

        Returns:
            list of dictionaries
                Each entry in the list has a dictionary with every recognized text of a single cluster.
                The dictionary keys is a subset of the ones in the OCR data:
                    "left"   - The position of the reconized text from the left of the image
                    "top"    - The position of the reconized text from the top of the image
                    "width"  - The width of the reconized text in the image
                    "height" - The height of the reconized text in the image
                    "text"   - The recognized text itself
        """
        positions_from_top = np.array(ocr_dict["top"])
        samples = np.array([(x, 0) for x in positions_from_top], dtype=int)
        ms = MeanShift(bandwidth=10, bin_seeding=True)
        ms.fit(samples)

        clusters = []

        confidence_index = np.array(ocr_dict["conf"]) != "-1"
        for k in np.unique(ms.labels_):
            current_label_index = ms.labels_ == k
            valid_boolean_array = np.logical_and(confidence_index, current_label_index)

            cluster_data = {}
            cluster_data["left"] = np.array(ocr_dict["left"])[valid_boolean_array]
            cluster_data["top"] = np.array(ocr_dict["top"])[valid_boolean_array]
            cluster_data["width"] = np.array(ocr_dict["width"])[valid_boolean_array]
            cluster_data["height"] = np.array(ocr_dict["height"])[valid_boolean_array]
            cluster_data["text"] = np.array(ocr_dict["text"])[valid_boolean_array]
            clusters.append(cluster_data)

        return clusters

    def __has_only_numbers(self, texts):
        """Check if the list has only numbers in it

        Args:
            texts (str list): List to be checked

        Returns:
            boolean: True if every string inside the list can be converted to numbers
                     False otherwise
        """
        for text in texts:
            if safe_atof(text) is None:
                return False
        return True

    def __find_depth_cluster(self, ocr_clusters):
        """Find the cluster that has the labels with core depth values.

        Args:
            ocr_clusters (dict list): OCR information separated in clusters

        Returns:
            dictionary: OCR information of the labels containing the core depth values
        """
        depth_cluster_candidates = []
        for cluster in ocr_clusters:
            if not self.__has_only_numbers(cluster["text"]):
                continue
            depth_cluster_candidates.append([len(cluster["text"]), cluster])
        # Choose the cluster with more reconized texts
        max_text_index = np.argmax(np.array(depth_cluster_candidates)[:, 0])
        return depth_cluster_candidates[max_text_index][1]

    def __ocr_depths(self, photo, single_line_of_text, tesseract_model):
        """Get core depths from the photo using OCR

        Args:
            photo (BGR image): A photo with the depth values for the cores
            single_line_of_text (bool):
                True: it will be assumed that the image has only a line of text containing only
                the values of the depths.
                False: the method will try to find the depths values anywhere inside the image.
            tesseract_model: The trained model that will be used by tesseract

        Return:
            float list: depth values. The order is the same as the one in the photo, from left to right.
        """
        photo_raw_ocr = self.__ocr_core_photo(photo, single_line_of_text, tesseract_model)
        depth_ocr_data = self.__ocr_replace_dot_with_comma(photo_raw_ocr)

        if not single_line_of_text:
            ocr_clusters = self.__get_vertical_clusters_from_ocr(depth_ocr_data)
            depth_ocr_data = self.__find_depth_cluster(ocr_clusters)

        return self.__merge_close_ocr_text(depth_ocr_data)

    def __cut_img_rect_with_depths(self, depth_ocr_data, photo):
        """Cut the image where the depth texts are

        Args:
            depth_ocr_data (dict): The OCR data of the recgonized text with the depth values
            photo (img array): The entire core photo

        Returns:
            img array: A rectangular image only containing the depth values
        """
        max_width = depth_ocr_data["width"].max()
        max_height = depth_ocr_data["height"].max()
        lower_top = depth_ocr_data["top"].max()
        upper_bottom = (depth_ocr_data["top"] + depth_ocr_data["height"]).min()
        leftmost_right = (depth_ocr_data["left"] + depth_ocr_data["width"]).min()
        rightmost_left = depth_ocr_data["left"].max()

        error_margin = 0.3
        max_width += math.ceil(max_width * error_margin)
        max_height += math.ceil(max_height * error_margin)

        rect_left = leftmost_right - max_width
        rect_right = rightmost_left + max_width
        rect_top = upper_bottom - max_height
        rect_bottom = lower_top + max_height
        return photo[rect_top:rect_bottom, rect_left:rect_right]

    def __merge_close_ocr_text(self, depth_ocr_data):
        """Merge OCR texts that are too close
        Sometimes the OCR processment divide a single depth value in several separated recognitions.
        This method merges those recognitions that are too close and therefore must be from a same
        depth value.

        Args:
            depth_ocr_data (dict): OCR data of the depth values in core photo similar to tesseract's dict

        Return
            depth_ocr_data (dict): Same OCR data but with merged recognitions
        """
        MIN_DISTANCE_BETWEEN_LABELS = 20
        labels_ordered_idexes = np.argsort(depth_ocr_data["left"])
        final_indexes = np.zeros(len(labels_ordered_idexes), int)
        for i in range(len(labels_ordered_idexes) - 1):
            label_end_position = (
                depth_ocr_data["left"][labels_ordered_idexes[i]] + depth_ocr_data["width"][labels_ordered_idexes[i]]
            )
            next_label_begin_position = depth_ocr_data["left"][labels_ordered_idexes[i + 1]]
            if next_label_begin_position - label_end_position < MIN_DISTANCE_BETWEEN_LABELS:
                final_indexes[i + 1] = final_indexes[i]
            else:
                final_indexes[i + 1] = final_indexes[i] + 1

        left_array = []
        top_array = []
        width_array = []
        height_array = []
        text_array = []
        for i in np.unique(final_indexes):
            indexes = labels_ordered_idexes[np.where(final_indexes == i)]
            left_array.append(np.array(depth_ocr_data["left"])[indexes].min())
            top_array.append(np.array(depth_ocr_data["top"])[indexes].min())
            width_array.append(np.array(depth_ocr_data["width"])[indexes].max())
            height_array.append(np.array(depth_ocr_data["height"])[indexes].max())
            text_array.append("".join(np.array(depth_ocr_data["text"])[indexes]))

        return {
            "left": np.array(left_array),
            "top": np.array(top_array),
            "width": np.array(width_array),
            "height": np.array(height_array),
            "text": np.array(text_array),
        }

    def __get_depth_values_from_ocr(self, depth_ocr_data):
        """Extract core depth values from OCR data

        Args:
            depth_ocr_data (dict): OCR data of the depth values in core photo similar to tesseract's dict

        Return:
            float list: depth values. The order is the same as the one in the photo, from left to right.
        """
        output = []
        for text in depth_ocr_data["text"]:
            output.append(safe_atof(text))
        return output

    def __crop_borders(self, photo):
        """Remove the borders from the original image, returning only the actual photo

        Args:
            photo (BGR image): A photo of some core samples in its boxes

        Returns:
            Only the photo of the cores, without the borders, labels and texts
        """
        photo_gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)

        # Mask every white
        ret, white_mask = cv2.threshold(photo_gray, 220, 255, cv2.THRESH_BINARY)
        white_mask = 255 - white_mask

        # Mask every black
        ret, black_mask = cv2.threshold(photo_gray, 10, 255, cv2.THRESH_BINARY)

        # Mask scale to the right of the cores (the non-white part of the scale)
        scale_mask = cv2.cvtColor(photo, cv2.COLOR_BGR2HSV)
        scale_mask = cv2.inRange(scale_mask, (0, 0, 124), (0, 0, 130))
        scale_mask = 255 - scale_mask

        # Unify masks
        central_image_threshold = np.bitwise_and(white_mask, black_mask)
        central_image_threshold = np.bitwise_and(central_image_threshold, scale_mask)

        # Remove noise
        kernel = np.ones((5, 5), np.uint8)
        central_image_threshold = cv2.morphologyEx(central_image_threshold, cv2.MORPH_OPEN, kernel)

        # Remove internal "leaks" inside the photo
        kernel = np.ones((20, 20), np.uint8)
        central_image_threshold = cv2.morphologyEx(central_image_threshold, cv2.MORPH_CLOSE, kernel)

        # Find the largest "object" in the image
        contours, _ = cv2.findContours(central_image_threshold, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        largest_contour = max(contours, key=cv2.contourArea)

        central_image_mask = np.zeros(central_image_threshold.shape, np.uint8)
        cv2.drawContours(central_image_mask, [largest_contour], 0, 255, -1)

        # Crop
        (y, x) = np.where(central_image_mask == 255)
        (top_y, top_x) = (np.min(y), np.min(x))
        (bottom_y, bottom_x) = (np.max(y), np.max(x))

        output_image = photo[top_y : bottom_y + 1, top_x : bottom_x + 1]
        return output_image

    def __cut_image_vertically(self, img, num_of_sections):
        """Vertically cut an image into N sections

        Args:
            img (image array): Image to be cut
            number_of_sections (int): Number of sections the image will be cut into

        Returns:
            image list: A list with the sections from left to right
        """
        sections = []
        img_width = img.shape[1]
        section_width = int(img_width / num_of_sections)
        for i in range(num_of_sections):
            x = i * section_width
            sections.append(img[:, x : x + section_width])
        return sections

    def __get_scale_bar_length(self, photo):
        """Get the length of the gray and white scale in the photo

        Args:
            photo (image array): The photo with the scale in it

        Returns:
            int: The length of the scale bar in pixels
        """
        kernel_size = int(photo.shape[0] * 0.006)
        morph_kernel = np.ones((kernel_size, kernel_size), np.uint8)

        # Get centers of scale's white parts
        scale_white_mask = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
        ret, scale_white_mask = cv2.threshold(scale_white_mask, 220, 255, cv2.THRESH_BINARY)
        scale_white_mask = cv2.morphologyEx(scale_white_mask, cv2.MORPH_OPEN, morph_kernel)
        scale_white_mask = cv2.morphologyEx(scale_white_mask, cv2.MORPH_CLOSE, morph_kernel)

        contours, _ = cv2.findContours(scale_white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours_centers = []
        for countour in contours:
            moments = cv2.moments(countour)
            center_x = int(moments["m10"] / moments["m00"])
            center_y = int(moments["m01"] / moments["m00"])
            contours_centers.append((center_x, center_y))
        contours_centers = np.array(contours_centers)
        area_list = np.array(list(map(cv2.contourArea, contours)))
        area_list = area_list / photo.shape[0] ** 2
        center_x_list = contours_centers[:, 0]
        center_x_list = center_x_list / photo.shape[1]
        samples = np.column_stack((area_list, center_x_list))
        ms = MeanShift(bandwidth=0.001, bin_seeding=True)
        ms.fit(samples)  # Find the most similar group of contours by their area and X position
        scale_parts_index = np.bincount(
            ms.labels_
        ).argmax()  # The group with more contours is assumed to be the one with the parts of the scale
        contours_centers = contours_centers[np.where(ms.labels_ == scale_parts_index)].tolist()

        # Get centers of scale's gray parts
        center_distance = int((contours_centers[0][1] - contours_centers[1][1]) / 2)
        for index in range(len(contours_centers)):
            center_x = contours_centers[index][0]
            center_y = contours_centers[index][1] + center_distance
            contours_centers.append((center_x, center_y))

        # Detect edges of scale
        img_edges = cv2.Canny(photo, 10, 150)
        img_edges = cv2.morphologyEx(img_edges, cv2.MORPH_CLOSE, morph_kernel)

        # Get scale mask (only upper and lower parts to save CPU)
        contours_centers.sort(key=lambda x: x[1])
        for center in [contours_centers[0], contours_centers[-1]]:
            cv2.floodFill(img_edges, None, center, 127)
        scale_mask = img_edges == 127

        # Get scale height in pixels
        (y, x) = np.where(scale_mask)
        top_y = np.min(y)
        bottom_y = np.max(y)

        return bottom_y - top_y

    def __check_depth_consistency(self, depth_values):
        """Checks if depths values are consistent

        Requirements:
        The depth values must be in ascending order.
        The gap distance between each depth must not be too much out of an average.

        Args:
            depth_values (float list): The depth values

        Returns:
            True if the depth values seem to be consistent; False otherwise.
        """
        if sorted(depth_values) != depth_values:
            return False

        if len(depth_values) > 1:
            diffs = []
            for i in range(1, len(depth_values)):
                diffs.append(depth_values[i] - depth_values[i - 1])
            diff_mean = np.array(diffs).mean()
            for diff in diffs:
                if not 0.25 < diff / diff_mean < 4:
                    return False
        return True
