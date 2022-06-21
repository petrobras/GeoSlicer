from setuptools import setup, find_packages
from pathlib import Path
from Cython.Build import cythonize


THIS_FOLDER = Path(__file__).absolute().parent


with open(THIS_FOLDER / "README.md", encoding="utf-8") as f:
    long_description = f.read()

with open(THIS_FOLDER / "requirements.txt") as f:
    requirements = f.readlines()

setup(
    name="ltrace",  # Required
    version="1.0.0",  # Required
    description="Library to support LTrace modules",  # Optional
    long_description=long_description,  # Optional
    long_description_content_type="text/markdown",  # Optional (see note above)
    install_requires=requirements,
    # url='https://github.com/pnlbwh/SlicerDiffusionQC/',
    author="""LTrace Team (LTrace Geophysics)""",
    packages=find_packages(),  # Required
    include_package_data=True,
    ext_modules=cythonize("ltrace/algorithms/find_objects.pyx", language_level=3),
)
