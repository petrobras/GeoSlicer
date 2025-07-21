#!/bin/sh

repository_path=$( cd "$(dirname "$0")" ; pwd -P )/..

# Function to check and install from a directory
install_editable_package() {
    if [ -d "$1" ]; then
        python -m pip install -e "$1"
    else
        echo "Warning: Directory not found: $1"
    fi
}

# Function to check and install requirements file
install_requirements() {
    if [ -f "$1" ]; then
        python -m pip install -r "$1"
    else
        echo "Warning: Requirements file not found: $1"
    fi
}

# Install ltrace package
install_editable_package "$repository_path"/src/ltrace

# Install Geoslicer modules package
install_editable_package "$repository_path"/src/modules

# Install Microtom required libraries
install_requirements "$repository_path"/src/modules/MicrotomRemote/Libs/microtom/requirements.txt

# Install porespy package
install_editable_package "$repository_path"/src/submodules/porespy

# Install biaep package
install_editable_package "$repository_path"/src/submodules/biaep

# Install py_pore_flow package
install_editable_package "$repository_path"/src/submodules/py_pore_flow

# Install pyflowsolver package
install_editable_package "$repository_path"/src/submodules/pyflowsolver

# Install tools package
install_editable_package "$repository_path"/tools

# Install test environment libraries
install_requirements "$repository_path"/tests/unit/requirements.txt

# Install pipeline required libraries
install_requirements "$repository_path"/tools/pipeline/requirements.txt

# Install deploy required libraries
install_requirements "$repository_path"/tools/deploy/requirements.txt
