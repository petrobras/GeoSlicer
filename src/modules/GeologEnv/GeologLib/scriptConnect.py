#!/usr/bin/env python-real

import argparse
import json
import sys

import pygg


def __init_project(project):
    if not pygg.init(project):
        sys.exit(1)
    else:
        print(f"Initialized project (RO): {project}")


def __open(type, status, name):
    if not pygg.open(type, status, name):
        print(f"Could not open {type} ({status}): {name}...")
        raise ValueError


def main(project, temporary_folder):
    return_code = 0

    __init_project(project)

    output = {}

    while True:
        result, well_name = pygg.getc(pygg.NEXT_WELL, pygg.STATUS_OLD)
        if not result:
            break
        try:
            __open(pygg.WELL, pygg.STATUS_OLD, well_name)
        except ValueError:
            return_code = 41
            continue

        well_sets = {}

        while True:
            result, set_name = pygg.getc(pygg.NEXT_SET, pygg.STATUS_OLD)
            if not result:
                break
            try:
                __open(pygg.SET, pygg.STATUS_OLD, set_name)
            except Exception:
                return_code = 42
                continue

            set_logs = {}

            while True:
                result, log_name = pygg.getc(pygg.NEXT_LOG, pygg.STATUS_OLD)
                if not result:
                    break
                try:
                    __open(pygg.LOG, pygg.STATUS_OLD, log_name)
                except Exception:
                    return_code = 43
                    continue

                log_attributes = {}

                result, units = pygg.getc(pygg.LOG_UNITS, log_name)
                result, comment = pygg.getc(pygg.LOG_COMMENT, log_name)
                result, sr = pygg.getc(pygg.LOG_SR, log_name)
                result, repeat = pygg.getn(pygg.LOG_REPEAT, log_name)
                result, dir = pygg.getc(pygg.LOG_LOGGED_DIRECTION, log_name)
                result, dimension = pygg.getc(pygg.LOG_DIMENSION, log_name)
                result, top = pygg.getc(pygg.LOG_TOP, log_name)
                result, bottom = pygg.getc(pygg.LOG_BOTTOM, log_name)
                result, frames = pygg.getc("*FRAMES", log_name)

                log_attributes["comment"] = comment
                log_attributes["unit"] = units
                log_attributes["sr"] = sr
                log_attributes["repeat"] = repeat
                log_attributes["dir"] = dir
                log_attributes["dimension"] = dimension
                log_attributes["frames"] = frames
                log_attributes["top"] = top
                log_attributes["bottom"] = bottom

                set_logs[log_name] = log_attributes

            pygg.close(pygg.SET, pygg.STATUS_OLD, set_name)

            well_sets[set_name] = set_logs

        output[well_name] = well_sets

        pygg.close(pygg.WELL, pygg.STATUS_OLD, well_name)

    pygg.term()

    try:
        with open(f"{temporary_folder}/output.json", "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=4)
    except:
        sys.exit(5)

    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project",
        help="Geolog Project",
    )
    parser.add_argument(
        "--tempPath",
        help="Geolog set",
        required=True,
    )
    args = parser.parse_args()

    code = main(args.project, args.tempPath)

    sys.exit(code)
