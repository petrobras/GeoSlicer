#!/usr/bin/env python-real
# -*- coding: utf-8 -*-
import struct
import time

from ltrace.slicer.cli_utils import progressUpdate

POLL_INTERVAL_SECONDS = 3
MAX_READ_FAILURES = 3


def readProgress(path):
    with open(path, "rb") as file:
        data = file.read(8)

    return struct.unpack("d", data)[0] if len(data) == 8 else None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--progressFile", type=str, default="")
    parser.add_argument("--timeout", type=int, default=300)

    args = parser.parse_args()

    print("Progress file:", args.progressFile)

    start = time.time()
    failures = 0
    while (time.time() - start) < args.timeout:
        try:
            value = readProgress(args.progressFile)
        except FileNotFoundError:
            break
        except OSError as error:
            print("Error:", error)
            value = None

        if value is None:
            failures += 1
            if failures > MAX_READ_FAILURES:
                break
        else:
            failures = 0
            if not 0 <= value <= 1:
                break
            progressUpdate(value=value)
            if value == 1:
                break

        time.sleep(POLL_INTERVAL_SECONDS)

    print("Done")
