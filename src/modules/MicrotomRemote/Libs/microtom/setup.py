import io
import logging
import os
import re

from pathlib import Path
from setuptools import find_packages, setup

THIS_FOLDER = Path(__file__).absolute().parent


def read(filename):
    filename = os.path.join(os.path.dirname(__file__), filename)
    text_type = type("")
    text = ""
    with io.open(filename, mode="r", encoding="utf-8") as fd:
        try:
            text = re.sub(text_type(r":[a-z]+:`~?(.*?)`"), text_type(r"``\1``"), fd.read())
        except Exception as error:
            logging.debug(f"Error: {error}")

    return text


try:
    with open(THIS_FOLDER / "requirements.txt") as f:
        requirements = f.readlines()
except Exception as error:
    raise RuntimeError(f"Invalid requirements file. Error: {error}")


setup(
    name="microtom",
    version="0.1.0",
    url="https://git.ep.petrobras.com.br/DRP/microtom",
    license="MIT",
    author="Marcelo Albuquerque, Rodrigo Surmas",
    author_email="mralbuquerque@petrobras.com.br, surmas@petrobras.com.br",
    description="Manipulation of Microtomography images in python",
    long_description=read("README.md"),
    packages=find_packages(exclude=("tests",)),
    install_requires=requirements,
    package_data={"microtom": ["templates/*.sh"]},
    entry_points={
        "console_scripts": [
            "microtom_hello_world=microtom.cli_cluster:microtom_hello_world",
            "microtom_nc2tiffolder=microtom.cli_plotting:microtom_nc2tiffolder",
            "microtom_nc2raw=microtom.cli_plotting:microtom_nc2raw",
            "microtom_tiffolder2nc=microtom.cli_plotting:microtom_tiffolder2nc",
            "microtom_tar2nc=microtom.cli_plotting:microtom_tar2nc",
            "microtom_mozaic_img=microtom.cli_plotting:microtom_mozaic_img",
            "microtom_mozaic_video=microtom.cli_plotting:microtom_mozaic_video",
            "microtom_tiffolder2tar=microtom.cli_plotting:microtom_tiffolder2tar",
            "microtom_move_files2folder=microtom.cli_plotting:microtom_move_files2folder",
            "microtom_process_tiffolder=microtom.cli_plotting:microtom_process_tiffolder",
            "microtom_process_cluster=microtom.cli_plotting:microtom_process_cluster",
            "microtom_show=microtom.cli_cluster:microtom_show",
            "microtom_extract=microtom.cli_cluster:microtom_extract",
            "microtom_psd=microtom.cli_cluster:microtom_psd",
            "microtom_hpsd=microtom.cli_cluster:microtom_hpsd",
            "microtom_micp=microtom.cli_cluster:microtom_micp",
            "microtom_krel=microtom.cli_cluster:microtom_krel",
            "microtom_stokes_kabs=microtom.cli_cluster:microtom_stokes_kabs",
        ]
    },
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
)
