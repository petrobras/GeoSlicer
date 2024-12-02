import logging
import re
import vtk
import lasio
import numpy as np
import pandas as pd
import slicer


from collections import namedtuple
from pathlib import Path
from dlisio import dlis as dlisio
from pandas.errors import ParserError
from ltrace.constants import DLISImportConst
from ltrace.image.optimized_transforms import DEFAULT_NULL_VALUES, handle_null_values, ANP_880_2022_DEFAULT_NULL_VALUE
from ltrace.lmath.filtering import DistributionFilter
from ltrace.ocr import parse_pdf
from ltrace.slicer import helpers
from ltrace.slicer.helpers import getVolumeNullValue
from ltrace.slicer.node_attributes import (
    ImageLogDataSelectable,
    TableType,
    TableDataOrientation,
    TableDataTypeAttribute,
)
from ltrace.slicer_utils import dataFrameToTableNode
from ltrace.units import global_unit_registry as ureg
from ltrace.file_utils import read_csv

SCALAR_VOLUME_TYPE = DLISImportConst.SCALAR_VOLUME_TYPE
WELL_PROFILE_TAG = DLISImportConst.WELL_PROFILE_TAG
NULL_VALUE_TAG = DLISImportConst.NULL_VALUE_TAG
LOGICAL_FILE_TAG = DLISImportConst.LOGICAL_FILE_TAG
FRAME_TAG = DLISImportConst.FRAME_TAG
WELL_NAME_TAG = DLISImportConst.WELL_NAME_TAG
UNITS_TAG = DLISImportConst.UNITS_TAG
DEPTH_LABEL = DLISImportConst.DEPTH_LABEL

CURVES_NAME = ["T2_DIST", "T2DIST", "T1DIST"]
ChannelMetadata = namedtuple(
    "ChannelMetadata",
    [
        "mnemonic",
        "name",
        "unit",
        "frame_name",
        "logical_file",
        "is_labelmap",
        "is_table",
        "stacked_curves",  # For LAS files that contain curves to be stacked into images
    ],
)

LAS_DEPTH_TAGS = ["DEPT", "DEPTH"]


class DLISLoader(object):
    def __init__(self, filepath, nulls=set):
        self.filepath = filepath
        self.logical_files = dlisio.load(str(self.filepath))
        self.null_value = nulls

    def load_volumes(self, curves, stepCallback, appFolder, nullValue, well_diameter_mm, well_name):
        return load_volumes(curves, stepCallback, appFolder, nullValue, well_diameter_mm, well_name)

    def clean(self):
        self.logical_files.close()
        self.logical_files = None

    def load_metadata(self):
        if self.logical_files is None:
            raise ValueError("Missing DLIS file.")

        values_db = []
        well_name = ""
        for f in self.logical_files:
            if len(f.origins) > 1:
                logging.warning(f"File contains {len(f.origins)} origins")
            for o in f.origins:
                well_name = o.well_name
            for channel in f.channels:
                if channel.frame is None:
                    continue

                framename = channel.frame.name
                is_table = check_as_table(channel.name)
                values_db.append(
                    ChannelMetadata(
                        channel.name,
                        channel.long_name,
                        channel.units,
                        framename,
                        f.fileheader.id,
                        False,
                        is_table,
                        False,
                    )
                )

        return well_name, values_db

    def load_data(self, file_path, mnemonic_and_files):
        if self.logical_files is None:
            raise ValueError("Missing DLIS file.")

        filename = Path(file_path).stem

        for lf in self.logical_files:
            channel_selection = set([it for it in mnemonic_and_files if it.logical_file == lf.fileheader.id])

            for metadata in channel_selection:
                prop_pattern = r"^{}$".format(re.escape(metadata.mnemonic))
                channels = lf.find("CHANNEL", prop_pattern)

                domains_dict = {}

                for c in channels:
                    if c.frame is None:
                        continue

                    framename = c.frame.name
                    if framename != metadata.frame_name or (str(c.units) != str(metadata.unit)):
                        continue

                    image = c.curves()
                    if image is None:
                        continue

                    if not (framename in domains_dict):
                        domain_channel = c.frame.channels[0]
                        domain = domain_channel.curves()
                        domain = domain * conversion_factor_to_millimeters(domain_channel.units)
                        domains_dict[framename] = (
                            filename,
                            lf.fileheader.id,
                            domain_channel.name,
                            framename,
                            domain,
                            None,
                            True,
                            False,
                        )

                    curve_name = f"{c.name} [{c.units}]"

                    yield (
                        filename,
                        lf.fileheader.id,
                        curve_name,
                        framename,
                        domains_dict[framename][4],
                        image,
                        False,
                        metadata.is_labelmap,
                        metadata.is_table,
                        c.units,
                    )


class LASLoader(object):
    def __init__(self, filepath, nulls=set):
        self.filepath = filepath

        #   Some invalid data will be susbtituted by nan (also other malformed data) by lasio
        invalid_values_handling_options = ["(null)", "NA", "INF", "IO", "IND"]

        self.logical_files = lasio.read(str(self.filepath), null_policy=invalid_values_handling_options)

        # Finally, the null values substitutions will be left to GeoSlicer's handle_null_values function
        self.null_value = nulls
        if self.logical_files.well.NULL.value:
            self.null_value.add(
                self.logical_files.well.NULL.value
            )  # Ensuring that self.logical_files.well.NULL.value is in the substitution list

        self.stacked_curves_pattern = re.compile(r"(.+)[\[|(|{]([0-9]+)[\]|)|}]")

    def load_volumes(self, curves, stepCallback, appFolder, nullValue, well_diameter_mm=None, well_name=None):
        if self.logical_files is None:
            return []

        return load_volumes(
            curves=curves,
            stepCallback=stepCallback,
            appFolder=appFolder,
            nullValue=nullValue,
            well_diameter_mm=well_diameter_mm,
            well_name=well_name,
        )

    def clean(self):
        self.logical_files = None

    def find_wellname(self):
        try:
            keys = set(self.logical_files.well.keys())
            if "ORIGINALWELLNAME" in keys and self.logical_files.well["ORIGINALWELLNAME"].value != "":
                well_name = self.logical_files.well["ORIGINALWELLNAME"].value
            elif "WELL" in keys and self.logical_files.well["WELL"].value != "":
                well_name = self.logical_files.well["WELL"].value
            else:
                well_name = Path(self.filepath).stem
        except Exception as e:
            print(f"An error occurred while obtaining the Well name: {e}")

        return well_name

    def load_metadata(self):
        if self.logical_files is None:
            raise ValueError("Missing LAS file.")

        well_name = self.find_wellname()

        values_db = []

        last_curve_name = ""

        for i, curve in enumerate(self.logical_files.curves):
            values_db.append(
                ChannelMetadata(
                    curve.mnemonic,
                    curve.original_mnemonic,
                    curve.unit,
                    "",
                    well_name,
                    "",
                    is_table=check_as_table(curve.original_mnemonic),
                    stacked_curves=False,
                )
            )

            # Removing any number enclosed by []'s

            mnemo_search = self.stacked_curves_pattern.search(curve.mnemonic)

            mnemonic = original_mnemonic = ""

            if mnemo_search is None:
                mnemonic = curve.mnemonic
            else:
                mnemonic = mnemo_search.group(
                    len(mnemo_search.groups()) - 1
                )  # Same as in check_image_data: find mnemonic with enclosed number, e.g. UBI_AMP[0] or UBI_AMP [dB][0]

            if mnemonic == last_curve_name:
                values_db[i - 1] = values_db[i - 1]._replace(stacked_curves=True)
                values_db[i] = values_db[i]._replace(stacked_curves=True)
                # As stacked curves create 2D images, exporting as labelmap should now be possible. So, we change "" for False (otherwise the checkbox is disabled in our UI's table):
                values_db[i - 1] = values_db[i - 1]._replace(is_labelmap=False)
                values_db[i] = values_db[i]._replace(is_labelmap=False)
            else:
                last_curve_name = mnemonic

        return well_name, values_db

    def load_data(self, file_path, mnemonic_and_files):
        if self.logical_files is None:
            raise ValueError("Missing LAS file.")

        loaded_nodes_ids = []
        item_id = None

        filename = slicer.mrmlScene.GetUniqueNameByString(Path(file_path).stem)
        well_name = self.find_wellname()

        frame = ""

        depth_mnemonic = ""

        stacking = False
        last_curve_mnemonic = ""
        for i, mf in enumerate(mnemonic_and_files):
            curve = self.logical_files.curves[mf.mnemonic]

            # the depth curve will be set as the domain of the other curves, not as a standalone curve
            if curve.mnemonic in LAS_DEPTH_TAGS:
                continue

            try:
                domain = self.logical_files.depth_m
            except lasio.exceptions.LASUnknownUnitError:
                logging.debug(
                    "Exception while setting domain of curve " + str(curve.mnemonic) + ". Trying from keys..."
                )
                for key in ("DEPT", "DEPTH", 0):
                    try:
                        domain = self.logical_files[key]
                        logging.debug("Domain set from key " + str(key))
                        break
                    except KeyError:
                        continue

            domain = domain * conversion_factor_to_millimeters("m")

            image = curve.data
            name = curve.mnemonic
            units = curve.unit

            last_curve_mnemonic, is_same_mnemonic = checkMnemonicChanged(curve.mnemonic, last_curve_mnemonic)

            if not is_same_mnemonic:
                stacking = False
            if mf.stacked_curves:
                if stacking == False:
                    image = self.logical_files.stack_curves(last_curve_mnemonic)
                    name = last_curve_mnemonic
                    stacking = True
                else:
                    continue
            else:
                stacking = False

            name = f"{name}[{units}]"

            yield (
                filename,
                well_name,
                name,  # curve.mnemonic,
                "",
                domain,
                image,
                False,
                mf.is_labelmap,
                mf.is_table,
                units,
            )


class CSVLoader(object):
    def __init__(self, filepath, nulls=set):
        self.filepath = filepath
        self.curve_depth = None
        self.curve_name = None
        self.filename = None
        self.db = {}
        self.null_value = nulls
        self.loaded_as_image = False

    @staticmethod
    def _isLength(unit):
        return isinstance(unit, str) and ureg(unit).check("[length]")

    def load_volumes(self, curves, stepCallback, appFolder, nullValue, well_diameter_mm, well_name):
        if self.filename is None:
            logging.debug("CSVLoader load_volumes load metadata")
            self.load_metadata()

        logging.debug(
            "CSVLoader load_volumes return sucess name {} - type {}".format(self.filename, type(self.filename))
        )
        if self.loaded_as_image:
            return load_volumes(curves, stepCallback, appFolder, nullValue, well_diameter_mm, well_name)

        return load_volumes_as_table(
            curves=curves,
            stepCallback=stepCallback,
            appFolder=appFolder,
            nullValue=nullValue,
            name=self.filename,
            well_name=well_name,
        )

    def clean(self):
        self.filepath = ""
        self.curve_depth = None
        self.curve_name = None
        self.filename = None
        self.db = {}

    def load_metadata(self):
        extension = Path(self.filepath).suffix.lower()
        self.filename = slicer.mrmlScene.GetUniqueNameByString(Path(self.filepath).stem)
        self.curve_name = self.filename

        if extension == ".pdf":
            columns = [
                "Profundidade de Sondador (m)",
                "Diâmetro Nominal (pol)",
                "Comprimento (cm)",
                "Massa (g)",
                "Permeabilidade Absoluta (mD)",
                "Porosidade Efetiva (%)",
                "Massa Específica de Sólidos (g/cm³)",
            ]
            df = parse_pdf(self.filepath, pages="3-end", columns=columns, remove_extra=True)
        elif extension == ".csv":
            try:
                df = read_csv(self.filepath)

                firstColumnUniqueValuesCount = df.iloc[1:10, 0].drop_duplicates().count()
                if firstColumnUniqueValuesCount == 1:
                    raise LoaderError("This CSV format is not supported.")
            except ParserError as pe:
                logging.warning("Tried managed read csv but failed doing so. Cause: " + repr(pe))

        if not self.checkImageData(df):
            depthUnit = "m"
            secondRowHasUnits = self._isLength(df.iloc()[0, 0])
            if secondRowHasUnits:
                units = df.iloc()[0]
                df = df.drop(0)
                df = df.reset_index(drop=True)
                depthUnit = units[0]
            else:
                pattern = re.compile(r"\((.+)\)")
                match = pattern.search(df.columns[0])
                if match and self._isLength(match.group(1)):
                    depthUnit = match.group(1)
            self.curve_depth = df.iloc[:, 0].to_numpy(dtype="float32") * conversion_factor_to_millimeters(depthUnit)

            for i, column in enumerate(df):
                if i == 0:  # assume depth is always the first column
                    continue

                data = df[column].to_numpy(dtype="float32")
                data[data < 0.001] = 0.001

                if secondRowHasUnits:
                    unit = units[i]
                else:
                    match = pattern.search(column)
                    unit = match.group(1) if match else ""

                fake_mnemonic = f"Column {i+1}"

                self.db[fake_mnemonic] = (
                    ChannelMetadata(fake_mnemonic, column, unit, "", self.filename, "", "", False),
                    data,
                )
                self.loaded_as_image = False
        else:
            self.curve_depth = df.iloc[:, 0].to_numpy() * conversion_factor_to_millimeters("m")

            fake_mnemonic = f"Image"
            self.db[fake_mnemonic] = (
                ChannelMetadata(
                    fake_mnemonic, df.columns[1].replace("[0]", ""), "", "", self.filename, "", False, False
                ),
                df.iloc[:, 1:].to_numpy(),
            )

            self.loaded_as_image = True

        return self.filename, [self.db[k][0] for k in self.db]

    def load_data(self, file_path, mnemonic_and_files=None):
        for m in mnemonic_and_files:
            md, data = self.db[m.mnemonic]
            data = np.copy(data)

            if not self.loaded_as_image:
                yield (
                    self.filename,
                    self.curve_name,
                    DEPTH_LABEL,
                    "",
                    self.curve_depth,
                    None,
                    True,
                    False,
                    False,
                    "mm",
                )

            yield (
                self.filename,
                self.curve_name,
                md.name,
                "",
                self.curve_depth,
                data,
                False,
                m.is_labelmap,
                m.is_table,
                md.unit,
            )

    def checkImageData(self, df):
        # find mnemonic with enclosed number
        # e.g. UBI_AMP[0] or UBI_AMP [dB][0]
        pattern = re.compile(r"(.+)[\[|(|{]([0-9]+)[\]|)|}]")
        imagedict = {}
        for i, column in enumerate(df):
            result = pattern.search(column)
            if result is None:
                continue
            if len(result.groups()) == 2:
                if not result.group(1) in imagedict.keys():
                    imagedict[result.group(1)] = list()
                imagedict[result.group(1)].append(int(result.group(2)))

        # if no images were found return 0
        if len(imagedict) == 0:
            return False

        # if the found images are evenly spaced
        foundValidImage = False
        for _, l in imagedict.items():
            normal = np.linspace(l[0], l[-1], len(l))
            if len(l) > 1 and np.all(l == normal):
                foundValidImage = True
        return foundValidImage


class LoaderError(RuntimeError):
    pass


def checkMnemonicChanged(curr_mnemonic, last_curve_mnemonic):
    stacked_curves_pattern = re.compile(r"(.+)[\[|(|{]([0-9]+)[\]|)|}]")
    mnemo_search = stacked_curves_pattern.search(curr_mnemonic)
    mnemonic = ""
    is_same_mnemonic = False

    if mnemo_search is None:
        mnemonic = curr_mnemonic
    else:
        mnemonic = mnemo_search.group(
            len(mnemo_search.groups()) - 1
        )  # Same as in check_image_data: find mnemonic with enclosed number, e.g. UBI_AMP[0] or UBI_AMP [dB][0]

    if mnemonic == last_curve_mnemonic:
        is_same_mnemonic = True
    else:
        last_curve_mnemonic = mnemonic

    return last_curve_mnemonic, is_same_mnemonic


def check_as_table(channel_name):
    for name in CURVES_NAME:
        if name in channel_name:
            return True
    return False


def load_volumes_with_depth(curves, stepCallback, appFolder=None, nullValue=None, well_diameter_mm=310):
    loaded_nodes_ids = []
    loaded_nodes = []
    depth_id = None
    for i, curve in enumerate(curves):
        node, itemID = add_volume(
            *curve,
            app_folder=appFolder,
            null_value=nullValue,
            well_diameter_mm=well_diameter_mm,
        )
        if itemID:
            loaded_nodes_ids.append(itemID)
        if node is not None:
            loaded_nodes.append(node)
            if curve[6]:
                depth_id = node.GetID()
    if depth_id is not None:
        for node in loaded_nodes:
            node.SetAttribute("DEPTH_NODE", str(depth_id))
    return loaded_nodes_ids


def load_volumes_as_table(curves, stepCallback=None, appFolder=None, nullValue=None, name="curves", well_name=""):
    """Load the selected curves' data as a table node

    Args:
        curves (list[tuple]): A list containing a tuple with the curve's information
        stepCallback (function): A callback for each iteration step. Not implemented.
        appFolder (str, optional): The curve's file folder name. Defaults to None.
        nullValue (double, optional): The null value related to the curve's data. Defaults to None.

    Returns:
        list: A list of subject hierarchy item ID. Keep to maintain compatibility,
              but its not used by the tables node.
    """
    curves_data = dict()
    units = list()
    for i, curve in enumerate(curves):
        if i == 0:
            root_folder = curve[0]
            folder = curve[1]
            frame = curve[3]
            units.append(str(curve[9]))
        curve_name = curve[2]

        if curve_name == DEPTH_LABEL:
            curve_data = curve[4]
        else:
            curve_data = curve[5]
            units.append(str(curve[9]))

        curves_data[curve_name] = curve_data

    create_depth_curves_table(
        curves=curves_data,
        root_folder=root_folder,
        folder=folder,
        frame=frame,
        app_folder=appFolder,
        name=name,
        null_value=nullValue,
        units=units,
        well_name=well_name,
    )

    return []


def add_volume(
    top_folder,
    folder,
    name,
    frame,
    domain,
    image,
    is_depth,
    is_labelmap,
    is_table,
    units="",
    app_folder=None,
    null_value=None,
    well_diameter_mm=310,
    well_name=None,
):
    if is_depth:
        image = domain
        name = DEPTH_LABEL

    if domain[0] > domain[-1]:
        domain[:] = np.flipud(domain)
        image[:] = np.flipud(image)

    total_circumference_millimeters = np.pi * well_diameter_mm
    vertical_spacing_millimeters = (domain[-1] - domain[0]) / image.shape[0]

    horizontal_spacing_millimeters = 0

    if image.ndim >= 2 and not is_table:
        # 2D / 3D data are added as scalar volume or label map
        horizontal_spacing_millimeters = total_circumference_millimeters / image.shape[1]

        image = image.reshape(image.shape[0], 1, image.shape[1])

        read_volume, item_id = add_volume_from_data(
            top_folder,
            folder,
            name,
            frame,
            image,
            is_labelmap,
            units,
            app_folder,
            null_value,
            well_name,
        )
        if read_volume:
            read_volume.SetSpacing(horizontal_spacing_millimeters, 0.48, vertical_spacing_millimeters)
            read_volume.SetOrigin(
                total_circumference_millimeters / 2,
                0,
                -int(domain[0]),
            )
            read_volume.SetIJKToRASDirections(-1, 0, 0, 0, -1, 0, 0, 0, -1)

            if not is_labelmap:
                calculateWindowLevelMinMax(read_volume)

        return read_volume, item_id
    else:
        # 1D/2D data is added as a table
        # first column is related to the depth curve and
        # the others are related to the selected log curve
        curve_data = {DEPTH_LABEL: domain, name: image}
        if image.ndim >= 2 and is_table:
            table_node, table_item_id = create_depth_curves_table_from_image(
                curves=curve_data,
                root_folder=top_folder,
                folder=folder,
                frame=frame,
                units=units,
                app_folder=app_folder,
                name=name,
                null_value=null_value,
                well_name=well_name,
            )
        else:  # 1D (whether is_table is True or False)
            table_node, table_item_id = create_depth_curves_table(
                curves=curve_data,
                root_folder=top_folder,
                folder=folder,
                frame=frame,
                units=units,
                app_folder=app_folder,
                name=name,
                null_value=null_value,
                well_name=well_name,
            )
        return table_node, None


def calculateWindowLevelMinMax(volume):
    imageData = slicer.util.arrayFromVolume(volume)
    imageData = imageData[imageData != getVolumeNullValue(volume)]
    distributionFilter = DistributionFilter(imageData)
    if volume.GetDisplayNode() is None:
        volume.CreateDefaultDisplayNodes()
    displayNode = volume.GetDisplayNode()
    displayNode.AutoWindowLevelOff()
    default_num_of_stds = 2
    displayNode.SetAttribute("num_of_stds", str(default_num_of_stds))
    displayNode.SetWindowLevelMinMax(*distributionFilter.get_filter_min_max(default_num_of_stds))


def create_subject_hierarchy_folder(root_folder, folder, frame, app_folder):
    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)

    if app_folder is not None:
        app_folder_id = subject_hierarchy.GetItemByName(app_folder)
        if app_folder_id == 0:
            top_level_id = subject_hierarchy.GetSceneItemID()
            app_folder_id = subject_hierarchy.CreateFolderItem(top_level_id, app_folder)
        subject_hierarchy.SetItemAttribute(app_folder_id, SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)
    else:
        app_folder_id = subject_hierarchy.GetSceneItemID()

    root_folder_id = subject_hierarchy.GetItemByName(root_folder)
    if root_folder_id == 0:
        root_folder_id = subject_hierarchy.CreateFolderItem(app_folder_id, root_folder)

    subject_hierarchy.SetItemAttribute(root_folder_id, SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)

    return root_folder_id


def verify_repeated_file(name, root_id, folder, frame):
    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    children = vtk.vtkIdList()
    subject_hierarchy.GetItemChildren(root_id, children)
    for i in range(children.GetNumberOfIds()):
        if subject_hierarchy.GetItemName(children.GetId(i)) == name:
            if (
                subject_hierarchy.GetItemAttribute(children.GetId(i), FRAME_TAG) == frame
                and subject_hierarchy.GetItemAttribute(children.GetId(i), LOGICAL_FILE_TAG) == folder
            ):
                return True
    return False


def get_valid_folder_volume_name(name, frame_id):
    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    volume_id = subject_hierarchy.GetItemChildWithName(frame_id, name)
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    if volume_id != 0:
        return None
    return name


def add_volume_from_data(
    root_folder,
    folder,
    name,
    frame,
    data,
    is_labelmap,
    units="",
    app_folder=None,
    nullValue=None,
    well_name=None,
):
    root_id = create_subject_hierarchy_folder(root_folder, folder, frame, app_folder)
    if well_name:
        name = f"{well_name}_{name}"

    if is_labelmap:
        name = f"{name}_LabelMap"

    if is_labelmap:
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLLabelMapVolumeNode")
        data = helpers.numberArrayToLabelArray(data)
        for value in nullValue:
            data[np.where(data == value)] = 0
    else:
        if nullValue is not None:
            nullValue = handle_null_values(data, nullValue)
        volume_node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode")

    name = name.strip()  # remove trailing spaces
    volume_node.SetName(slicer.mrmlScene.GenerateUniqueName(name))
    volume_node.SetAttribute(SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)
    volume_node.SetAttribute(NULL_VALUE_TAG, str(nullValue))  # default set at handle_null_values
    volume_node.SetAttribute(WELL_NAME_TAG, well_name)

    volume_units = units if units != "" else None
    volume_node.SetAttribute(UNITS_TAG, units)
    volume_node.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
    codedUnit = slicer.vtkCodedEntry()
    codedUnit.SetCodeValue(units)
    volume_node.SetVoxelValueUnits(codedUnit)

    # updateVolumeFromArray does not support long long type
    if data.dtype == np.longlong:
        data = data.astype(int)

    slicer.util.updateVolumeFromArray(volume_node, data)

    if is_labelmap:
        volume_node.CreateDefaultDisplayNodes()
        displayNode = volume_node.GetDisplayNode()
        colorMapNode = helpers.labelArrayToColorNode(data, name + "_ColorMap")
        displayNode.SetAndObserveColorNodeID(colorMapNode.GetID())
        colorMapNode.NamesInitialisedOn()

    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    volume_item_id = subject_hierarchy.CreateItem(root_id, volume_node)
    subject_hierarchy.SetItemAttribute(volume_item_id, SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)
    subject_hierarchy.SetItemAttribute(volume_item_id, LOGICAL_FILE_TAG, folder or "")
    subject_hierarchy.SetItemAttribute(volume_item_id, FRAME_TAG, frame or "")

    return volume_node, volume_item_id


def get_loader(file_path, null_values=""):
    ext = Path(file_path).suffix.lower()
    if ext == ".las":
        return LASLoader(file_path, null_values)
    if ext == ".dlis":
        return DLISLoader(file_path, null_values)
    if ext == ".csv" or ext == ".pdf":
        return CSVLoader(file_path, null_values)
    raise NotImplementedError(f'Handler for "{ext}" not implemented.')


def load_volumes(curves, stepCallback, appFolder=None, nullValue=None, well_diameter_mm=310, well_name=None):
    loaded_nodes_ids = []
    for i, curve in enumerate(curves):
        _, itemID = add_volume(
            *curve, app_folder=appFolder, null_value=nullValue, well_diameter_mm=well_diameter_mm, well_name=well_name
        )
        if itemID:
            loaded_nodes_ids.append(itemID)
        stepCallback(curve[2], i + 1)
    return loaded_nodes_ids


def conversion_factor_to_millimeters(unitStr):
    parts = unitStr.strip().split(" ")
    unit = parts[-1].lower()  # to avoid wrong unit recognition by pint (e.g.: M stands as Molar, not meters)
    fraction = float(parts[0]) if len(parts) == 2 else 1
    baseQuantity = ureg.Quantity(1, unit)

    if not baseQuantity.is_compatible_with(ureg.millimeter):
        raise ImageLogImportError("Depth unit is not a distance unit.")

    return fraction * baseQuantity.m_as(ureg.millimeter)


def blank_fn(*args, **kwargs):
    pass


def create_depth_curves_table(
    curves: dict,
    root_folder,
    folder,
    frame,
    units,
    app_folder,
    name: str = "curves",
    null_value=None,
    well_name="",
):
    """[summary]

    Args:
        curves (list[tuple]): A list containing a tuple with the curve's information
        root_folder ([type]): the subject hierarchy item's root folder name.
        folder ([type]): the subject hierarchy item's folder name.
        frame ([type]): the frame name that contains the curve data.
        units (str): values' units (such as dB)
        app_folder (str): The curve's file folder name
        name (str, optional): The curve's table node name. Defaults to "curves".
        null_value (double, optional): The null value related to the curve's data. Defaults to None.
    Raises:
        RuntimeError: Raises if curve data is invalid.

    Returns:
        vtkMRMLTableNode: The table node object.
        vtkIdType: The subject hierarchy item's ID.
    """
    if len(curves.keys()) <= 1 or DEPTH_LABEL not in curves.keys():
        raise RuntimeError("Unable to create curve table. The input data has insufficent selected curves")

    # Create data frame based on the curves data
    df = pd.DataFrame.from_dict(curves)
    df.columns = list(curves.keys())

    if null_value is not None:
        df = df.replace(null_value, np.nan)

    # Assert data frame has DEPTH as first column
    depth_column_index = df.columns.get_loc(DEPTH_LABEL)

    if depth_column_index != 0:
        depth_column = df.pop(DEPTH_LABEL)
        df.insert(0, DEPTH_LABEL, depth_column)  # Is in-place

    # Sort data by depth descending order
    df.sort_values(by=DEPTH_LABEL, ascending=False)

    # Create table node and Insert data frame to table node
    root_id = create_subject_hierarchy_folder(root_folder, folder, frame, app_folder)
    if verify_repeated_file(name, root_id, folder, frame):
        return None, None
    table_node = dataFrameToTableNode(dataFrame=df)
    table_node.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
    table_node.SetAttribute(WELL_NAME_TAG, well_name)

    data_units = units if units != "" else None
    # The first column should hold the depth (or time, if supported), and all others should have the same unit
    if isinstance(units, (list, np.ndarray)):
        data_units = units[1] if units[1] != "" else None
    else:
        data_units = units if units != "" else None
    table_node.SetAttribute(UNITS_TAG, data_units)

    table_node.SetName(name)

    if isinstance(units, (list, np.ndarray)):
        for collumnTitle, unit in zip(df.columns, units):
            table_node.SetColumnUnitLabel(collumnTitle, unit)
    else:  # if units is a single string, we have 2 columns: depth and the log data
        table_node.SetColumnUnitLabel(
            df.columns[0], "mm"
        )  # NOTE - We expect that mm is enforced when loading the domain data
        table_node.SetColumnUnitLabel(df.columns[1], units)

    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    volume_item_id = subject_hierarchy.CreateItem(root_id, table_node)
    subject_hierarchy.SetItemAttribute(volume_item_id, SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)
    subject_hierarchy.SetItemAttribute(volume_item_id, LOGICAL_FILE_TAG, folder or "")
    subject_hierarchy.SetItemAttribute(volume_item_id, FRAME_TAG, frame or "")
    subject_hierarchy.SetItemAttribute(volume_item_id, NULL_VALUE_TAG, str(null_value))

    return table_node, volume_item_id


def create_depth_curves_table_from_image(
    curves: dict, root_folder, folder, frame, units, app_folder, name: str = "curves", null_value=None, well_name=""
):
    """[summary]

    Args:
        curves (list[tuple]): A list containing a tuple with the curve's information
        root_folder ([type]): the subject hierarchy item's root folder name.
        folder ([type]): the subject hierarchy item's folder name.
        frame ([type]): the frame name that contains the curve data.
        units (str): values' units (such as dB)
        app_folder (str): The curve's file folder name
        name (str, optional): The curve's table node name. Defaults to "curves".
        null_value (double, optional): The null value related to the curve's data. Defaults to None.
    Raises:
        RuntimeError: Raises if curve data is invalid.

    Returns:
        vtkMRMLTableNode: The table node object.
        vtkIdType: The subject hierarchy item's ID.
    """
    if len(curves.keys()) <= 1 or DEPTH_LABEL not in curves.keys():
        raise RuntimeError("Unable to create curve table. The input data has insufficent selected curves")

    # Create data frame based on the curves data
    df = pd.DataFrame(curves[name].astype(float))

    if null_value is not None:
        df = df.replace(null_value, np.nan)

    # Assert data frame has DEPTH as first column
    if curves[DEPTH_LABEL].size > 0:
        df.insert(0, DEPTH_LABEL, curves[DEPTH_LABEL].astype(float))  # Is in-place

    # Create table node and Insert data frame to table node
    root_id = create_subject_hierarchy_folder(root_folder, folder, frame, app_folder)
    if verify_repeated_file(name, root_id, folder, frame):
        return None, None
    table_node = dataFrameToTableNode(dataFrame=df)
    table_node.SetAttribute(ImageLogDataSelectable.name(), ImageLogDataSelectable.TRUE.value)
    table_node.SetAttribute(WELL_NAME_TAG, well_name)

    data_units = units if units != "" else None
    table_node.SetAttribute(UNITS_TAG, data_units)

    table_node.SetAttribute(TableType.name(), TableType.HISTOGRAM_IN_DEPTH.value)
    table_node.SetAttribute(TableDataTypeAttribute.name(), TableDataTypeAttribute.IMAGE_2D.value)
    table_node.SetAttribute(TableDataOrientation.name(), TableDataOrientation.ROW.value)
    table_node.SetName(name)
    table_node.SetUseFirstColumnAsRowHeader(True)
    table_node.SetUseColumnNameAsColumnHeader(True)

    subject_hierarchy = slicer.vtkMRMLSubjectHierarchyNode.GetSubjectHierarchyNode(slicer.mrmlScene)
    volume_item_id = subject_hierarchy.CreateItem(root_id, table_node)
    subject_hierarchy.SetItemAttribute(volume_item_id, SCALAR_VOLUME_TYPE, WELL_PROFILE_TAG)
    subject_hierarchy.SetItemAttribute(volume_item_id, LOGICAL_FILE_TAG, folder or "")
    subject_hierarchy.SetItemAttribute(volume_item_id, FRAME_TAG, frame or "")
    subject_hierarchy.SetItemAttribute(volume_item_id, NULL_VALUE_TAG, str(null_value))

    return table_node, volume_item_id


class ImageLogImportError(RuntimeError):
    pass
