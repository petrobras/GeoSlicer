JOB_EVENT_CANCEL = "CANCEL"
JOB_EVENT_CLOSE = "CLOSE"
JOB_EVENT_COLLECT = "COLLECT"
JOB_EVENT_CONNECT = "CONNECT"
JOB_EVENT_DEPLOY = "DEPLOY"
JOB_EVENT_DISCONNECTED = "DISCONNECTED"
JOB_EVENT_PROGRESS = "PROGRESS"
JOB_EVENT_START = "START"
JOB_EVENT_SHUTDOWN = "SHUTDOWN"

# Minimum delay between two PROGRESS polls of the same job. Prevents the
# monitor thread from busy-looping (and starving the GIL) when a handler
# reschedules PROGRESS immediately.
JOB_POLL_INTERVAL_SECONDS = 7.0

# Cap for the exponential backoff between reconnection attempts of a
# disconnected job (see SlurmJobStatusMixin.disconnected). Kept short on
# purpose: the backoff only exists to avoid hammering an unreachable host,
# and a long cap leaves a job displayed as NOT CONNECTED for hours after
# connectivity is back, which is indistinguishable from a stuck job.
DISCONNECT_BACKOFF_MAX_SECONDS = 300

JOB_STATE_COMPLETED = "COMPLETED"
JOB_STATE_DEPLOYING = "DEPLOYING"
JOB_STATE_FAILED = "FAILED"
JOB_STATE_NOTCONNECTED = "NOT CONNECTED"
JOB_STATE_PENDING = "PENDING"
JOB_STATE_RUNNING = "RUNNING"
JOB_STATE_CANCELLED = "CANCELLED"
JOB_STATE_IDLE = "IDLE"
JOB_STATE_DONE = "DONE"
# Set by a handler when the remote job could not be cancelled, so the local
# entry no longer mirrors a known remote state.
JOB_STATE_GHOST = "GHOST"

# States a job never leaves on its own. A connection or polling failure must
# not overwrite them: a COMPLETED job silently rewritten to NOT CONNECTED
# loses its result and lands in a state the monitor refuses to cancel, which
# is how entries become impossible to remove.
JOB_TERMINAL_STATES = frozenset(
    {
        JOB_STATE_COMPLETED,
        JOB_STATE_FAILED,
        JOB_STATE_CANCELLED,
        JOB_STATE_DONE,
    }
)

# Not finished, but not following anything either: the job moves again only
# when the user asks it to. IDLE was never resumed; GHOST lost track of its
# remote counterpart, so polling it would be running sacct on job ids we have
# already admitted we cannot trust. NOT CONNECTED is deliberately absent -- it
# is actively retrying under backoff.
JOB_DORMANT_STATES = frozenset(
    {
        JOB_STATE_IDLE,
        JOB_STATE_GHOST,
    }
)

# What the monitor must not deliver scheduled events to, for either reason.
# Answers a different question from JOB_TERMINAL_STATES ("is the outcome
# final?"), which is why they are two names and not one.
JOB_INACTIVE_STATES = JOB_TERMINAL_STATES | JOB_DORMANT_STATES
