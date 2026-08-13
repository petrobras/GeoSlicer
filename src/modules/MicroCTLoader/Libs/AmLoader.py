import logging
import re
import traceback
from pathlib import Path

import ctk
import numpy as np
import qt
import slicer
import vtk

from ltrace.slicer import helpers, loader
from ltrace.slicer.microct import ROOT_DATASET_DIRECTORY_NAME
from ltrace.utils.ProgressBarProc import ProgressBarProc


_AM_DTYPE_MAP = {
    "byte": np.int8,
    "ubyte": np.uint8,
    "short": np.int16,
    "ushort": np.uint16,
    "int": np.int32,
    "uint": np.uint32,
    "float": np.float32,
    "double": np.float64,
}

_UNIT_TO_MM = {
    "m": 1e3,
    "cm": 10.0,
    "mm": 1.0,
    "um": 1e-3,
    "μm": 1e-3,
    "nm": 1e-6,
}


def parse_am_header(file_path):
    header_lines = []
    data_offset = None
    with open(file_path, "rb") as fh:
        while True:
            line = fh.readline()
            if not line:
                raise ValueError("Could not find a '@1' data section marker in the file")
            stripped = line.lstrip()
            if stripped.startswith(b"@1") and (len(stripped) == 2 or not stripped[2:3].isdigit()):
                data_offset = fh.tell()
                break
            header_lines.append(line)

    raw_header = b"".join(header_lines)

    first_nl = raw_header.find(b"\n")
    first_line = raw_header[:first_nl].decode("ascii", errors="replace").strip()

    if "BINARY" not in first_line:
        raise ValueError("Only binary .am files are supported (ASCII variant not implemented)")

    endian = "little" if "LITTLE-ENDIAN" in first_line else "big"

    header_text = raw_header.decode("ascii", errors="replace")
    header_flat = re.sub(r"\s+", " ", header_text)

    try:
        # ------------------------------------------------------------------ #
        # Parse dimensions: "define Lattice nx ny nz"
        # ------------------------------------------------------------------ #
        dims_m = re.search(r"define\s+Lattice\s+(\d+)\s+(\d+)\s+(\d+)", header_flat)
        if dims_m is None:
            raise ValueError("Could not find 'define Lattice nx ny nz' in header")
        nx, ny, nz = int(dims_m.group(1)), int(dims_m.group(2)), int(dims_m.group(3))

        # ------------------------------------------------------------------ #
        # Parse bounding box: "BoundingBox xmin xmax ymin ymax zmin zmax"
        # ------------------------------------------------------------------ #
        num_pat = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
        bbox_m = re.search(
            r"BoundingBox\s+" + r"\s+".join([num_pat] * 6),
            header_flat,
        )
        bbox = tuple(float(bbox_m.group(i)) for i in range(1, 7)) if bbox_m else None

        # ------------------------------------------------------------------ #
        # Parse coordinate unit: Units { Coordinates "m" }
        # ------------------------------------------------------------------ #
        unit_m = re.search(r'Coordinates\s+"(\w+)"', header_text)
        coord_unit = unit_m.group(1) if unit_m else "m"

        # ------------------------------------------------------------------ #
        # Parse data type: "Lattice { dtype FieldType } @1"
        # ------------------------------------------------------------------ #
        dtype_m = re.search(r"Lattice\s*\{\s*(\w+)\s+\w+\s*\}", header_flat)
        if dtype_m is None:
            raise ValueError("Could not find data-type declaration in header (expected 'Lattice { type Field }')")

        type_str = dtype_m.group(1).lower()
        if type_str not in _AM_DTYPE_MAP:
            raise ValueError(f"Unsupported data type '{type_str}'. " f"Supported types: {list(_AM_DTYPE_MAP.keys())}")

        dtype = np.dtype(_AM_DTYPE_MAP[type_str]).newbyteorder(endian)
    except Exception as e:
        raise ValueError(f"Not a valid .am file") from e

    return {
        "dims": (nx, ny, nz),
        "dtype": dtype,
        "data_type_str": type_str,
        "bounding_box": bbox,
        "coord_unit": coord_unit,
        "data_offset": data_offset,
        "endian": endian,
    }


class AmLoaderLogic:
    def load(self, filePath, volumeName=None, centerVolume=False, loadAsLabelmap=False):
        """Read an .am file and return a new vtkMRML(LabelMap)VolumeNode."""
        info = parse_am_header(filePath)
        nx, ny, nz = info["dims"]
        dtype = info["dtype"]
        dataOffset = info["data_offset"]
        boundingBox = info["bounding_box"]
        coordUnit = info["coord_unit"]

        count = nx * ny * nz
        array = np.fromfile(filePath, dtype=dtype, offset=dataOffset, count=count)
        if array.size != count:
            raise RuntimeError(
                f"Expected {count} voxels but read {array.size}. "
                "The file may be truncated or use a compressed encoding."
            )
        array = array.reshape((nz, ny, nx))

        scale = _UNIT_TO_MM.get(coordUnit, 1000.0)  # fallback: metres
        if boundingBox is not None:
            xmin, xmax, ymin, ymax, zmin, zmax = boundingBox
            spacingX = (xmax - xmin) / (nx - 1) * scale if nx > 1 else 1.0  # mm, center-to-center
            spacingY = (ymax - ymin) / (ny - 1) * scale if ny > 1 else 1.0
            spacingZ = (zmax - zmin) / (nz - 1) * scale if nz > 1 else 1.0
            originX = xmin * scale
            originY = ymin * scale
            originZ = zmin * scale
        else:
            spacingX = spacingY = spacingZ = 1.0  # 1 mm default
            originX = originY = originZ = 0.0

        if volumeName is None:
            volumeName = slicer.mrmlScene.GenerateUniqueName(Path(filePath).stem)

        if loadAsLabelmap:
            nodeClass = "vtkMRMLLabelMapVolumeNode"
        else:
            nodeClass = "vtkMRMLScalarVolumeNode"

        node = slicer.mrmlScene.AddNewNodeByClass(nodeClass, volumeName)
        slicer.util.updateVolumeFromArray(node, array)

        ijkToRas = vtk.vtkMatrix4x4()
        ijkToRas.SetElement(0, 0, spacingX)
        ijkToRas.SetElement(1, 1, spacingY)
        ijkToRas.SetElement(2, 2, spacingZ)
        ijkToRas.SetElement(0, 3, originX)
        ijkToRas.SetElement(1, 3, originY)
        ijkToRas.SetElement(2, 3, originZ)
        node.SetIJKToRASMatrix(ijkToRas)
        node.Modified()

        node.CreateDefaultDisplayNodes()
        displayNode = node.GetDisplayNode()
        if loadAsLabelmap:
            colorNode = helpers.labelArrayToColorNode(array, f"{volumeName}_ColorMap")
            displayNode.SetAndObserveColorNodeID(colorNode.GetID())
        elif displayNode and hasattr(displayNode, "AutoWindowLevelOff"):
            displayNode.AutoWindowLevelOff()
            displayNode.AutoWindowLevelOn()

        if centerVolume:
            added = node.AddCenteringTransform()
            if added:
                transformId = node.GetTransformNodeID()
                node.HardenTransform()
                centering = slicer.mrmlScene.GetNodeByID(transformId) if transformId else None
                if centering is not None:
                    slicer.mrmlScene.RemoveNode(centering)

        loader.configureInitialNodeMetadata(ROOT_DATASET_DIRECTORY_NAME, volumeName, node)
        slicer.util.resetSliceViews()
        return node


class AmLoaderWidget(qt.QFrame):
    """Shows parsed .am header info and loads the volume on demand."""

    def __init__(self, mctLoader):
        super().__init__(None)
        self._mctLoader = mctLoader
        self._filePath = None
        self._info = None
        self.logic = AmLoaderLogic()
        self._setup()

    def _setup(self):
        mainLayout = qt.QVBoxLayout(self)
        mainLayout.setContentsMargins(0, 0, 0, 0)

        infoSection = ctk.ctkCollapsibleButton()
        infoSection.setText("Parsed header info")
        infoSection.collapsed = False
        infoLayout = qt.QFormLayout(infoSection)
        infoLayout.setLabelAlignment(qt.Qt.AlignRight)

        self._dimsLabel = qt.QLabel("—")
        self._typeLabel = qt.QLabel("—")
        self._spacingLabel = qt.QLabel("—")
        self._bboxLabel = qt.QLabel("—")
        self._unitLabel = qt.QLabel("—")

        infoLayout.addRow("Dimensions (x, y, z):", self._dimsLabel)
        infoLayout.addRow("Data type:", self._typeLabel)
        infoLayout.addRow("Voxel size (μm):", self._spacingLabel)
        infoLayout.addRow("Bounding box:", self._bboxLabel)
        infoLayout.addRow("Coordinate unit:", self._unitLabel)

        mainLayout.addWidget(infoSection)

        outputSection = ctk.ctkCollapsibleButton()
        outputSection.setText("Output")
        outputSection.collapsed = False
        outputLayout = qt.QFormLayout(outputSection)
        outputLayout.setLabelAlignment(qt.Qt.AlignRight)

        self._centerCheckbox = qt.QCheckBox("Center volume")
        self._centerCheckbox.setChecked(False)
        self._labelmapCheckbox = qt.QCheckBox("Load as Labelmap")

        self._nameEdit = qt.QLineEdit()
        outputLayout.addRow("Output name:", self._nameEdit)
        outputLayout.addRow("", self._centerCheckbox)
        outputLayout.addRow("", self._labelmapCheckbox)
        outputLayout.addRow(" ", None)

        self._loadButton = qt.QPushButton("Load")
        self._loadButton.setFixedHeight(40)
        self._loadButton.setEnabled(False)
        outputLayout.addRow(self._loadButton)

        self._errorLabel = qt.QLabel("")
        self._errorLabel.setStyleSheet("color: red; font-size: 13px; font-weight: bold")
        outputLayout.addRow(self._errorLabel)

        mainLayout.addWidget(outputSection)

        self._loadButton.clicked.connect(self._onLoadClicked)

    def onCurrentPathChanged(self, path):
        self._filePath = str(path)
        self._errorLabel.setText("")
        try:
            self._info = parse_am_header(self._filePath)
        except Exception as exc:
            logging.error(f"AmLoader: failed to parse header: {exc}\n{traceback.format_exc()}")
            self._info = None
            self._errorLabel.setText(f"Header parse error: {exc}")
            self._loadButton.setEnabled(False)
            self._clearInfoLabels()
            return

        self._populateInfoLabels()
        defaultName = slicer.mrmlScene.GenerateUniqueName(Path(self._filePath).stem)
        self._nameEdit.setText(defaultName)
        self._loadButton.setEnabled(True)

    def _clearInfoLabels(self):
        for label in (self._dimsLabel, self._typeLabel, self._spacingLabel, self._bboxLabel, self._unitLabel):
            label.setText("—")

    def _populateInfoLabels(self):
        info = self._info
        nx, ny, nz = info["dims"]
        self._dimsLabel.setText(f"{nx} × {ny} × {nz}")
        self._typeLabel.setText(info["data_type_str"])
        self._unitLabel.setText(info["coord_unit"])

        boundingBox = info["bounding_box"]
        coordUnit = info["coord_unit"]
        scale = _UNIT_TO_MM.get(coordUnit, 1000.0)
        if boundingBox is not None:
            xmin, xmax, ymin, ymax, zmin, zmax = boundingBox
            sx = (xmax - xmin) / (nx - 1) * scale * 1000 if nx > 1 else 1000.0  # mm → μm for display
            sy = (ymax - ymin) / (ny - 1) * scale * 1000 if ny > 1 else 1000.0
            sz = (zmax - zmin) / (nz - 1) * scale * 1000 if nz > 1 else 1000.0
            self._spacingLabel.setText(f"{sx:.3f}, {sy:.3f}, {sz:.3f}")
            self._bboxLabel.setText(f"[{xmin:.4g}, {xmax:.4g}] × [{ymin:.4g}, {ymax:.4g}] × [{zmin:.4g}, {zmax:.4g}]")
        else:
            self._spacingLabel.setText("(bounding box not found — defaulting to 1 mm)")
            self._bboxLabel.setText("—")

    def _onLoadClicked(self):
        if self._filePath is None or self._info is None:
            return

        with ProgressBarProc() as pb:
            pb.nextStep(0, "Loading .am file...")
            try:
                node = self.logic.load(
                    self._filePath,
                    volumeName=self._nameEdit.text or None,
                    centerVolume=self._centerCheckbox.isChecked(),
                    loadAsLabelmap=self._labelmapCheckbox.isChecked(),
                )
                self._errorLabel.setText("")
                pb.nextStep(80, "Applying post-processing...")
                processing = self._mctLoader.checkProcessingSettings()
                self._mctLoader.postProcessing(
                    node=node,
                    willCrop=processing.get("willCrop", False),
                )
                pb.nextStep(100, "Done")
                slicer.util.setSliceViewerLayers(background=node, fit=True)
            except Exception as exc:
                logging.error(f"AmLoader: load failed: {exc}\n{traceback.format_exc()}")
                self._errorLabel.setText(f"Load error: {exc}")
