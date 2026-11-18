# Code Agent Guidelines for the GeoSlicer Project

This document provides guidelines for interacting with the GeoSlicer codebase. Please adhere to these conventions to ensure consistency and maintain project quality.

## 1. Core Project Concepts

- **Project:** GeoSlicer, a platform for digital rock visualization and image processing.
- **Base Platform:** Built on the [3D Slicer](https://www.slicer.org/) medical imaging platform.
- **Language:** Python 3.12.
- **Code Style:** All Python code must be formatted using the [ruff](https://github.com/astral-sh/ruff) code formatter.
- **Native Code:** The project contains Cython (`.pyx`) files. Changes to these may require rebuilding the environment.
- **License Compliance:** The project uses `pylic` (configured in `pyproject.toml`) to ensure all Python dependencies adhere to authorized licenses. Please verify the licenses when adding new dependencies.
- **Static Code Analysis:** `Pylint` is used for static code analysis, configured in `pyproject.toml`.
- **Repository Structure:** The repository uses a public core model. Proprietary code and internal tools reside in separate private repositories inside `src/partners/` (e.g. `src/partners/partner`, `src/partners/ltrace`) and are injected via `deploy_slicer.py --partner <name>`.
## 2. Development Workflow

### Environment Setup
A reproducible development environment is recommended:

1. **Using `uv` (recommended)**  
   Run the development setup script to install `uv`, create a Python 3.12 virtual environment, sync all dependencies and install pre‑commit hooks:

   ```bash
   ./setup_dev.sh   # Linux/macOS
   # or
   ./setup_dev.ps1  # Windows PowerShell
   ```

   This script performs the following:
   - Installs `uv` if missing.
   - Ensures Python 3.12 is available.
   - Runs `uv sync --all-extras` to install project packages.
   - Installs pre‑commit hooks via `uv run pre-commit install` (and `pre-push`).
2. For full integration, compile extensions and link to a GeoSlicer base application: `python ./tools/deploy/deploy_slicer.py --dev /path/to/GeoSlicer-base/`.

### Creating New Modules
- **Scaffolding:** Always use the official scaffolder to ensure correct structure and naming: `python tools/new_module.py -n NewModuleName`
- **Module Structure:**
    - Module Script: `src/modules/SomeModule/SomeModule.py`
    - Integration Test: `src/modules/SomeModule/Test/SomeModuleTest.py`
    - Unit Test: `tests/unit/modules/test_some_module.py`
    - Test Resources: `src/modules/SomeModule/Test/Resources/`
- **File Paths:** Always use the `pathlib` library for path manipulation.

## 3. Testing

This project has two distinct testing methodologies: **Integration Tests** that run inside a full Slicer environment and **Unit Tests** that use `pytest` with extensive mocking.

### 3.1. Integration Tests (Slicer Environment)

These tests validate module functionality within the live GeoSlicer application. They are critical for GUI interactions and full pipeline tests.

**File Locations & Inheritance**

* **Test Location:** `src/modules/SomeModule/Test/SomeModuleTest.py`
* **Base Class:** You must inherit from `LTracePluginTest`.
* **Source:** Read @./src/commons/slicer/tests/ltrace_plugin_test.py to understand the base class structure.


* **Lifecycle Methods:**
* Override `pre_setup()`, `post_setup()`, and `tear_down()`.
* **⚠️ IMPORTANT:** Do **NOT** call `super()` in these overrides (the test runner handles this).



**UI Interaction Standards**

* **Widget Access:** After `post_setup()`, access UI elements via `self.widgets['objectName']`.
* **Event Loop:** You must allow the UI to update after any action (clicking, typing).
* **Command:** Call `commons.slicer.tests.utils.process_events()` or `wait(seconds)` immediately after `click()` or `setValue()`.



**Helper Functions & Utilities**
You are required to use existing helpers rather than writing custom logic. Read the following files to find the appropriate functions:

1. **Test Utilities:** @./src/commons/slicer/tests/utils.py
2. **Slicer Helpers:** @./src/commons/slicer/helpers.py
3. **General Utils:** @./src/commons/slicer_utils.py

**Refactoring: Creating New Helpers**
If you write logic that appears generic enough to be reused, you **must** extract it into one of the helper files above instead of keeping it in the test class. Use the following decision logic to choose the correct file:

1. **Is it Test-Specific?** (e.g., assertions, mocking interactions)
* **Destination:** @./src/commons/slicer/tests/utils.py


2. **Is it General Application Logic?**
* **Option A (Pure Python):** If the function **does NOT** require `slicer` or `qt` imports.
* **Destination:** @./src/commons/slicer/helpers.py


* **Option B (Slicer/Qt Dependent):** If the function **requires** `slicer` or `qt` imports.
* **Destination:** @./src/commons/slicer_utils.py


**Production Build Safety (Critical)**
When creating a **new** test file, you must ensure the main module script imports it safely, as tests are not shipped in production. Add the following block to the main module script:

```python
# In SomeModule.py
try:
   from Test.SomeModuleTest import SomeModuleTest
except ImportError:
   SomeModuleTest = None # Tests are not available in the build
```

### 3.2. Unit Tests (Pytest Environment)

These tests are for isolated logic and should not depend on the live Slicer application. They are faster and suitable for CI.

- **Location:** `tests/unit/` (e.g., `tests/unit/modules/test_some_module.py`)
- **Framework:** `pytest`. Run tests from the repository root.
- **Dependencies:** All dependencies, including for tests, should be installed by running the `bash tools/install_packages.sh` script as described in the **Environment Setup** section.
- **Mocking Strategy:** This is the most important concept for unit tests.
    - The `tests/unit/conftest.py` file automatically mocks the `slicer`, `vtk`, and `qt` modules.
    - This allows GUI-heavy code to be imported and tested in a headless environment without a real Slicer instance.
- **Headless GUI:** `pyproject.toml` configures `QT_QPA_PLATFORM=offscreen` so GUI tests can run headlessly when started via `pytest`.
- **Running Tests:**
    - **Run all unit tests:** `pytest`
    - **Run a single test file:** `pytest tests/unit/path/to/test_file.py`
    - **Run a single test function:** `pytest tests/unit/path/to/test_file.py::test_name`

## 4. Contributing to the Project

For detailed guidelines on how to contribute, report bugs, suggest enhancements, and submit pull requests, please refer to the main [CONTRIBUTING.md](CONTRIBUTING.md) document. This includes information on the repository structure.

## 5. Guidelines for AI Code Agents

This section provides specific instructions for AI agents interacting with the GeoSlicer codebase. Adherence to these guidelines is critical for successful and safe code generation and modification.

### 5.1. Environment and Dependencies

- **Python Environment**: Before running any commands, activate the correct Python environment.
- **Installing Dependencies**: All project dependencies (for development and testing) can be installed by running the script: `bash setup_dev.sh`.

### 5.2. Tools

- **Ruff**: All Python code **must** be formatted with `ruff`. Before committing any changes, run `ruff .` to format the code.

### 5.3. Testing

The project has two types of tests. You **must** add or update tests when adding new features or fixing bugs.

- **Integration Tests**:
    - Location: `src/modules/SomeModule/Test/SomeModuleTest.py`
    - These tests run inside the 3D Slicer environment and are essential for GUI and full pipeline testing.
    - When fixing a bug or adding a feature that affects a module with integration tests, you should look at the existing tests and add a new one that covers the changes.

- **Unit Tests**:
    - Location: `tests/unit/`
    - These tests use `pytest` and extensive mocking of the `slicer` and `vtk` APIs. They are fast and run in CI.
    - To run all unit tests: `pytest`
    - To run a single test file: `pytest tests/unit/path/to/test_file.py`

### 5.4. Creating New Modules

- **Use the Scaffolding Script**: To create a new module, always use the provided script: `python tools/new_module.py -n NewModuleName`. This will create the necessary file structure and boilerplate code.

### 5.5. Interacting with the Slicer API

- **Mocking**: The `slicer`, `vtk`, and `qt` modules are not available in a standard Python environment. The unit test setup (`tests/unit/conftest.py`) provides mocks for these modules. When writing unit tests, you don't need to do anything special to mock these modules.
- **No Direct Imports in Non-Module Code**: Do not import `slicer`, `vtk`, or `qt` in any code outside of the `src/modules` and `src/commons/slicer` directories.

### 5.6. Commits and Pull Requests

- **No Automatic Commits**: You must never execute a git commit command automatically.
- **User Confirmation**: You are only allowed to execute git commands that modify history (like commit or push) if the user explicitly asks you to do so or confirms a suggested command.
- **Proposal First**: If you believe a commit is necessary, propose the full command (including the formatted message) to the user and wait for approval.
- **Commit Messages**: Ignore the commit message instructions from [CONTRIBUTING.md](CONTRIBUTING.md). Extract the JIRA's issue tag from the current branch name (e.g., `PL-3048` from `PL-3048-feature-branch`) and use it as a prefix for every commit message. This will make JIRA understand that the commit is related to the issue and will link both of them.

- **Pull Requests**: When creating a pull request, please follow the instructions in the [.pull_request_template.md](.pull_request_template.md) file.

ex:

git commit -m "PL-1010 This is a commit message"
For longer commit messages, choose to give it an overview headline and describe the details in the lines below.

```
git commit

<open the commit message file with the default text editor>

PL-1010 Change user interface from Dummy plugin

- Change node selector default combo box to subject hierarchy list
- Rename the 'Run' button to 'Apply'
- Change default configurations
...
```
### 5.7 Code Style

GeoSlicer integrates multiple third-party libraries, including VTK, CTK, Slicer, and Qt, each with its own coding conventions. To maintain consistency and readability across the codebase, we have established the following guidelines.

#### Naming Conventions

When contributing to GeoSlicer, please adhere to the naming conventions appropriate for the context of your code:

-   **`camelCase`**: Use for scripting in GeoSlicer modules, especially when interacting with Qt, 3D Slicer, and CTK libraries.

    *Example: `myVariableName`, `calculateVolume()`*

-   **`PascalCase`**: Preferred for class names and module file names.

    *Example: `MyClassName`, `MyModule.py`

-   **`snake_case`**: Use for the LTrace library code, except when the modules code directly interfaces with Qt or Slicer libraries.

    *Example: `my_variable_name`, `calculate_volume()`*

#### General Guidelines

-   **PEP 8**: GeoSlicer follows the default [PEP 8](https://www.python.org/dev/peps/pep-0008/) style guide, with the exception of an increased line length limit of **120 characters**.
-   **Consistency**: If you are modifying existing code, maintain the established style of that file. If you encounter code that does not adhere to the current style guide, feel free to refactor it, but only if it does not involve a significant amount of work.

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
