#!/usr/bin/env python
"""Start the Interactive Segmenter fuzzer in the running GeoSlicer and watch it.

    python fuzz.py            # start with a random seed and follow the status
    python fuzz.py 12345      # reproduce a seed
    python fuzz.py --attach   # just follow a fuzzer that is already running
    python fuzz.py --stop     # stop a running fuzzer and exit

Ctrl-C stops the fuzzer and restores GeoSlicer (unless it already froze on a
crash, in which case it is left frozen for inspection -- rerun with --stop once
you are done).
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, os.pardir, os.pardir))
sys.path.insert(0, os.path.join(REPO_ROOT, ".claude", "skills", "gs-exec", "scripts"))

from gs import post_code_json  # noqa: E402

FUZZER = os.path.join(HERE, "fuzz_interactive_segmenter.py")

POLL_SECONDS = 3


def run(code, url, timeout=120, fatal=True):
    """Exec `code` in GeoSlicer and return its JSON result.

    With fatal=False a dead/unreachable GeoSlicer returns None instead of
    exiting -- used on teardown, where the instance may already be gone.
    """
    try:
        value, err = post_code_json(code, url, timeout=timeout)
    except Exception as exc:  # transport failure other than a clean refusal
        value, err = None, str(exc)
    if err is not None:
        print(f"error: {err}")
        if fatal:
            sys.exit(1)
        return None
    return value


def start(url, seed):
    seed_arg = "None" if seed is None else str(seed)
    return run(
        f"""
import json
src = open(r"{FUZZER}").read()
# The file auto-starts when exec'd (for /gs-exec); drop that so we control the seed.
src = src.replace("\\nstart()", "\\npass")
ns = {{}}
exec(compile(src, r"{FUZZER}", "exec"), ns)
fuzzer = ns["start"]({seed_arg})
print(json.dumps({{"seed": fuzzer.seed, "status_path": fuzzer.status_path}}))
""",
        url,
    )


def summary(url, fatal=True):
    return run(
        """
import json, slicer
fuzzer = getattr(slicer.modules, "_interactive_seg_fuzzer", None)
print(json.dumps(None if fuzzer is None else fuzzer._summary(), default=str))
""",
        url,
        fatal=fatal,
    )


def stop(url, fatal=True):
    return run(
        """
import json, slicer
fuzzer = getattr(slicer.modules, "_interactive_seg_fuzzer", None)
if fuzzer is not None:
    fuzzer.stop()
print(json.dumps({"stopped": fuzzer is not None}))
""",
        url,
        fatal=fatal,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("seed", nargs="?", type=int, help="seed to reproduce a previous run")
    parser.add_argument("--port", type=int, default=2016, help="GeoSlicer WebServer port (default: 2016)")
    parser.add_argument(
        "--attach", action="store_true", help="follow an already-running fuzzer instead of starting one"
    )
    parser.add_argument("--stop", action="store_true", help="stop a running fuzzer and exit")
    args = parser.parse_args()

    url = f"http://localhost:{args.port}/slicer/exec"

    if args.stop:
        result = stop(url)
        print("stopped." if result["stopped"] else "no fuzzer was running.")
        return 0

    if args.attach:
        info = summary(url)
        if info is None:
            print("no fuzzer is running; drop --attach to start one.")
            return 1
        print(f"attached to running fuzzer. seed={info['seed']}")
    else:
        info = start(url, args.seed)
        print(f"fuzzer started. seed={info['seed']}")
        print(f"status file: {info['status_path']}")
    print("Ctrl-C to stop.\n")

    crashed = False
    try:
        while True:
            time.sleep(POLL_SECONDS)
            info = summary(url, fatal=False)
            if info is None:
                # Either the instance died (a native crash is itself a finding)
                # or someone stopped the fuzzer from the GeoSlicer console.
                print("lost the fuzzer: GeoSlicer is unreachable or it was stopped there.")
                return 1
            print(
                f"session={info['sessions']} tick={info['ticks']} phase={info['phase']} "
                f"plane={info['plane']} left={info['actions_left']} cfg={info['config']}"
            )
            if info["crashed"]:
                crashed = True
                print("\n=== CRASH ===")
                print(json.dumps(info["crash_info"], indent=2, default=str))
                print(
                    "\nGeoSlicer is frozen at the crash for inspection.\n"
                    "Run `python fuzz.py --stop` when you are done."
                )
                return 1
            if not info["running"]:
                print("fuzzer stopped server-side.")
                return 0
    except KeyboardInterrupt:
        print("\ninterrupted.")
        if not crashed:
            stop(url)
            print("fuzzer stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
