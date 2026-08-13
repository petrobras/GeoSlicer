from setuptools import setup, find_namespace_packages

setup(
    name="modules",
    version="1.0.0",
    description="Geoslicer modules",
    author="""LTrace Team (LTrace Geophysics)""",
    packages=find_namespace_packages(),
    include_package_data=True,
)
