import logging
import qt
import slicer

from collections import namedtuple

# This has no reason to be here apart from the type annotation in the constructor
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar


CliNodeInformation = namedtuple(
    "CliNodeInformation", ["node", "module", "parameters", "modified_callback", "progress_text"]
)


class CliQueue(qt.QObject):
    signal_queue_successful = qt.Signal()
    signal_queue_failed = qt.Signal()
    signal_queue_cancelled = qt.Signal()
    signal_queue_finished = qt.Signal()

    def __init__(
        self,
        cli_node=None,
        quick_start=False,
        update_display=True,
        progress_bar: LocalProgressBar = None,
        progress_label: qt.QLabel = None,
    ):
        super(qt.QObject, self).__init__()
        self.__nodes = []
        self.__queue = []
        self.__running = False
        self.__update_display = update_display
        self.__progress_bar = progress_bar
        self.__progress_label = progress_label
        self.__current_observer_handlers = list()

        self.__current_node_idx = 0
        self.__total_nodes = 0
        self.__current_node_info = None
        self.__error_message = None

        if cli_node is not None:
            if isinstance(cli_node, list):
                for node in cli_node:
                    self.add_cli_node(node)
            else:
                self.add_cli_node(cli_node)

        if self.__progress_label is not None:
            self.__progress_label.setVisible(False)

        if quick_start:
            self.run()

    def run(self):
        if len(self.__nodes) <= 0:
            raise RuntimeError("There is no CLI node to run!")

        if self.__running:
            return

        self.__running = True
        self.__queue.clear()
        self.__clear_observers()
        self.__queue.extend(self.__nodes)
        self.__nodes.clear()
        logging.debug("Starting running CLI nodes process. Total in queue: {}".format(len(self.__queue)))
        self.__run_next_node_in_queue()

    def stop(self, cancelled=False):
        if not self.__running:
            return

        logging.debug("Stopping queue...")

        if len(self.__queue) > 0:
            for cli_node in self.__queue:
                cli_node.node.Cancel()

        self.__clear_observers()
        self.__queue.clear()
        self.__nodes.clear()
        self.__running = False
        if self.__progress_label is not None:
            self.__progress_label.setVisible(False)

        if self.__error_message is None:
            if not cancelled:
                self.signal_queue_successful.emit()
            else:
                self.signal_queue_cancelled.emit()
        else:
            self.signal_queue_failed.emit()
        self.signal_queue_finished.emit()

        self.__current_node_info = None

    def add_cli_node(self, cli_node: CliNodeInformation):
        if not isinstance(cli_node, CliNodeInformation):
            raise RuntimeError(
                "Wrong input type's node. Current: '{}', Expected: 'slicer.vtkMRMLCommandLineModuleNode'".format(
                    type(cli_node)
                )
            )

        self.__total_nodes += 1
        if self.__running:
            self.__queue.append(cli_node)
            self.update_progress_label(self.__queue[0])
            logging.debug(
                "Creating cli node {} and adding it to queue. Total in queue: {}".format(
                    cli_node.node.GetID(), len(self.__queue)
                )
            )
        else:
            self.__nodes.append(cli_node)
            logging.debug("Creating cli node {}".format(cli_node.node.GetID()))

    def create_cli_node(self, module, parameters=None, modified_callback=None, progress_text="Running"):
        node = slicer.cli.createNode(module, parameters)
        self.add_cli_node(
            CliNodeInformation(
                node=node,
                module=module,
                parameters=parameters,
                modified_callback=modified_callback,
                progress_text=progress_text,
            )
        )

    def __clear_observers(self):
        for obj, handler in self.__current_observer_handlers:
            logging.debug("Removing observer {} from cli node {}".format(handler, obj.GetID()))
            obj.RemoveObserver(handler)

        self.__current_observer_handlers.clear()

    def __on_modified_event(self, caller, event):
        if caller is None or self.__current_node_info is None:
            return

        if self.__current_node_info.modified_callback:
            self.__current_node_info.modified_callback(caller, event, self.__current_node_info.parameters)

        if not self.__running or caller.IsBusy():
            return

        if caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed:
            logging.debug(
                "cli node {} run finished! Removing it from queue!".format(self.__current_node_info.node.GetID())
            )
            self.__queue.remove(self.__current_node_info)

            if len(self.__queue) > 0:
                self.__run_next_node_in_queue()
            else:
                self.stop()

        elif caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.CompletedWithErrors:
            logging.error("error running cli node {}!".format(self.__current_node_info.node.GetID()))
            self.__error_message = (
                f"{self.__current_node_info.progress_text}:\n{caller.GetErrorText().strip().splitlines()[-1]}"
            )
            self.stop()

        elif caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Cancelled:
            self.stop(cancelled=True)

    def __run_next_node_in_queue(self):
        if len(self.__queue) <= 0 or not self.__running:
            self.stop()
            return

        self.__clear_observers()
        self.__current_node_info = self.__queue[0]
        node = self.__current_node_info.node
        module = self.__current_node_info.module
        if node.IsBusy():
            logging.debug("Node {} is busy! Skipping it!".format(node.GetID()))
            self.__queue.remove(self.__current_node_info)
            self.__current_node_info = None
            self.__run_next_node_in_queue()
            return

        self.__current_node_idx += 1
        logging.debug("Running next node: {}! Total node in queue: {}".format(node.GetID(), len(self.__queue)))
        logic = module.logic()
        logic.SetDeleteTemporaryFiles(True)
        logic.Apply(node, self.__update_display)

        modified_handler = node.AddObserver("ModifiedEvent", self.__on_modified_event)
        self.__current_observer_handlers.append((node, modified_handler))
        logging.debug("Creating default observer {} for node {}".format(modified_handler, node.GetID()))
        if self.__progress_bar is not None:
            self.__progress_bar.setCommandLineModuleNode(node)
        if self.__progress_label is not None and self.__total_nodes > 1:
            self.update_progress_label(self.__current_node_info)

    def is_running(self):
        return self.__running

    def get_error_message(self):
        return self.__error_message

    def get_current_node(self):
        return self.__current_node_info.node

    def update_progress_label(self, node_info):
        if self.__progress_label is None:
            return
        self.__progress_label.setText(f"Step {self.__current_node_idx}/{self.__total_nodes}: {node_info.progress_text}")
        self.__progress_label.setVisible(True)

    # Compatibility with vtkMRMLCommandLineModuleNode:
    def IsBusy(self):
        return self.is_running()

    def Cancel(self):
        return self.stop(cancelled=True)
