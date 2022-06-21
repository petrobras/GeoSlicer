from pathlib import Path
from ltrace.slicer import helpers
from ltrace.slicer.helpers import tryGetNode, rand_cmap, createOutput, makeTemporaryNodePermanent
from ltrace.slicer.throat_analysis.throat_analysis import ThroatAnalysis
from ltrace.slicer_utils import dataFrameToTableNode

import json
import pandas as pd
import slicer


class ThroatAnalysisGenerator:
    """Helper class to execute the Throat Analysis process.
    It wraps the slicer's nodes creation used to the process input,
    allows the user to choose between running it through CLI or not, and
    offers the data handling pos-process.
    """

    def __init__(self, input_node_id, base_name, hierarchy_folder, direction, progress_bar=None, use_cli=True):
        self.input_node_id = input_node_id
        self.base_name = base_name
        self.hierarchy_folder = hierarchy_folder
        self.direction = direction
        self.__cli_node = None
        self.__cli_node_modified_observer = None
        self.__progress_bar = progress_bar
        self.__use_cli = use_cli
        self.throat_table_output_path = str(Path(slicer.app.temporaryPath).absolute() / "temp_throat_data.pkl")
        self.throat_table_node_id = None
        self.throat_label_map_node_id = None

    def create_output_nodes(self):
        throat_table_node = createOutput(
            prefix=self.base_name,
            ntype="Throat_Report",
            where=self.hierarchy_folder,
            builder=lambda n, hidden=True: helpers.createTemporaryNode(slicer.vtkMRMLTableNode, n, hidden=hidden),
        )

        throat_label_map_node = createOutput(
            prefix=self.base_name,
            ntype="Throat_LabelMap",
            where=self.hierarchy_folder,
            builder=lambda n, hidden=True: helpers.createTemporaryNode(
                slicer.vtkMRMLLabelMapVolumeNode, n, hidden=hidden
            ),
        )
        self.throat_table_node_id = throat_table_node.GetID()
        self.throat_label_map_node_id = throat_label_map_node.GetID()

    def generate(self):
        if self.input_node_id is None:
            raise AttributeError("Unable to generate throat analysis without a valid Label Map Volume Node input.")

        self.create_output_nodes()

        params = {"direction": self.direction}

        if self.__use_cli:
            cli_config = dict(
                params=json.dumps(params),
                labelVolume=self.input_node_id,
                outputLabelVolume=self.throat_label_map_node_id,
                outputReport=self.throat_table_output_path,
                reportNode=self.throat_table_node_id,
            )

            self.__cli_node = slicer.cli.run(
                slicer.modules.throatanalysiscli, None, cli_config, wait_for_completion=False
            )
            self.__cli_node_modified_observer = self.__cli_node.AddObserver(
                "ModifiedEvent", lambda c, e, cfg=cli_config: self.__on_cli_node_modified_event(c, e, cfg)
            )
            if self.__progress_bar is not None:
                self.__progress_bar.setCommandLineModuleNode(self.__cli_node)
        else:
            throat_table_node = tryGetNode(self.throat_table_node_id)
            throat_label_map_node = tryGetNode(self.throat_label_map_node_id)
            throat_analysis = ThroatAnalysis(labelVolume=self.input_node_id, params=params)
            dataFrameToTableNode(throat_analysis.throat_report_df, throat_table_node)
            slicer.util.updateVolumeFromArray(throat_label_map_node, throat_analysis.boundary_labeled_array)

    def handle_process_completed(self, config=None):
        if config is None:
            output_report_node_id = self.throat_table_node_id
            output_report = tryGetNode(self.throat_table_node_id)
            output_report_path = Path(self.throat_table_output_path)
            output_label_node = tryGetNode(self.throat_label_map_node_id)
        else:
            output_report = config["outputReport"]
            output_report_node_id = config["reportNode"]
            output_label_id = config["outputLabelVolume"]
            output_report_path = Path(config["outputReport"])
            output_label_node = tryGetNode(output_label_id)

        if output_report_path.exists():
            # Populate table node
            output_report_data = pd.read_pickle(str(output_report_path))
            output_report_node = tryGetNode(output_report_node_id)

            if output_report_node is None:
                return

            dataFrameToTableNode(output_report_data, tableNode=output_report_node)
            output_report_path.unlink(missing_ok=True)

            # Add label and color relation to the label map volume node
            max_color_number = len(list(output_report_data["Label"])) + 1
            color_names = [f"Throat_{throat_id}" for throat_id in list(output_report_data["ID"])]
            colors = rand_cmap(max_color_number)
            color_map_node = helpers.create_color_table(
                node_name=output_label_node.GetName() + "_Throat_Label_ColorMap",
                colors=colors,
                color_names=color_names,
                add_background=True,
            )
            output_label_node.GetDisplayNode().SetAndObserveColorNodeID(color_map_node.GetID())
            output_label_node.Modified()

            makeTemporaryNodePermanent(output_report, show=True)
            makeTemporaryNodePermanent(output_label_node, show=True)

    def __on_cli_node_modified_event(self, caller, event, config):
        if caller is None:
            del self.__cli_node
            del self.__cli_node_modified_observer
            self.__cli_node = None
            self.__cli_node_modified_observer = None
            return

        if caller.GetStatusString() == "Completed":
            self.handle_process_completed(config=config)

            if self.__cli_node_modified_observer is not None:
                self.__cli_node.RemoveObserver(self.__cli_node_modified_observer)

            del self.__cli_node_modified_observer
            del self.__cli_node
            self.__cli_node_modified_observer = None
            self.__cli_node = None
