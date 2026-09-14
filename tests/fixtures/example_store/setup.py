from setuptools import find_packages, setup

setup(
    name="example-lake-store",
    version="0.3.1",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    entry_points={"datalake.backends": ["example_files=example_store.provider:backend"]},
    install_requires=[],
)
