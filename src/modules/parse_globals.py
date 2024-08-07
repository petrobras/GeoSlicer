#!/usr/bin/env python3
# -*- coding: UTF-8 -*-

import os
import re
from pathlib import Path
import csv


def parse(dirpath: Path):
    for item in os.listdir(dirpath):
        subdir = dirpath / item
        for file in os.listdir(subdir):
            filepath = str(subdir / file)
            with open(filepath, "r") as fp:
                content = fp.readlines()

            # detect missing area
            new_content = []
            for line in content:
                if re.search(r"\t0$", line):
                    print(subdir)

                # replace squared symbol
                nline = re.sub("\(mm.*\)", "mm^2", line)
                new_content.append(nline)

            with open(filepath, "w") as fp:
                fp.writelines(new_content)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Provide a directory path")

    parse(Path(sys.argv[1]))
