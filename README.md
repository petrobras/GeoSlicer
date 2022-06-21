# GeoSlicer

GeoSlicer is a software platform for digital rock visualization and image processing, encompassing multiple aprouches involving thin section, CT and mCT imagery. We use advanced technices, like Convolution Neural Networks, to deliver a unique solution that allows users to solve complex workflows from a single platform.

## Intro

The GeoSlicer code is a set of modules and auxiliary functions to work with digital rock images. The modules are installed onto a modified version of 3D Slicer which we call GeoSlicer-base. To do so, a deploy script is used to deploy install modules, generate a release, install in development mode, generate the public and opensource versions and commit them to the open source repository.
GeoSlicer-base can be obtained from pre-built binaries available for windows and linux or built from source using the geoslicerbase and internal slicer repositories. 

## Repository Structure

Basically our repository is structured as follows:

* slicerltrace
    * __general files__, documentation, README, icons
* slicerltrace/src
    * __modules__, folders define the modules, for example the Segmenter/
        * module, contain a python file of the same name. This file is the module's input and needs to follow the pattern of the others. A module folder can be generated using the new-module.py script located at the root.
    * __ltrace__, our main library. Contains codes that are agnostic to GeoSlicer and permeate several modules.
    * __ModuleNameCLI__, CLIs can be placed on several levels: at the src/modules, in a global folder of CLIs or inside a module folder. However, they must always be identified with CLI at the end of the name. Examples:
        * Root/ExampleCLI/ExampleCLI.py
        * Root/Example/ExampleCLI/ExampleCLI.py
        * Root/CLI/ExampleCLI/ExampleCLI.py
* slicerltrace/tools
    * __general scripts__, such as new-module.py
    * __tooling__, these are also folders, and implement features for developers, such as the build function that is performed by the tools in the Deploy / folder.

### Create a new GeoSlicer module
Run the command bellow to create a module from an empty template:
The "--bind" argument is optional and renames the module classes to be compatible with the LTrace Wrappers.
```console
python new-module.py -n NewModuleName [--bind]
```

## For Developers

This project uses 3D Slicer version 4.11 and beyond with support for Python 3.9.

### Windows

1. Install Git LFS (https://git-lfs.github.com/) and run `git lfs install`.

1. Download the Visual Studio Community 2019 (https://visualstudio.microsoft.com/downloads/) and execute the installer. Under the tab "Individual components", select only: MSVC v142 for x64/x86 (14.29).

1. Download (https://developer.nvidia.com/cuda-11.2.0-download-archive) and install CUDA 11.2.

1. Download (https://developer.nvidia.com/cudnn), unzip and copy the cuDNN 8.1 files to CUDA's installation directory (usually C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.2) This operation should merge the "bin" folders of CUDA and CUDNN.

1. Check your environment variables. You should have a variable CUDA_PATH_V11_2 pointing to CUDA's installation directory.

1. Download GeoSlicer base version geoslicer-1.6.0-2021-12-21-win-amd64 (or later) from https://drive.google.com/drive/folders/15vSYL31kycLnRlcQqOtpVAeNTyuFe8h5?usp=sharing

1. Run the command below to generate a GeoSlicer Development Version from a new installation of 3D Slicer or even update an existing version of GeoSlicer with new plugins during development:

    ```console
    python .\tools\deploy\deploy_slicer.py --dev "path_of_base\GeoSlicer-1.6.0-2021-12-21-win-amd64"
    ```


### Linux

1. Install C/C++ tooling according to your linux distribution.

2. Install NVIDIA and CUDNN according to your linux distribution.

3. Run the command below to generate a GeoSlicer from a new installation of 3D Slicer or even update an existing version of GeoSlicer with new plugins:

    ```console
    python3 tools/deploy/deploy_slicer.py --dev ~/Slicer-4-11-amd64/
    # or
    python3 tools/deploy/deploy_slicer.py --dev ~/Slicer-4-11-amd64.tar.gz
    ```

Obs.: Some software used to predict the scale in thin section images are included with an AppImage package, that will run in almost any distribution. But in some cases it will be necessary install FUSE manually, as can be follow [here](https://github.com/AppImage/AppImageKit/wiki/FUSE).

### Generating Manually

For developing plugins, you need to setup our environment in a Slicer installation. For that, you need to do 4 things:

1 - Install extensions that are required for some of our plugins (defined in tools/deploy/slicer_deploy_config.json).

2 - Install our shared library and python dependencies that are required by our plugins (defined in ltrace and ltrace/requirements.txt).

3 - Add our plugins to Slicer's module path.

4 - Copy some asset files to Slicer's folder (defined in Deploy/slicer_deploy_config.json).

The script in `tools/deploy/deploy_slicer.py` does that. And you can call it like this:

```console
python3 tools/deploy/deploy_slicer.py --dev ~/Slicer-4-11-amd64/
# or
python3 tools/deploy/deploy_slicer.py --dev ~/Slicer-4-11-amd64.tar.gz
```

## Deployment

To generate an archive that is self contained, so that we can deliver it to clients use:

```console
python3 tools/deploy/deploy_slicer.py ~/Slicer-4-11-amd64.tar.gz --geoslicer-version <somesuffixhere>
```
or on Windows, remeber to copy from a fresh install on AppData\Local\NA-MIC and zip it,
```console
python3 tools/deploy/deploy_slicer.py ~/Slicer-4-11-amd64.zip --geoslicer-version <somesuffixhere>
```

## Debugging

Developers can debug extensions by attaching a python debugger to Slicer. Follow the tutorial: https://www.slicer.org/wiki/Documentation/Nightly/Extensions/DebuggingTools

## Running a plugin

The installed plugins will appear on 3D Slicer Modules selector.

## Troubleshooting

Windows PATH and other environment variables influence on the installation of the modules inside GeoSlicer.
If you are having trouble installing ltrace or others, remove any references of python directories from your PATH and other environment variables.
Do not forget to restart your console after removing them.

Windows need to be configured to allow file paths longer than 260 characters, which usually hapens when installing tensorflow, to solve this, it may be necessary to allow long path names and then install tensorflow manually before running deploy:
- New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `-Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
- {geoslicer_folder}\bin\PythonSlicer.exe -m pip install tensorflow==2.7.0

Newer versions OpenCV requires Windows Media Feature, which is not automatically installed in all versions of Windows. If cv2 fails to import, this may be the problem. To install MF:
- Start Menu --> Settings --> Apps --> Apps & Features --> Optional Features --> Add a feature --> Media Feature Pack (requires reboot)

## VSCode tips

Add Slicer/bin/PythonSlicer.exe as the python interpreter


## Code style

Multiples third-party libraries are used in the Geoslicer’s base, such as vtk, ctk, slicer and Qt. Futhermore, we create code as well.

Dealing with those libraries, we will probably encounter different code styles among them, and it might confuse you how we should do our own code. A list of the code style relation is described below:

```
Qt, slicer, ctk: camelCase
vtk: PascalCase
LTrace: snake_case
```

As [discussed](https://bitbucket.org/ltrace/slicerltrace/pull-requests/626?w=1), Geoslicer will use the default PEP-8 code style (snake_case and other patterns), only enlarging the line lenght limit to 120 characters. For further details about PEP-8, please read this [article](https://www.python.org/dev/peps/pep-0008/) (30 min read).

If you find some code without the current code style, please change it if it wouldn’t be a big deal.

[Black](https://pypi.org/project/black/) was selected as the default formatter tool. You could manually use it by using the following command at the repository folder:

```
black
```

### Pre-commit hook

Install pre-commit hook to force the black code formating use as you commit the code. To install it, use the command below inside the repository folder:

```
python .\tools\install_pre_commit_hook.py 
```

If you want to avoid the pre-commit hook to trigger, use '--no-verify' or '-n' flag after the git commit command:

```
git commit -m 'Example' -n
```

