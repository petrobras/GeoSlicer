#!/usr/bin/env python-real

import argparse
import json
import sys

import numpy as np
import pygg


class GeologOpenException(BaseException):
    pass


def __init_project(project):
    if not pygg.init(project):
        sys.exit(1)
    else:
        print("Initialized project (RO): %s" % project)


def __open(type, status, name):
    if not pygg.open(type, status, name):
        raise GeologOpenException
    else:
        print(f"Opened {type} ({status}): {name}")


def main(project, well, logical_file, overwrite, export_folder):
    return_code = 0

    __init_project(project)

    try:
        with open(f"{export_folder}/attributes.json", "r") as f:
            export_data = json.load(f)
    except FileNotFoundError:
        sys.exit(9)

    well_status = pygg.STATUS_NEW
    try:
        __open(pygg.WELL, well_status, well)
    except GeologOpenException:
        sys.exit(2)

    try:
        __open(pygg.SET, pygg.STATUS_OLD, logical_file)
        pygg.close(pygg.SET, pygg.STATUS_OLD, logical_file)

        if overwrite:
            raise (GeologOpenException)

        raise (ValueError)

    except ValueError:
        sys.exit(24)

    except GeologOpenException:
        pass

    try:
        set_status = pygg.STATUS_NEW
        __open(pygg.SET, set_status, logical_file)
    except GeologOpenException:
        sys.exit(3)

    reference = export_data["reference"]
    depth_top = reference["top"]
    depth_bottom = reference["bottom"]
    depth_increment = reference["spacing"]

    try:
        log_status = pygg.STATUS_NEW
        __open(pygg.LOG, pygg.STATUS_NEW, reference["name"])
    except GeologOpenException:
        sys.exit(4)

    log_values_dict = {}
    log_attributes = export_data["logs"]
    for log_name in log_attributes.keys():
        try:
            log_values_dict[log_name] = np.load(f"{export_folder}/{log_name}.npy")
        except FileNotFoundError:
            return_code = 31
            log_attributes.pop(log_name, None)
            print(f"couldnt not get {log_name} files. skipping log...")
            continue

    # REFERENCE attrs
    pygg.putc(pygg.LOG_UNITS, reference["name"], reference["name"])
    pygg.putc(pygg.LOG_DIMENSION, reference["name"], "1")
    pygg.putc(pygg.LOG_COMMENT, reference["name"], "Imported from GEOSLICER")

    removed_logs = []

    for log_name in log_values_dict.keys():
        try:
            log_type = log_attributes[log_name]["type"]
            __open(pygg.LOG + f"{log_type}*{log_values_dict[log_name].shape[1]}", log_status, log_name)
        except GeologOpenException:
            return_code = 32
            removed_logs.append(log_name)
            print(f"could not open log {log_name}. skipping log...")
            continue

        # LOG attrs
        try:
            unit = log_attributes[log_name]["unit"]
            dimension = log_values_dict[log_name].shape[1]
            repeat = log_values_dict[log_name].shape[1]
            top = float(log_attributes[log_name]["top"])
            bottom = float(log_attributes[log_name]["bottom"])

            if unit:
                pygg.putc(pygg.LOG_UNITS, log_name, unit)
            pygg.putc(pygg.LOG_DIMENSION, log_name, str(dimension))
            pygg.putn(pygg.LOG_REPEAT, log_name, repeat)
            pygg.putn(pygg.LOG_TOP, log_name, top)
            pygg.putn(pygg.LOG_BOTTOM, log_name, bottom)
            pygg.putc(pygg.LOG_COMMENT, log_name, "Imported from GEOSLICER")
        except ValueError:
            return_code = 33
            removed_logs.append(log_name)
            continue

    if removed_logs:
        for to_be_removed in removed_logs:
            log_attributes.pop(to_be_removed, None)
            log_values_dict.pop(to_be_removed, None)

    if not log_attributes or not log_values_dict:
        sys.exit(34)

    try:
        current_depth = depth_top
        while current_depth < depth_bottom:
            pygg.putn(pygg.LOG_VALUE, reference["name"], float(current_depth))
            for log_name in log_attributes.keys():
                log_top = log_attributes[log_name]["top"]
                log_bottom = log_attributes[log_name]["bottom"]
                if current_depth >= log_top:
                    if current_depth <= log_bottom:
                        index = int((current_depth - log_top) / depth_increment)
                        pygg.putn(pygg.LOG_VALUES, log_name, log_values_dict[log_name][index].tolist())
                    else:
                        width = len(log_values_dict[log_name][0].tolist())
                        pygg.putn(pygg.LOG_VALUES, log_name, [np.nan for z in range(width)])

            pygg.write()
            current_depth += depth_increment
    except RuntimeError:
        sys.exit(35)

    for log_name in log_attributes.keys():
        pygg.close(pygg.LOG, log_status, log_name)

    pygg.close(pygg.LOG, pygg.STATUS_NEW, reference["name"])
    pygg.close(pygg.SET, set_status, logical_file)
    pygg.close(pygg.WELL, well_status, well)
    pygg.term()

    sys.exit(return_code)


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
    parser.add_argument(
        "--overwrite",
        help="Allow overwriting set with given name",
        required=True,
    )
    parser.add_argument(
        "--tempPath",
        help="Geolog set",
        required=True,
    )
    args = parser.parse_args()

    overwrite = True if int(args.overwrite) else False

    main(args.project, args.well, args.set, overwrite, args.tempPath)
