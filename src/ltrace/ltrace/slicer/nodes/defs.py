from enum import Enum


class TriggerEvent(Enum):
    NONE = 0
    SAVE = 1
    SAVE_AS = 2
    LOAD = 3
