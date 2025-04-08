#!/usr/bin/env python-real
# -*- coding: utf-8 -*-
import multiprocessing.shared_memory as shm
import struct
import time

import numpy as np

from ltrace.slicer.cli_utils import progressUpdate

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LTrace Image Compute Wrapper for Slicer.")
    parser.add_argument("--namespace", type=str, default="")
    parser.add_argument("--timeout", type=int, default=300)

    args = parser.parse_args()

    print("Namespace:", args.namespace)

    shared_mem = shm.SharedMemory(name=args.namespace)

    timeout = args.timeout

    # keep checking shared memory for a float value until timeout
    start = time.time()
    while (time.time() - start) < timeout:
        try:
            data = shared_mem.buf[:8]  # Read first 8 bytes (size of a float64)
            value = struct.unpack("d", data)[0]
            if 0 <= value < 1:
                progressUpdate(value=value)
            elif value == 1:
                progressUpdate(value=1.0)
                break
            else:
                break

            time.sleep(3)
        except Exception as e:
            print("Error:", e)
            break

    print("Done")
