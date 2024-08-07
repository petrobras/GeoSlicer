#!/usr/bin/env python-real

import argparse
import sys

import numpy as np
import pygg


OPEN_ERROR_CODES = {pygg.WELL: 2, pygg.SET: 3, pygg.LOG: 4}


def __init_project(project):
    if not pygg.init(project):
        sys.exit(1)
    else:
        print(f"Initialized project (RO): {project}")


def __open(type, status, name):
    if not pygg.open(type, status, name):
        sys.exit(OPEN_ERROR_CODES[type])
    else:
        print(f"Opened {type} ({status}): {name}")


def main(project, well, sets, logs, temporary_folder):
    __init_project(project)
    __open(pygg.WELL, pygg.STATUS_OLD, well)
    __open(pygg.SET, pygg.STATUS_OLD, sets)

    for log in logs:
        __open(pygg.LOG, pygg.STATUS_OLD, log)
        result, repeat = pygg.getn(pygg.LOG_REPEAT, log)
        log_values = []
        while pygg.read():
            result, log_val = pygg.getn(pygg.LOG_VALUES, log, repeat=int(repeat))
            if not result:
                break
            log_values.append(log_val)

        np.save(f"{temporary_folder}/{log}.npy", log_values)

        pygg.close(pygg.LOG, pygg.STATUS_OLD, log)

    pygg.close(pygg.SET, pygg.STATUS_OLD, sets)
    pygg.close(pygg.WELL, pygg.STATUS_OLD, well)
    pygg.term()

    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        help="Geolog Project",
        required=True,
    )
    parser.add_argument(
        "--well",
        help="Geolog well",
        required=True,
    )
    parser.add_argument(
        "--set",
        help="Geolog set",
        required=True,
    )
    parser.add_argument("--log", help="Geolog log", required=True, nargs="+")
    parser.add_argument(
        "--tempPath",
        help="Geolog set",
        required=True,
    )
    args = parser.parse_args()

    main(args.project, args.well, args.set, args.log, args.tempPath)
