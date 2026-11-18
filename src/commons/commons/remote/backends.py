"""Where a job can run, named once.

``auto`` leaves the choice to the dispatcher, ``local`` is this computer and ``remote`` is one of the
configured accounts. The three names end up in job details, in settings keys and in the UI of every module
that dispatches work, so they are declared here instead of in whichever dispatcher happened to need them
first.
"""

BACKEND_AUTO = "auto"
BACKEND_LOCAL = "local"
BACKEND_REMOTE = "remote"
