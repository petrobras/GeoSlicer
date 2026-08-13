import os
import qt
import ctk
import slicer
import logging
from pathlib import Path

from ltrace.slicer import ui, helpers, widgets
from ltrace.slicer_utils import LTracePlugin, LTracePluginWidget, LTracePluginLogic, getResourcePath
from ltrace.slicer.helpers import LazyLoad2
from ltrace.slicer.application_observables import ApplicationObservables
from ltrace.pore_networks.report import ReportForm, ReportLogic, StreamlitServer

try:
    from Test.PoreNetworkWorkflowTest import PoreNetworkWorkflowTest
except ImportError:
    PoreNetworkWorkflowTest = None


class PoreNetworkWorkflow(LTracePlugin):
    SETTING_KEY = "PoreNetworkWorkflow"
    MODULE_DIR = Path(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Pore Network Workflow"
        self.parent.categories = ["MicroCT", "Pore Network"]
        self.parent.contributors = ["LTrace Geophysics Team"]
        self.parent.dependencies = []
        self.parent.helpText = "Workflow for Pore Network Modeling and Reporting."

    @classmethod
    def readme_path(cls):
        return str(cls.MODULE_DIR / "README.md")


class PoreNetworkWorkflowWidget(LTracePluginWidget):
    def __init__(self, parent):
        LTracePluginWidget.__init__(self, parent)
        self.logic = None
        self.server = None
        self.currentMode = widgets.SingleShotInputWidget.MODE_NAME
        self.simOptions = None  # Mock for StreamlitServer

    def setup(self):
        LTracePluginWidget.setup(self)

        self.modeSelectors = {}
        self.modeWidgets = {}

        # Mock simOptions for StreamlitServer compatibility
        self.simOptions = qt.QComboBox(self.parent)
        self.simOptions.addItem("PNM Complete Workflow", "pnm")
        self.simOptions.setCurrentIndex(0)
        self.simOptions.hide()

        # 1. Inputs Section
        self.layout.addWidget(self._setupInputsSection())

        # 2. Configuration Section (ReportForm)
        self.layout.addWidget(self._setupConfigSection())

        # 3. Output Section (Server controls + Apply button)
        self.layout.addWidget(self._setupOutputSection())

        # Connect signals
        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME].onReferenceSelectedSignal.connect(
            self._onReferenceSelected
        )

        # Ensure dependencies are available in sys.path
        import slicer
        import sys
        from pathlib import Path

        dependencies = [
            "CustomResampleScalarVolume",
            "PoreNetworkSimulation",
            "PoreNetworkExtractor",
            "PoreNetworkProduction",
        ]

        for dep in dependencies:
            if dep in slicer.modules.AppContextInstance.modules.availableModules:
                mod_info = slicer.modules.AppContextInstance.modules.availableModules[dep]
                mod_path = Path(mod_info.searchPath).as_posix()
                if mod_path not in sys.path:
                    sys.path.append(mod_path)

        # Initialize logic
        try:
            if ReportLogic is not None and ReportLogic.ReportLogic is not None:
                # Assuming ReportLogic takes (parent, progressBar)
                # We don't have a progress bar passed yet, let's create one or pass None
                self.logic = ReportLogic.ReportLogic(self.parent, None)
            else:
                self.logic = None
                slicer.util.errorDisplay("Failed to load ReportLogic. Please check logs.")
        except Exception as e:
            import traceback

            traceback.print_exc()
            self.logic = None
            slicer.util.errorDisplay(f"Error initializing ReportLogic: {e}")

        self.layout.addStretch(1)

        self.layout.addStretch(1)

    def cleanup(self):
        if self.modeWidgets.get(widgets.BatchInputWidget.MODE_NAME):
            self.modeWidgets[widgets.BatchInputWidget.MODE_NAME].onDirSelected = None

        if StreamlitServer.StreamlitServer is not None:
            ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)
        super().cleanup()

    def _setupInputsSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Inputs"
        layout = qt.QVBoxLayout(widget)

        optionsLayout = qt.QHBoxLayout()
        optionsLayout.setAlignment(qt.Qt.AlignLeft)

        self.optionsStack = qt.QStackedWidget()

        # Mode switching radio buttons
        btn1 = qt.QRadioButton(widgets.SingleShotInputWidget.MODE_NAME)
        btn1.objectName = "Single Shot Mode Radio Button"
        btn1.setChecked(True)
        self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME] = btn1
        optionsLayout.addWidget(btn1)
        btn1.toggled.connect(self._onModeClicked)

        btn2 = qt.QRadioButton(widgets.BatchInputWidget.MODE_NAME)
        btn2.objectName = "Batch Mode Radio Button"
        self.modeSelectors[widgets.BatchInputWidget.MODE_NAME] = btn2
        optionsLayout.addWidget(btn2)
        btn2.toggled.connect(self._onModeClicked)

        # Single Shot Widget
        panel1 = widgets.SingleShotInputWidget(dimensionsUnits={"px": True, "mm": True})

        # Configure for PNM: hide main input, show reference input as the primary segmentation input
        panel1.mainLabel.visible = False
        panel1.mainInput.visible = False
        panel1.soiLabel.visible = False
        panel1.soiInput.visible = False
        panel1.referenceInput.enabled = True
        panel1.referenceInput.visible = True
        panel1.referenceLabel.visible = True
        panel1.referenceLabel.text = "Input Volume:"
        panel1.referenceInput.setToolTip("Select Input Volume")
        panel1.objectName = "SingleShotInputWidget"

        # Ensure referenceInput accepts LabelMapNodes
        if hasattr(panel1.referenceInput, "nodeTypes"):
            panel1.referenceInput.nodeTypes = ["vtkMRMLLabelMapVolumeNode", "vtkMRMLScalarVolumeNode"]

        self.modeWidgets[widgets.SingleShotInputWidget.MODE_NAME] = panel1
        self.optionsStack.addWidget(panel1)

        # Batch Widget
        panel2 = widgets.BatchInputWidget(objectNamePrefix="PoreNetworkWorkflow Batch")
        panel2.onDirSelected = self._onBatchInputSelected

        # Configure for PNM
        panel2.ioBatchValTagLabel.text = "Image Suffix:"
        panel2.ioBatchValTagPattern.text = ".nrrd"
        panel2.ioBatchROITagLabel.visible = False
        panel2.ioBatchSegTagLabel.visible = False
        panel2.ioBatchLabelLabel.visible = False
        panel2.ioBatchROITagPattern.visible = False
        panel2.ioBatchSegTagPattern.visible = False
        panel2.ioBatchLabelPattern.visible = False
        panel2.ioBatchValTagPattern.objectName = "BatchPathLineEdit"

        self.modeWidgets[widgets.BatchInputWidget.MODE_NAME] = panel2
        self.optionsStack.addWidget(panel2)

        layout.addLayout(optionsLayout)
        layout.addWidget(self.optionsStack)
        return widget

    def _setupConfigSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Configuration"
        layout = qt.QVBoxLayout(widget)

        if ReportForm is not None:
            self.reportForm = ReportForm.ReportForm()
            self.reportForm.objectName = "PNMReportForm"
            layout.addWidget(self.reportForm)
        else:
            layout.addWidget(qt.QLabel("Report module not available"))
            self.reportForm = None

        return widget

    def _setupOutputSection(self):
        widget = ctk.ctkCollapsibleButton()
        widget.text = "Output"
        layout = qt.QVBoxLayout(widget)

        formLayout = qt.QFormLayout()

        # Server controls
        self._setupServerControls(layout)  # This adds to VBox, server controls are complex

        # Output Prefix
        self.outputPrefix = qt.QLineEdit()
        self.outputPrefix.objectName = "Output Prefix Line Edit"
        self.outputPrefix.setPlaceholderText("Output Prefix")
        formLayout.addRow("Output Prefix:", self.outputPrefix)

        layout.addLayout(formLayout)

        # Apply Buttons
        hbox = qt.QHBoxLayout()
        self.applyBtn = qt.QPushButton("Apply")
        self.applyBtn.objectName = "Apply Button"
        self.applyBtn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.applyBtn.clicked.connect(self.onApply)

        self.cancelBtn = qt.QPushButton("Cancel")
        self.cancelBtn.setStyleSheet("QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}")
        self.cancelBtn.clicked.connect(self.onCancel)
        self.cancelBtn.enabled = False

        hbox.addWidget(self.applyBtn)
        hbox.addWidget(self.cancelBtn)
        layout.addLayout(hbox)

        return widget

    def _setupServerControls(self, layout):
        self.toggleServerButton = qt.QPushButton("Open Report Locally")
        self.toggleServerButton.setStyleSheet(
            "QPushButton {font-size: 11px; font-weight: bold; padding: 8px; margin: 4px}"
        )
        self.toggleServerButton.objectName = "ToggleServerButton"
        self.serverStatus = qt.QLabel("Stopped")
        self.serverStatus.setOpenExternalLinks(True)
        self.serverStatus.objectName = "ServerStatusLabel"

        layout.addWidget(self.toggleServerButton)
        layout.addWidget(self.serverStatus)

        self.advancedSection = ctk.ctkCollapsibleButton()
        self.advancedSection.text = "Advanced (Server Settings)"
        self.advancedSection.collapsed = True
        layout.addWidget(self.advancedSection)

        advLayout = qt.QFormLayout(self.advancedSection)

        self.updateScriptsButton = qt.QPushButton("Update scripts in report folder")
        self.updateScriptsButton.setToolTip(
            "This button will replace existing Streamlit codes in the report folder with the versions from the current GeoSlicer release."
        )
        self.updateScriptsButton.setIcon(qt.QIcon(getResourcePath("Icons") / "png" / "UpdateStreamlit.png"))

        if StreamlitServer.StreamlitServer is not None:
            self.server = StreamlitServer.StreamlitServer(
                self.simOptions,
                self.serverStatus,
                self.toggleServerButton,
                self.updateScriptsButton,
            )
            self.server.objectName = "StreamlitServerManager"

            self.updateScriptsButton.clicked.connect(self.server.onUpdateScripts)

            portLineEdit = ui.numberParam((1024, 65535), value=self.server.port, step=1, decimals=0)
            portLineEdit.setToolTip("Select server port for Streamlit report")
            portLineEdit.valueChanged.connect(self.server.onPortChanged)
            advLayout.addRow("Server Port:", portLineEdit)

            folderLineEdit = ctk.ctkPathLineEdit()
            folderLineEdit.filters = ctk.ctkPathLineEdit.Dirs
            folderLineEdit.objectName = "StreamlitFolderLineEdit"
            folderLineEdit.setToolTip("Select a folder where you can run the Streamlit report")
            folderLineEdit.currentPathChanged.connect(self.server.onPathChanged)
            if self.reportForm:
                folderLineEdit.currentPathChanged.connect(self.reportForm.onPathChanged)

            folderLineEdit.setCurrentPath(self.server.report_folder)
            advLayout.addRow("Report Folder:", folderLineEdit)

            hbox = qt.QHBoxLayout()
            hbox.addWidget(self.updateScriptsButton)
            advLayout.addRow(hbox)

            ApplicationObservables().applicationLoadFinished.connect(self.__onApplicationLoadFinished)
        else:
            self.toggleServerButton.clicked.connect(self.onStreamlitServerUnavailable)
            self.server = None

        print("Server:", self.server)

    def _onModeClicked(self):
        if self.modeSelectors[widgets.SingleShotInputWidget.MODE_NAME].isChecked():
            self.currentMode = widgets.SingleShotInputWidget.MODE_NAME
            self.optionsStack.setCurrentIndex(0)
        else:
            self.currentMode = widgets.BatchInputWidget.MODE_NAME
            self.optionsStack.setCurrentIndex(1)

    def _onReferenceSelected(self, node):
        if node:
            nodeName = node.GetName()
            tokens = nodeName.split("_")
            # Logic to generate PNM name if needed, as in MicrotomRemote
            # "PNM" type
            if len(tokens) < 4:
                try:
                    arr = slicer.util.arrayFromVolume(node).astype(float)  # Check if array can be retrieved
                    image_type = "PNM"
                    shape = ["{:04d}".format(int(d)) for d in arr.shape[::-1]]
                    res = min([v for v in node.GetSpacing()])
                    nodeName = "_".join([*tokens, image_type, *shape, "{:05d}".format(int(round(res * 1e6))) + "nm"])
                except:
                    pass

            self.outputPrefix.setText(nodeName)
            if self.reportForm:
                self.reportForm.wellName.setText(nodeName)
                self.reportForm.setVolumeNode(node)

        self.applyBtn.enabled = node is not None

    def _onBatchInputSelected(self, path):
        if path:
            if self.reportForm:
                self.outputPrefix.setText(self.reportForm.report_folder)
            self.applyBtn.enabled = True
        else:
            self.applyBtn.enabled = False

    def onApply(self):
        if not self.logic:
            slicer.util.errorDisplay("Logic not initialized.")
            return

        self.applyBtn.enabled = False
        self.cancelBtn.enabled = True
        slicer.app.processEvents()

        try:
            params = self.reportForm.params() if self.reportForm else {}
            # Ensure required params

            modeWidget = self.modeWidgets[self.currentMode]

            uid = None
            if self.currentMode == widgets.BatchInputWidget.MODE_NAME:
                batchDir = modeWidget.ioFileInputLineEdit.currentPath
                segTag = modeWidget.ioBatchSegTagPattern.text
                roiTag = modeWidget.ioBatchROITagPattern.text
                valTag = modeWidget.ioBatchValTagPattern.text
                labelTag = modeWidget.ioBatchLabelPattern.text

                uid = self.logic.runInBatch(
                    "pnm",  # Simulator name
                    None,  # Input Node (None for batch)
                    batchDir,
                    segTag,
                    roiTag,
                    valTag,
                    labelTag,
                    output_path=None,  # or specific path?
                    mode="Local",  # Always local for this workflow?
                    outputPrefix=self.outputPrefix.text,
                    params=params,
                )
            else:
                # Single Shot
                # For PNM workflow in MicrotomRemote, mainInput was hidden, referenceInput was enabled.
                # So we pass referenceInput as input logic?
                refNode = modeWidget.referenceInput.currentNode()

                # ReportLogic.run signature:
                # simulator, segmentationNode, referenceNode, labels, roiNode=None, output_path=None, mode="Local", outputPrefix="", params=None

                # In MicrotomRemote for "pnm":
                # modeWidget.mainInput.currentNode() is None (hidden)
                # modeWidget.soiInput.currentNode() is None (hidden)
                # refNode is selected.

                # So we pass segmentationNode=None, referenceNode=refNode?
                # Let's assume ReportLogic handles this.

                uid = self.logic.run(
                    "pnm",
                    None,  # segmentationNode
                    refNode,  # referenceNode
                    None,  # labels
                    None,  # roiNode
                    output_path=None,
                    mode="Local",
                    outputPrefix=self.outputPrefix.text,
                    params=params,
                )

        except Exception as e:
            logging.error(f"Error executing Pore Network Workflow: {e}")
            slicer.util.errorDisplay(f"Error executing Pore Network Workflow: {e}")

        self.applyBtn.enabled = True
        self.cancelBtn.enabled = False

    def onCancel(self):
        if self.logic:
            self.logic.cancel()
        self.applyBtn.enabled = True
        self.cancelBtn.enabled = False

    def __onApplicationLoadFinished(self):
        if self.server:
            self.server.retrieveActiveStreamlit()
            ApplicationObservables().applicationLoadFinished.disconnect(self.__onApplicationLoadFinished)

    def onStreamlitServerUnavailable(self):
        slicer.util.errorDisplay("Server unavailable at this version.")


class PoreNetworkWorkflowLogic(LTracePluginLogic):
    # Fallback if needed, but we use ReportLogic
    pass
