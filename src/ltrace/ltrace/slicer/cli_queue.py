import logging
import qt
import slicer

from collections import namedtuple

# This has no reason to be here apart from the type annotation in the constructor
from ltrace.slicer.widget.global_progress_bar import LocalProgressBar


CliNodeInformation = namedtuple("CliNodeInformation", ["node", "module", "parameters", "modified_callback"])


class CliQueue(qt.QObject):
    signal_queue_finished = qt.Signal()

    def __init__(self, cli_node=None, quick_start=False, progress_bar: LocalProgressBar = None):
        super(qt.QObject, self).__init__()
        self.__nodes = []
        self.__queue = []
        self.__running = False
        self.__update_display = True
        self.__progress_bar = progress_bar
        self.__current_observer_handlers = list()

        if cli_node is not None:
            if isinstance(cli_node, list):
                for node in cli_node:
                    self.add_cli_node(node)
            else:
                self.add_cli_node(cli_node)

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

    def stop(self):
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
        self.signal_queue_finished.emit()

    def add_cli_node(self, cli_node: CliNodeInformation):
        if not isinstance(cli_node, CliNodeInformation):
            raise RuntimeError(
                "Wrong input type's node. Current: '{}', Expected: 'slicer.vtkMRMLCommandLineModuleNode'".format(
                    type(cli_node)
                )
            )
        if self.__running:
            self.__queue.append(cli_node)
            logging.debug(
                "Creating cli node {} and adding it to queue. Total in queue: {}".format(
                    cli_node.node.GetID(), len(self.__queue)
                )
            )
        else:
            self.__nodes.append(cli_node)
            logging.debug("Creating cli node {}".format(cli_node.node.GetID()))

    def create_cli_node(self, module, parameters=None, modified_callback=None):
        node = slicer.cli.createNode(module, parameters)
        self.add_cli_node(
            CliNodeInformation(node=node, module=module, parameters=parameters, modified_callback=modified_callback)
        )

    def __clear_observers(self):
        for obj, handler in self.__current_observer_handlers:
            logging.debug("Removing observer {} from cli node {}".format(handler, obj.GetID()))
            qt.QTimer.singleShot(10, lambda x=handler: obj.RemoveObserver(x))

        self.__current_observer_handlers.clear()

    def __on_modified_event(self, caller, event):
        if caller is None and not self.__running and caller.IsBusy():
            return

        if (
            caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.Completed
            or caller.GetStatus() == slicer.vtkMRMLCommandLineModuleNode.CompletedWithErrors
        ):
            for queued_node_info in self.__queue[:]:
                if caller is queued_node_info.node:
                    self.__queue.remove(queued_node_info)
                    logging.debug(
                        "cli node {} run finished! Removing it from queue!".format(queued_node_info.node.GetID())
                    )

            if len(self.__queue) > 0:
                self.__run_next_node_in_queue()
            else:
                self.stop()

    def __run_next_node_in_queue(self):
        if len(self.__queue) <= 0 or not self.__running:
            self.stop()
            return

        node_info = self.__queue[0]
        node = node_info.node
        module = node_info.module
        if node.IsBusy():
            logging.debug("Node {} is busy! Skipping it!".format(node.GetID()))
            self.__queue.remove(node_info)
            self.__run_next_node_in_queue()
            return

        logging.debug("Running next node: {}! Total node in queue: {}".format(node.GetID(), len(self.__queue)))
        logic = module.logic()
        logic.SetDeleteTemporaryFiles(True)
        logic.Apply(node, self.__update_display)

        modified_handler = node.AddObserver("ModifiedEvent", self.__on_modified_event)
        self.__current_observer_handlers.append((node, modified_handler))
        logging.debug("Creating default observer {} for node {}".format(modified_handler, node.GetID()))
        if node_info.modified_callback is not None:
            modified_callback_handler = node.AddObserver(
                "ModifiedEvent",
                lambda caller, event, config=node_info.parameters: node_info.modified_callback(caller, event, config),
            )
            logging.debug("Creating custom observer {} for node {}".format(modified_callback_handler, node.GetID()))
            self.__current_observer_handlers.append((node, modified_callback_handler))
        if self.__progress_bar is not None:
            self.__progress_bar.setCommandLineModuleNode(node)

    def is_running(self):
        return self.__running
