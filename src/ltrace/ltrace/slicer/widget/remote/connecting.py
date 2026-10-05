from ltrace.remote import errors
from ltrace.remote.jobs import JobManager
from ltrace.slicer.widget.remote import waiting

# A slow handshake alone takes about 11 s (TCP, authentication and a first
# command), and the monitor may be in the middle of another host's send when
# the request arrives.
CONNECT_TIMEOUT_SECONDS = 60


def connect(host, parent=None):
    """Have the job monitor connect to host, showing 'Connecting...' with a Cancel button.

    Only waits: the connection is the job monitor's to make, and the client it
    makes never comes back here.

    Returns whether the host is connected, or None if the person cancelled.
    Raises what the connection attempt raised, and TimeoutException when the
    monitor did not answer in time.
    """
    future = JobManager.request_connect(host)

    try:
        waiting.wait(
            [future],
            title=f"Connect to {host.name}",
            text=f"Connecting to {host.server_name()}...",
            buttonText="Cancel",
            timeoutSeconds=CONNECT_TIMEOUT_SECONDS,
            parent=parent,
        )
    except TimeoutError:
        future.cancel()
        raise errors.TimeoutException(
            TimeoutError(f"The job monitor did not answer within {CONNECT_TIMEOUT_SECONDS} s."),
            host.server_name(),
        )

    if not future.done():
        # Cancelled. If the monitor has not started on it yet, the attempt is
        # dropped; if it has, it finishes in the background and its client is
        # cached for next time. Either way nobody waits on it.
        future.cancel()
        return None

    return future.result()
