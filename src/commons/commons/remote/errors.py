"""Exceptions raise by Apps."""


class ChannelError(Exception):
    """Base class for all exceptions

    Only to be invoked when only a more specific error is not available.
    """

    def __repr__(self):
        cause = getattr(self, "e", None)
        return "Hostname: {0}, reason: {1}{2}".format(
            getattr(self, "hostname", "?"),
            getattr(self, "reason", type(self).__name__),
            "" if cause is None else ", cause: {0!r}".format(cause),
        )

    def __str__(self):
        return self.__repr__()


class TimeoutException(ChannelError):
    """SSH channel could not be created since server did not respond

    Contains:
    reason(string)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "SSH channel could not be created since server did not respond"
        self.hostname = hostname
        self.e = e


class BadHostKeyException(ChannelError):
    """SSH channel could not be created since server's host keys could not
    be verified

    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "SSH channel could not be created since server's host keys could not be verified"
        self.hostname = hostname
        self.e = e


class BadScriptPath(ChannelError):
    """An error raised during execution of an app.
    What this exception contains depends entirely on context
    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "Inaccessible remote script dir. Specify script_dir"
        self.hostname = hostname
        self.e = e


class BadPermsScriptPath(ChannelError):
    """User does not have permissions to access the script_dir on the remote site

    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "User does not have permissions to access the script_dir"
        self.hostname = hostname
        self.e = e


class FileExists(ChannelError):
    """Push or pull of file over channel fails since a file of the name already
    exists on the destination.

    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname, filename=None):
        super().__init__()
        self.reason = "File name collision in channel transport phase:" + filename
        self.hostname = hostname
        self.e = e


class AuthException(ChannelError):
    """An error raised during execution of an app.
    What this exception contains depends entirely on context
    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "Authentication to remote server failed"
        self.hostname = hostname
        self.e = e


class MissingCredentialsError(ChannelError):
    """No credential is stored for the host (no password and no identity file).

    Distinct from AuthException: there is nothing to invalidate, so the stored
    password must NOT be deleted. The caller should prompt for login
    (interactive) or flag the job NOT CONNECTED (polling) instead of treating
    it as a rejected credential.

    Contains:
    reason(string)
    e (underlying exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "No stored credentials (password or identity file)"
        self.hostname = hostname
        self.e = e


class UserDisconnectedError(ChannelError):
    """The user disconnected from the host and has not connected again since.

    Raised instead of reconnecting on the user's behalf: the stored credential
    is still good, so without this the next poll would silently undo the
    Disconnect. Like MissingCredentialsError, nothing is wrong with the
    credential, so it must not be deleted. The polling caller should flag the
    job NOT CONNECTED and wait for the user to connect.

    Contains:
    reason(string)
    e (underlying exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "Disconnected by the user"
        self.hostname = hostname
        self.e = e


class SSHException(ChannelError):
    """if there was any other error connecting or establishing an SSH session

    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "Error connecting or establishing an SSH session"
        self.hostname = hostname
        self.e = e


class HostNotFoundError(ChannelError):
    """The host address could not be resolved (DNS/name resolution failed).

    Distinct from SSHException/TimeoutException: those mean a resolvable host
    was unreachable this time (transient — worth retrying). A resolution
    failure means the address itself could not be found, so automatic retries
    should stop until the user fixes the address or their network.

    Contains:
    reason(string)
    e (underlying exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "Host address could not be resolved"
        self.hostname = hostname
        self.e = e


class FileCopyException(ChannelError):
    """File copy operation failed

    Contains:
    reason(string)
    e (paramiko exception object)
    hostname (string)
    """

    def __init__(self, e, hostname):
        super().__init__()
        self.reason = "File copy failed due to {0}".format(e)
        self.hostname = hostname
        self.e = e
