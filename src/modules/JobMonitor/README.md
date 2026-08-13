# Job Monitor

_GeoSlicer_ module for real-time monitoring and management of remote computational jobs running on distributed compute clusters. It tracks jobs deployed to remote hosts and displays their status, progress, and details.

__Features__

* Real-time job status tracking with progress bars
* Search and filter jobs by host, name, status, address, protocol, UID, or type
* Sort jobs by name, status, or submission date
* Cancel running jobs or collect completed results
* Inspect job details, host information, and execution logs
* Automatic cleanup notification for jobs older than 15 days
* Reconnect to idle or disconnected jobs

__Module Interface__

1. __Search bar__: Filter jobs using free text or specific flags (`@host`, `@name`, `@status`, `@address`, `@protocol`, `@uid`, `@type`). Multiple flags can be combined in a single query.

2. __Sort options__: Sort the job list by name (A-Z or Z-A), status, newest first, or oldest first.

3. __Reconnect Visible__: Reconnect all visible idle or disconnected jobs to their remote hosts.

4. __Job list__: Each job entry displays:
   - Job name and host
   - Progress bar (0-100%)
   - Current status and elapsed time
   - Warning icon for jobs older than 15 days
   - Context menu with actions: Cancel, Load data, Details, and Restart

5. __Details dialog__: Accessed from the context menu, shows three tabs:
   - _Job_: Job metadata (UID, name, type, status, progress, timestamps)
   - _Host_: Host connection details (address, protocol, credentials)
   - _Logs_: Execution traceback and error information

__Job States__

* __Running__: Job is actively executing on the remote host. Cancel is available if the host is connected.
* __Completed__: Job finished successfully. Results can be loaded via "Load data".
* __Idle__: Job is registered but not actively running. Can be restarted.
* __Not Connected__: Host connection was lost. Reconnection can be attempted.
* __Failed__: Job encountered an error. Logs can be inspected for details.
