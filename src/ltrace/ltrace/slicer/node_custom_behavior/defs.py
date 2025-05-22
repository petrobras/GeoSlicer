from enum import Enum


class TriggerEvent(Enum):
    NONE = 0
    SAVE = 1
    SAVE_AS = 2
    LOAD = 3
    NODE_ADDED = 4
    NODE_REMOVED = 5
