#!/bin/sh

repository_path=$( cd "$(dirname "$0")" ; pwd -P )/..

# Install ltrace package
python -m pip install -e "$repository_path"/src/ltrace

# Install Geoslicer modules package
python -m pip install -e "$repository_path"/src/modules

# Install Microtom required libraries
python -m pip install -r "$repository_path"/src/modules/MicrotomRemote/Libs/microtom/requirements.txt

# Install porespy package
python -m pip install -e "$repository_path"/src/submodules/porespy

# Install biaep package
python -m pip install -e "$repository_path"/src/submodules/biaep

# Install py_pore_flow package
python -m pip install -e "$repository_path"/src/submodules/py_pore_flow

# Install py_pore_flow package
python -m pip install -e "$repository_path"/src/submodules/pyflowsolver

# Install tools package
python -m pip install -e "$repository_path"/tools

# Install test environment libraries
python -m pip install -r "$repository_path"/tests/unit/requirements.txt

# Install pipeline required libraries
python -m pip install -r "$repository_path"/tools/pipeline/requirements.txt

# Install deploy required libraries
python -m pip install -r "$repository_path"/tools/deploy/requirements.txt
