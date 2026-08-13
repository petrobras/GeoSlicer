#!/usr/bin/env python-real
# -*- coding: utf-8 -*-

from __future__ import print_function

import json
import numpy as np
import os
import re
import subprocess
import sys
import tempfile

from pathlib import Path
from ltrace.slicer.cli_utils import progressUpdate


def getProgress(bufferedLine):
    progressLinePattern = r"=== .* \((\d+)/(\d+)\) ==="
    match = re.search(progressLinePattern, bufferedLine)
    if match:
        i = int(match.group(1))
        j = int(match.group(2))
        return (i - 1) / j
    return 0


def capitalizedToHyphenated(arg):
    match = re.search(r"[A-Z]", arg)
    if match:
        capIndex = match.start()
        arg = arg[:capIndex] + "-" + arg[capIndex:].lower()
    return f"--{arg}"


def runcli(args):
    python_executable = sys.executable
    script_path = (Path(__file__).parent / "Libs" / "pore_stats" / "pore_stats.py").as_posix()
    required_args = [args.inputDir, args.outputDir]
    optional_paths = [
        "--pore-model",
        args.poreModel,
        "--seg-cli",
        args.segCLI,
        "--inspector-cli",
        args.inspectorCLI,
        "--foreground-cli",
        args.foregroundCLI,
        "--remove-spurious-cli",
        args.removeSpuriousCLI,
        "--clean-resin-cli",
        args.cleanResinCLI,
    ]
    optional_params = (
        np.array([[capitalizedToHyphenated(param), value] for param, value in json.loads(args.params).items()])
        .flatten()
        .tolist()
    )
    optional_flags = [capitalizedToHyphenated(flag) for flag, checked in json.loads(args.flags).items() if checked]
    fixed_flags = ["--netcdf", "--exclude-ooids"]
    # fixed_flags += ["--resize"]  # faster execution for debugging purposes only. Leave it commented or delete.

    # Route stderr to a temp file instead of a pipe: we only read stdout during
    # execution, and if the child writes more than the OS pipe buffer (~64 KB
    # on Windows) it would block on stderr and freeze stdout too. The file is
    # kept after the run so its contents can be inspected.
    stderr_log = tempfile.NamedTemporaryFile(mode="wb+", prefix="porestats_cli_stderr_", suffix=".log", delete=False)
    try:
        process = subprocess.Popen(
            [python_executable]
            + [script_path]
            + required_args
            + optional_paths
            + optional_params
            + optional_flags
            + fixed_flags,
            bufsize=1,  # line buffered
            stdout=subprocess.PIPE,
            stderr=stderr_log,
            text=True,
            shell=True if sys.platform.startswith("win32") else False,
        )

        progress = 0
        for line in process.stdout:
            progress = max(getProgress(line), progress)
            progressUpdate(progress)

        progressUpdate(1)
        process.wait()

        if process.returncode != 0:
            stderr_log.seek(0)
            error_text = stderr_log.read().decode("utf-8", errors="replace")
            raise RuntimeError(error_text)
    finally:
        stderr_log.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Calculate pore and ooids statistics for a set of thin section images.",
    )
    parser.add_argument(
        "--inputdir", type=str, dest="inputDir", help="Path of the input directory containing thin section images"
    )
    parser.add_argument(
        "--outputdir", type=str, dest="outputDir", help="Path of the output directory of the final results"
    )
    parser.add_argument("--params", type=str, help="Segmentation parameters")
    parser.add_argument("--flags", type=str, help="Binary options")
    parser.add_argument("--poremodel", type=str, dest="poreModel", help="Model to use for the binary pore segmentation")
    parser.add_argument(
        "--segcli", type=str, dest="segCLI", default=None, help="Path to the pore segmentation CLI to use"
    )
    parser.add_argument(
        "--inspectorcli", dest="inspectorCLI", type=str, default=None, help="Path to the segment inspector CLI to use"
    )
    parser.add_argument(
        "--foregroundcli", dest="foregroundCLI", type=str, default=None, help="Path to the smart foreground CLI to use"
    )
    parser.add_argument(
        "--removespuriouscli",
        dest="removeSpuriousCLI",
        type=str,
        default=None,
        help="Path to the spurious removal CLI to use",
    )
    parser.add_argument(
        "--cleanresincli", dest="cleanResinCLI", type=str, default=None, help="Path to the resin cleaning CLI to use"
    )

    args = parser.parse_args()

    runcli(args)
