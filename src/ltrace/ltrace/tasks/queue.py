import json

from collections import OrderedDict
from queue import Queue
from threading import Thread
from typing import Callable

from ltrace.tasks.core import AbstractTask


class QueryPool:
    def __init__(self):
        self._tasks = OrderedDict()
        self._task_models = {}
        self._in = Queue()
        self._out = Queue(maxsize=1)
        self.__active = False
        self.__thread = None

    def put(self, taskdesc: str):
        self._in.put(taskdesc)

    def register(self, model: str, builder: Callable) -> None:
        self._task_models[model] = builder

    def status(self):
        table = []
        for task in self._tasks.values():
            row = task.service()
            table.append(row)
        return table

    def start(self):
        self.__thread = Thread(target=self.dispatch, daemon=True)
        self.__thread.start()

    def stop(self):
        self.__active = False
        self.__thread.join()

    def dispatch(self):
        self.__active = True
        while self.__active:
            try:
                taskjs = self._in.get()
                data = json.loads(taskjs)
                if data["msgtype"] == "ADD_TASK":
                    builder = self._task_models[data["model"]]
                    task: AbstractTask = builder(data["task"])
                    self._tasks[task.id] = task
                elif data["msgtype"] == "GET_STATUS":
                    response = self.status()
                    self._out.put_nowait(response)
                elif data["msgtype"] == "CANCEL_TASK":
                    task: AbstractTask = self._tasks.pop(data["task"]["id"])
                    task.cancel()
                elif data["msgtype"] == "QUIT":
                    self.stop()
                    return
            finally:
                self._in.task_done()
