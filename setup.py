from setuptools import find_packages, setup

setup(
    name="data-lake-service",
    version="0.1.0",
    description="Reusable lake host: HTTP contract, configuration and backend interface",
    packages=find_packages(include=["data_lake_service", "data_lake_service.*"]),
    include_package_data=True,
    entry_points={"console_scripts": ["data-lake=data_lake_service.main:main"]},
    install_requires=["flask>=3.0"],
    python_requires=">=3.10",
)
