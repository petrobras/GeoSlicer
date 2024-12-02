import csv
import json
import pickle

import vtk, qt, ctk, slicer

from pathlib import Path

from ltrace.slicer_utils import *
from ltrace.units import convert_to_global_registry, global_unit_registry as ureg

from ltrace.slicer.directorylistwidget import DirectoryListWidget


#
# CorePluggingExporter
#


class CorePluggingExporter(LTracePlugin):
    SETTING_KEY = "CorePluggingExporter"

    def __init__(self, parent):
        LTracePlugin.__init__(self, parent)
        self.parent.title = "Core Plugging Exporter"
        self.parent.categories = ["Tools"]
        self.parent.dependencies = []
        self.parent.contributors = ["LTrace Geophysics Team"]  # replace with "Firstname Lastname (Organization)"
        self.parent.helpText = ""
        self.parent.helpText += self.getDefaultModuleDocumentationLink()
        self.parent.acknowledgementText = ""


#
# CorePluggingExporterWidget
#


class CorePluggingExporterWidget(LTracePluginWidget):
    def setup(self):
        LTracePluginWidget.setup(self)

        # Instantiate and connect widgets ...

        #
        # Parameters Area
        #
        parametersCollapsibleButton = ctk.ctkCollapsibleButton()
        parametersCollapsibleButton.text = "Parameters"
        self.layout.addWidget(parametersCollapsibleButton)

        # Layout within the dummy collapsible button
        parametersFormLayout = qt.QFormLayout(parametersCollapsibleButton)

        self.dataSourceWidget = DirectoryListWidget()
        parametersFormLayout.addRow("Data Sources: ", self.dataSourceWidget)

        #
        # Apply Button
        #
        self.applyJSONButton = qt.QPushButton("Export to JSON")
        self.applyJSONButton.enabled = True
        parametersFormLayout.addRow(self.applyJSONButton)

        self.applyCSVButton = qt.QPushButton("Export to CSV")
        self.applyCSVButton.enabled = True
        parametersFormLayout.addRow(self.applyCSVButton)

        # connections
        self.applyJSONButton.connect("clicked(bool)", self.onApplyJSONButton)
        self.applyCSVButton.connect("clicked(bool)", self.onApplyCSVButton)

        # Add vertical spacer
        self.layout.addStretch(1)

        # Refresh Apply button state
        # self.onSelect()

    def cleanup(self):
        pass

    # def onSelect(self):
    #     self.applyButton.enabled = self.inputSelector.currentNode() and self.outputSelector.currentNode()

    def onApplyJSONButton(self):
        logic = CorePluggingExporterLogic()
        logic.run(self.dataSourceWidget.ui.pathList.directoryList, format=".json")

    def onApplyCSVButton(self):
        logic = CorePluggingExporterLogic()
        logic.run(self.dataSourceWidget.ui.pathList.directoryList, format=".csv")


#
# CorePluggingExporterLogic
#


class CorePluggingExporterLogic(LTracePluginLogic):
    def run(self, dataSources, format=".csv"):
        import shutil

        from ltrace.cli_progress import RunCLIWithProgressBar

        """
        Run the actual algorithm
        """

        filter = "JSON (*.json)" if format == ".json" else "CSV (*.csv)"
        path = qt.QFileDialog.getSaveFileName(None, "Save file", "", filter)
        if len(path) == 0:
            return

        if not path.endswith(format):
            path += format

        temp_dir = Path(slicer.util.tempDirectory(key="__import_core_images__"))

        try:
            rock_cores_list = []
            for i, sourceDir in enumerate(dataSources):
                output_file = temp_dir / f"output_plug_locations_{i}"
                print(sourceDir)
                success, message = RunCLIWithProgressBar(
                    slicer.modules.importcoreimagescli,
                    parameters={
                        "core_images_folder": sourceDir,
                        "output_file": str(output_file),
                    },
                    title="Extracting plugging locations",
                )

                if not success:
                    raise RuntimeError(f'Failed to process file "{sourceDir}". Cause: {message}')

                samples, _ = self._parseResult(output_file, 0)
                rock_cores_list.extend(samples)

                # shutil.rmtree(temp_dir)
        except Exception as e:
            slicer.util.errorDisplay(repr(e))
        finally:
            shutil.rmtree(temp_dir)

        self._writeOutput(path, rock_cores_list, format)

        return True

    def _writeOutput(self, destination, items, format):
        if format == ".csv":
            with open(destination, "w", newline="") as csvfile:
                spamwriter = csv.writer(csvfile, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL)
                spamwriter.writerow(["source", "relative_depth", "relative_to_core_start_plug_depth"])
                for core in items:
                    spamwriter.writerow(
                        [
                            core["source"],
                            core["relative_depth"],
                            ",".join(str(it) for it in core["relative_to_core_start_plug_depth"]),
                        ]
                    )

        elif format == ".json":
            with open(destination, "w") as jsonfile:
                json.dump(items, jsonfile)

    def _parseResult(self, outputFile, current_depth=0):

        current_depth *= ureg.meter
        cores = []
        print(str(outputFile))
        with open(str(outputFile), "rb") as f:
            result = pickle.loads(f.read())

            for file, plugs in result:
                filename = file.stem
                core_start = 0 * ureg.centimeter

                for i, ((start, end), holes) in enumerate(plugs):
                    start = convert_to_global_registry(start)
                    end = convert_to_global_registry(end)
                    holes.sort()

                    cores.append(
                        {
                            "source": "{}_{}".format(filename, i + 1),
                            "relative_depth": current_depth.m_as(ureg.meter),
                            "relative_to_core_start_plug_depth": [
                                (convert_to_global_registry(h) - start).m_as(ureg.meter) for h in holes
                            ],
                        }
                    )

                    current_depth += end - start

        return cores, current_depth
