# Contributing to GeoSlicer

First off, thank you for considering contributing to GeoSlicer!

This document is a guide to help you through the process. We have a few guidelines that we need contributors to follow so that we can have a chance of keeping on top of things.

## Code of Conduct

This project and everyone participating in it is governed by the [GeoSlicer Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior.

## How Can I Contribute?

There are many ways to contribute to GeoSlicer, from writing tutorials or blog posts, improving the documentation, submitting bug reports and feature requests or writing code which can be incorporated into GeoSlicer itself.

### Reporting Bugs

Bugs are tracked as [GitHub issues](https://github.com/petrobras/geoslicer/issues). Before creating a bug report, please check the list of existing issues to see if the bug has already been reported. If it has, please add a comment to the existing issue instead of creating a new one.

When you are creating a bug report, please include as many details as possible. Fill out the required template, the information it asks for helps us resolve issues faster.

### Suggesting Enhancements

Enhancement suggestions are tracked as [GitHub issues](https://github.com/petrobras/geoslicer/issues). Before creating an enhancement suggestion, please check the list of existing issues to see if the enhancement has already been suggested. If it has, please add a comment to the existing issue instead of creating a new one.

When you are creating an enhancement suggestion, please include as many details as possible. Fill out the required template, the information it asks for helps us to better understand the enhancement.

### Submitting Pull Requests

If you have a bugfix or a new feature that you would like to contribute to GeoSlicer, you can do so by sending a pull request. We are always thrilled to receive pull requests, and do our best to process them as fast as we can. Before you start to code, we recommend discussing your plans through a GitHub issue, especially for more ambitious contributions. This gives other contributors a chance to point you in the right direction, give you feedback on your design, and help you find out if someone else is working on the same thing.

#### Pull Request Workflow

1.  **Fork the repository** and create your branch from `master`.
2.  **Set up your development environment** by following the instructions in the [compiling guide](BUILD.md).
3.  **Make your changes.**
4.  **Run the test suite** to ensure that your changes don't break anything.

    ```bash
    pytest tests/unit -v
    ```

5.  **Commit your changes** using a descriptive commit message that follows our [commit message conventions](#commit-message-conventions).
6.  **Push your branch** to your fork.
7.  **Open a pull request** to the `master` branch of the main repository.

#### Commit Message Conventions

We use the [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) specification for our commit messages. This allows us to automatically generate changelogs and release notes. Please follow this specification for your commit messages.

Here are some examples:

*   `feat: Add new feature`
*   `fix: Fix bug`
*   `docs: Update documentation`
*   `style: Format code`
*   `refactor: Refactor code`
*   `test: Add tests`
*   `chore: Update build scripts`

## Repository Structure

The repository is structured as follows:

*   `src`: Contains all the source code.
    *   `ltrace`: The library with code shared across different modules.
    *   `modules`: Houses the various modules of the GeoSlicer application. Each module is in its own subdirectory.
        *   `ModuleName`: Each module folder contains the Python files that define its functionality. The `new_module.py` script can be used to generate a new module from a template.
        *   `ModuleNameCLI`: Command Line Interface modules are denoted by a `CLI` suffix in their folder name.
    *   `submodules`: Contains git submodules used in the project.
*   `tools`: Provides scripts and utilities for developers.
    *   `deploy`: Includes scripts for application deployment.
    *   `hooks`: Holds Git hooks for the repository.
    *   `resources`: Files used by the tool scripts.
*   The root directory also general files such as documentation and configuration files.


## Create a new GeoSlicer module

### From a template

To create a new module from a template, you can use the `new_module.py` script located in the `tools` directory. This script will generate all the necessary boilerplate files for a new module.

Run the following command from the root of the repository:

```console
python tools/new_module.py -n NewModuleName
```

You can also customize the module by using the following optional arguments:

*   `--title` or `-t`: Sets the title of the module in the GeoSlicer UI. If not provided, it will be generated from the module's name.
*   `--category` or `-c`: Specifies the category under which the module will appear in the GeoSlicer UI. The default is `Tools`.
*   `--cli`: Use this flag to include a Command Line Interface (CLI) template for your module.

**Example:**

To create a new module named "My Awesome Module" with the title "My Awesome Module" in the "LTrace Tools" category, and with a CLI, you would run:

```console
python tools/new_module.py -n "My Awesome Module" --cli
```

### Manually

If you prefer to create a module manually, follow these steps:

1.  **Create the module directory:** Inside the `src/modules` directory, create a new folder for your module (e.g., `src/modules/NewModule`).

2.  **Create the main Python file:** Inside the new module directory, create a Python file with the same name as the directory (e.g., `NewModule.py`). This file will be the entry point for your module.

3.  **Define the plugin classes:** In the main Python file, you need to define three classes:
    *   **Plugin Class:** This class should inherit from `LTracePlugin` and is responsible for defining the module's metadata, such as its title, category, and dependencies.
    *   **Widget Class:** This class should inherit from `LTracePluginWidget` and is where you will build the user interface of your module using Qt widgets.
    *   **Logic Class:** This class should inherit from `LTracePluginLogic` and will contain the core logic of your module, separating it from the UI code.

4.  **Create a CLI (Optional):** If your module requires a Command Line Interface (CLI), create a new subdirectory within your module's folder with the `CLI` suffix (e.g., `NewModuleCLI`). Place your CLI script inside this folder. Note that the CLI environment does not have access to the Qt library, so your CLI script should not contain any GUI-related code.

By following this structure, you ensure that your new module integrates correctly with the GeoSlicer framework.

### Insert the module in an environment

After creating a new module, you might want to add it to one of the existing environments in GeoSlicer, such as the MicroCT, Thin Section, or Segmentation environments. This will make your module accessible from the toolbar of that specific environment.

To do this, you need to modify the environment's setup file. For example, to add a module to the **MicroCT Environment**, you would edit the `src/modules/MicroCTEnv/MicroCTEnv.py` file.

Inside the `setupEnvironment` method of the `MicroCTEnvLogic` class, you will find a list of modules that are loaded into the environment. You can add your new module to this list.

**Example:**

Let's say you have created a new module named `MyAwesomeModule`. To add it to the MicroCT environment, you would modify the `modules` list in `MicroCTEnv.py` as follows:

```python
class MicroCTEnvLogic(LTracePluginLogic, LTraceEnvironmentMixin):
    def setupEnvironment(self):
        modules = [
            "CustomizedData",
            "MicroCTLoader",
            "MicroCTExport",
            # ...
            "MyAwesomeModule",  # Add your new module here
        ]
```

After making this change, your module will appear in the MicroCT environment's toolbar the next time you run GeoSlicer.


## Debugging

Developers can debug extensions by attaching a python debugger to Slicer. Checkout the available tools at [SlicerDebuggingTools repository](https://github.com/SlicerRt/SlicerDebuggingTools).

## IDE tips

Add GeoSlicer/bin/PythonSlicer.exe as the python interpreter


## Code Style

GeoSlicer integrates multiple third-party libraries, including VTK, CTK, Slicer, and Qt, each with its own coding conventions. To maintain consistency and readability across the codebase, we have established the following guidelines.

### Naming Conventions

When contributing to GeoSlicer, please adhere to the naming conventions appropriate for the context of your code:

-   **`camelCase`**: Use for scripting in GeoSlicer modules, especially when interacting with Qt, 3D Slicer, and CTK libraries.
    
    *Example: `myVariableName`, `calculateVolume()`*
    
-   **`PascalCase`**: Preferred for class names and when working with the VTK library.
    
    *Example: `MyClassName`, `vtkImageData`*
    
-   **`snake_case`**: Use for the LTrace library code, except when the code directly interfaces with Qt or Slicer libraries.
    
    *Example: `my_variable_name`, `calculate_volume()`*

### General Guidelines

-   **PEP 8**: GeoSlicer follows the default [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide, with the exception of an increased line length limit of **120 characters**.
-   **Consistency**: If you are modifying existing code, maintain the established style of that file. If you encounter code that does not adhere to the current style guide, feel free to refactor it, but only if it does not involve a significant amount of work.

### Auto-formatting

To ensure a consistent code style, we use [Black](https://pypi.org/project/black/) as our auto-formatter. The configuration for Black is available in the `pyproject.toml` file.

To format your code manually, run the following command from the root of the repository:

```bash
black .
```

### Typing

Adding type hints to your code is highly encouraged, as it helps other developers understand the expected inputs and outputs of functions and classes. It also improves IDE support for autocompletion and error checking.

**Example:**

```python
from typing import Callable

def register(self, model: str, builder: Callable) -> None:
    # ...
    pass
```

In this example, the `register` method is defined to accept a `model` of type `str` and a `builder` of type `Callable`, and it is specified to return `None`.


## Pre-Commit Hook

This project uses a pre-commit hook to automatically format your code with Black before each commit. This ensures that all code pushed to the repository adheres to a consistent style.

### Installation

To install the pre-commit hook, run the following command from the root of the repository:

```bash
python ./tools/install_pre_commit_hook.py
```

This script will copy the pre-commit hook to the `.git/hooks` directory and make it executable.

### Bypassing the Hook

If you need to make a commit without running the pre-commit hook, you can use the `--no-verify` or `-n` flag with the `git commit` command:

```bash
git commit -m "Your commit message" -n
```

This is useful for small changes that do not require code formatting, such as fixing a typo in the documentation.

## Troubleshooting

This section provides solutions to common problems you might encounter while installing or running GeoSlicer.

### Windows-Specific Issues

#### Long Path Limitation

On Windows, you may encounter errors if the installation path for GeoSlicer exceeds the default character limit. To resolve this, you need to enable long path support in the Windows Registry.

For detailed instructions, please refer to the official Microsoft documentation: [Enable Long Paths in Windows](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation?tabs=registry).

#### Missing Media Feature Pack

Newer versions of OpenCV, a dependency of GeoSlicer, require the Windows Media Feature Pack. If you are using a version of Windows where this is not installed by default, you may encounter errors when `cv2` fails to import.

To install the Media Feature Pack:

1.  Open the **Start Menu** and go to **Settings**.
2.  Select **Apps** > **Apps & Features**.
3.  Click on **Optional Features** and then **Add a feature**.
4.  Find and install the **Media Feature Pack**.
5.  A system reboot is required after installation.

### Linux-Specific Issues

#### GCC Compiler Not Found

If you encounter an error message indicating that the GCC compiler was not found during the installation process, it may be because the build script is looking for it in a specific, non-standard directory.

**Error Message Example:**

```console
error: command '/opt/rh/devtoolset-7/root/usr/bin/gcc' failed: No such file or directory
```

To resolve this, you can create symbolic links from the expected directory to the actual location of your GCC and G++ compilers.

**Solution:**

First, ensure that you have `gcc` and `g++` installed on your system. Then, run the following commands to create the required directory and symbolic links:

```bash
sudo mkdir -p /opt/rh/devtoolset-7/root/usr/bin/
sudo ln -s $(which gcc) /opt/rh/devtoolset-7/root/usr/bin/gcc
sudo ln -s $(which g++) /opt/rh/devtoolset-7/root/usr/bin/g++
```

These commands will create the necessary directory structure and link your system's default compilers to the location where the build script expects to find them.

### General Issues

#### Conflicting Python Interpreters in PATH

If you have multiple Python installations, your system's `PATH` environment variable might point to a different Python interpreter than the one required by GeoSlicer. This can lead to package installation failures.

To fix this, remove any references to other Python directories from your `PATH` and other relevant environment variables. Remember to restart your terminal or system for the changes to take effect.

#### GeoSlicer Restarts Indefinitely

In some cases, an incompatibility between the GeoSlicer source code and the GeoSlicerBase files can cause the application to enter a restart loop. If you notice the splash screen repeatedly appearing, try one of the following solutions:

*   **Re-deploy the application:** Delete the current GeoSlicer application directory and re-deploy it from the original compressed file (`.zip` or `.tar.gz`).
*   **Update GeoSlicerBase:** Download the latest version of GeoSlicerBase that is compatible with your version of the GeoSlicer source code.

#### Access Denied During Installation or Deployment

If you receive a "permission denied" error while running `PythonSlicer -m pip install` or during the deployment process, it is likely that a GeoSlicer instance is still running in the background. This prevents the script from modifying or deleting files that are in use.

To resolve this, ensure that all instances of GeoSlicer are closed before trying again.