from enum import Enum


class TestState(Enum):
    NOT_INITIALIZED = 0
    RUNNING = 1
    FAILED = 2
    SUCCEED = 3
    CANCELLED = 4

    @staticmethod
    def to_str(state: int) -> str:
        if state == TestState.NOT_INITIALIZED:
            return "Not initialized"
        if state == TestState.RUNNING:
            return "Running"
        if state == TestState.FAILED:
            return "Failed"
        if state == TestState.SUCCEED:
            return "Succeed"
        if state == TestState.CANCELLED:
            return "Cancelled"

        raise ValueError("Invalid state.")
