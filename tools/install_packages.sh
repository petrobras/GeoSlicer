#!/bin/sh

repository_path=$( cd "$(dirname "$0")" ; pwd -P )/..

# Install ltrace package
python -m pip install -e "$repository_path"/src/ltrace

# Install Geoslicer modules package
python -m pip install -e "$repository_path"/src/modules

# Install pyedt package
python -m pip install -e "$repository_path"/src/submodules/pyedt

# Install porespy package
python -m pip install -e "$repository_path"/src/submodules/porespy

# Install biaep package
python -m pip install -e "$repository_path"/src/submodules/biaep

# Install tools package
python -m pip install -e "$repository_path"/tools

# Install test environment libraries
python -m pip install -r "$repository_path"/tests/unit/requirements.txt

# Install pipeline required libraries
python -m pip install -r "$repository_path"/tools/pipeline/requirements.txt

# Install deploy required libraries
python -m pip install -r "$repository_path"/tools/deploy/requirements.txt
