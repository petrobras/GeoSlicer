"""GeoSlicer CLI.

Usage:
    python gs.py exec <script.py>
    python gs.py run-tests [--timeout N] [SuiteName[:test1,test2] ...]
    python gs.py status
    python gs.py cancel
    python gs.py restart [--timeout N] [--interval N]

Options:
    --port PORT  GeoSlicer WebServer port (default: 2016)
"""

import argparse
import json
import sys
import time

import requests

SLICER_PORT = 2016
RUN_TESTS_DEFAULT_TIMEOUT = 1800  # 30 minutes


def _indent(code, spaces=4):
    pad = " " * spaces
    return "\n".join(f"{pad}{line}" if line.strip() else line for line in code.splitlines())


def _wrap(user_code):
    return f"""
import sys, io, traceback
_buf = io.StringIO()
_orig = sys.stdout
sys.stdout = _buf
try:
{_indent(user_code)}
except Exception:
    traceback.print_exc(file=sys.stdout)
finally:
    sys.stdout = _orig
__execResult = {{"stdout": _buf.getvalue()}}
"""


def post_code(code, url, timeout=None):
    """POST wrapped code to GeoSlicer's exec endpoint. Returns (stdout, error).

    On transport (ConnectionError), HTTP, or JSON-envelope failure, stdout is
    None and error is a human-readable string. requests.exceptions.Timeout is
    deliberately propagated so callers (e.g. run-tests) can distinguish it.
    """
    try:
        response = requests.post(url, data=_wrap(code), timeout=timeout)
    except requests.exceptions.ConnectionError:
        return None, f"could not connect to GeoSlicer at {url} (is the Web Server running?)"
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text[:300]}"
    try:
        return response.json().get("stdout", ""), None
    except json.JSONDecodeError:
        return None, f"invalid JSON envelope: {response.text[:300]}"


def post_code_json(code, url, timeout=None):
    """POST code whose stdout is a single JSON document. Returns (value, error)."""
    stdout, err = post_code(code, url, timeout=timeout)
    if err is not None:
        return None, err
    try:
        return json.loads(stdout.strip()), None
    except json.JSONDecodeError:
        return None, f"script stdout was not JSON:\n{stdout[:500]}"


def _cmd_exec(args):
    import os

    if not args.script.endswith(".py"):
        print("Error: only .py files are supported.")
        return 1
    if not os.path.isfile(args.script):
        print(f"Error: file not found: {args.script}")
        return 1
    try:
        with open(args.script) as f:
            code = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        return 1
    stdout, err = post_code(code, args.url)
    if err is not None:
        print(err, file=sys.stderr)
        return 1
    print(stdout, end="")
    return 0


_STATUS_CODE = (
    "from ltrace.slicer.tests.api import get_run_status\n" "import json\n" "print(json.dumps(get_run_status()))"
)

_CANCEL_CODE = (
    "from ltrace.slicer.tests.api import cancel_run_tests\n" "import json\n" "print(json.dumps(cancel_run_tests()))"
)


def _hint_recovery():
    print(
        "\nTest is still running on the server. "
        "Use `gs.py status` to fetch buffered output, or `gs.py cancel` to abort.",
        file=sys.stderr,
    )


def _cmd_run_tests(args):
    filters = args.filters
    code = (
        "from ltrace.slicer.tests.api import run_tests\n"
        f"run_tests(filters={json.dumps(filters) if filters else None})"
    )
    try:
        stdout, err = post_code(code, args.url, timeout=args.timeout)
    except requests.exceptions.Timeout:
        print(f"\nTimeout after {args.timeout}s waiting for tests to finish.", file=sys.stderr)
        _hint_recovery()
        return 124
    except KeyboardInterrupt:
        print("\nInterrupted locally.", file=sys.stderr)
        _hint_recovery()
        return 130
    if err is not None:
        print(err, file=sys.stderr)
        return 1
    print(stdout, end="")
    return 0


def _cmd_status(args):
    data, err = post_code_json(_STATUS_CODE, args.url, timeout=15)
    if err:
        print(f"Could not fetch status: {err}", file=sys.stderr)
        return 1
    output = data.get("output", "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if data.get("running"):
        log = data.get("log_file") or "<unknown>"
        print(f"[STILL RUNNING] log file: {log}", file=sys.stderr)
        return 2
    result = data.get("result") or "NO_RUN"
    err_msg = data.get("error")
    if err_msg:
        print(f"[ERROR] {err_msg}", file=sys.stderr)
    print(f"[DONE: {result}]", file=sys.stderr)
    return 0 if result == "SUCCEED" else 1


def _cmd_cancel(args):
    data, err = post_code_json(_CANCEL_CODE, args.url, timeout=15)
    if err:
        print(f"Could not request cancel: {err}", file=sys.stderr)
        return 1
    if not data.get("running"):
        print("No test run is in progress.")
        return 0
    if data.get("cancel_requested"):
        print("Cancel requested. Tests will stop at the next safe point.")
    else:
        print("Could not request cancel (no model attached). Test may still be running.")
    return 0


_RESTART_CODE = """\
import slicer
slicer.app.userSettings().setValue("GeoSlicer/AgentSkipOnboarding", "true")
slicer.app.userSettings().sync()
slicer.util.restart()
"""

_READINESS_CODE = """\
import slicer, json
ctx = getattr(slicer.modules, "AppContextInstance", None)
initialized = getattr(ctx, "appInitialized", False) if ctx else False
print(json.dumps({"initialized": initialized}))
"""


def _cmd_restart(args):
    url = args.url

    print(f"Sending restart command to {url}...")
    # Fire-and-forget: server is killing itself mid-response, failure is expected.
    try:
        requests.post(url, data=_RESTART_CODE, timeout=5)
    except Exception:
        pass

    print("Waiting for GeoSlicer to shut down...")
    deadline = time.time() + 30
    while time.time() < deadline:
        # Connection failure is the positive signal here (server is down).
        try:
            requests.post(url, data="__execResult = {'ping': True}", timeout=2)
        except Exception:
            print("GeoSlicer is restarting...")
            break
        time.sleep(1)
    else:
        print("Warning: server did not go down within 30s.")

    print(f"Waiting for GeoSlicer to be ready (timeout: {args.timeout}s)...")
    start = time.time()
    while time.time() - start < args.timeout:
        data, _ = post_code_json(_READINESS_CODE, url, timeout=5)
        if data is not None and data.get("initialized", False):
            print(f"GeoSlicer is ready! ({time.time() - start:.1f}s)")
            return 0
        remaining = args.timeout - (time.time() - start)
        if remaining > 0:
            time.sleep(min(args.interval, remaining))

    print(f"Timeout: GeoSlicer not ready after {args.timeout}s.")
    return 1


def main():
    parser = argparse.ArgumentParser(description="GeoSlicer CLI.")
    parser.add_argument(
        "--port", type=int, default=SLICER_PORT, help=f"GeoSlicer WebServer port (default: {SLICER_PORT})"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_exec = sub.add_parser("exec", help="Execute a .py script in GeoSlicer.")
    p_exec.add_argument("script", help="Path to .py file.")

    p_tests = sub.add_parser("run-tests", help="Run integration tests.")
    p_tests.add_argument("filters", nargs="*", metavar="FILTER", help='e.g. "SuiteName" or "SuiteName:test1,test2"')
    p_tests.add_argument(
        "--timeout",
        type=int,
        default=RUN_TESTS_DEFAULT_TIMEOUT,
        help=f"Max seconds to wait for tests (default: {RUN_TESTS_DEFAULT_TIMEOUT})",
    )

    sub.add_parser("status", help="Fetch buffered output and status of the last/in-flight test run.")
    sub.add_parser("cancel", help="Request cancellation of the in-flight test run.")

    p_restart = sub.add_parser("restart", help="Restart GeoSlicer and wait for readiness.")
    p_restart.add_argument("--timeout", type=int, default=120, help="Max seconds to wait (default: 120)")
    p_restart.add_argument("--interval", type=float, default=3, help="Poll interval in seconds (default: 3)")

    args = parser.parse_args()
    args.url = f"http://localhost:{args.port}/slicer/exec"
    handlers = {
        "exec": _cmd_exec,
        "run-tests": _cmd_run_tests,
        "status": _cmd_status,
        "cancel": _cmd_cancel,
        "restart": _cmd_restart,
    }
    sys.exit(handlers[args.command](args))


if __name__ == "__main__":
    main()
