import sys
import gc

from contextlib import contextmanager


@contextmanager
def priority_lock(interval=30, no_gc=False):
    """
    Temporarily sets the Python GIL switch interval to a high value
    to prevent the interpreter from preempting the current thread.

    This is useful in scenarios where you want to ensure that a block of code
    runs without interruption from other threads for a longer duration.

    Args:
        interval (float): The switch interval in seconds to set temporarily.
        no_gc (bool): If True, disables garbage collection during the context.
    """
    # Save the original interval (usually 0.005 seconds)
    original_interval = sys.getswitchinterval()

    gc_was_enabled = gc.isenabled()

    try:
        if no_gc and gc_was_enabled:
            gc.collect()
            gc.disable()

        sys.setswitchinterval(interval)
        yield
    finally:
        # Always restore the interval, even if an exception occurs
        sys.setswitchinterval(original_interval)
        if gc_was_enabled:
            gc.enable()
