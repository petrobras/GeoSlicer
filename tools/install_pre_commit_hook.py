import importlib
import os
import shutil
import subprocess
import sys

PYTHON_INTERPRETER = sys.executable
# Ensured that the required libraries for the pre-commit is installed
REQUIRED_LIB_LIST = [("black", "22.3.0"), ("pylint", "2.15.0")]
USE_SHELL = True if sys.platform.startswith("linux") else False

print("Checking if required libraries are installed:")
for lib_name, lib_version in REQUIRED_LIB_LIST:
    try:
        print(f"\tImporting python module: {lib_name}... ", end="")
        module_obj = importlib.__import__(lib_name)
        if module_obj.__version__ != lib_version:
            del module_obj
            raise RuntimeError("Wrong version")

        print("OK!")
    except ModuleNotFoundError:
        print(f"ERROR! Module {lib_name} not found. Running pip to install it.")
        subprocess.run(f"{PYTHON_INTERPRETER} -m pip install {lib_name}=={lib_version}", shell=USE_SHELL, check=True)
    except RuntimeError:
        print(f"ERROR! Found module {lib_name} with different version. Running pip to install it.")
        subprocess.run(
            f"{PYTHON_INTERPRETER} -m pip install --upgrade {lib_name}=={lib_version}", shell=USE_SHELL, check=True
        )


current_dir = os.path.abspath(os.path.dirname(__file__))
sample_file = os.path.join(current_dir, "hooks", "pre-commit")
destiny_file = os.path.join(current_dir, "..", ".git", "hooks", "pre-commit")
if os.path.isfile(destiny_file):
    os.remove(destiny_file)

shutil.copyfile(sample_file, destiny_file)

if sys.platform == "linux":
    subprocess.run(f"chmod +x {destiny_file}", check=True, shell=USE_SHELL, cwd=current_dir)

# Define git blame 'ignore commits' file
BLAME_IGNORE_FILE = ".git-blame-ignore-revs"
print(f"Defining git blame 'ignore' file config to {BLAME_IGNORE_FILE}...")
subprocess.run(f"git config blame.ignoreRevsFile {BLAME_IGNORE_FILE}", check=True, shell=USE_SHELL, cwd=current_dir)

print("Pre-commit hook installed!")
